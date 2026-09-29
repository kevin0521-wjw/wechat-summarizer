# -*- coding: utf-8 -*-
"""
开机补读本地微信数据库（解决 Q1「关机期间的消息」）
====================================================
原理：电脑关机时消息由手机收，等开机后微信 PC 端会从服务器把历史消息同步到本地库。
本模块在启动时用 PyWxDump 解密本地库，把「上次运行以来漏掉的消息」补读进 Store，
保证统计 / 每日汇总 / 周报不丢样本。

依赖：pip install pywxdump（这里只调它的 CLI，不碰它不稳定的 Python API）

⚠️ **强烈建议把 pywxdump 装在独立 venv**（见下）：它硬锁 `protobuf==3.10.0`，
而主环境需要的 wcferry 要求 `protobuf>=5.29`（3.10.0 没有 `google.protobuf.internal.builder`，
会让 wcferry 直接 ImportError）。两个包在同一环境里**无法共存**。
本模块会自动去下面这几个位置找 `wxdump` 可执行文件：
  1. PATH 上的 `wxdump`
  2. 项目内的 `vendor/pywxdump_venv/Scripts/wxdump.exe`（随仓库一起分发）
  3. `~/.workbuddy/binaries/python/envs/wxdump/Scripts/wxdump.exe`（本机独立环境）

流程：
  wxdump wx_info   → 拿数据库密钥 key + 数据目录
  wxdump decrypt   → 解密出明文 .db
  sqlite3 读消息表 → 按时间戳过滤 → 归一化成统一 msg dict → 落库

⚠️ 需实测微调的点（集中在下面，方便你改）：
  1. wxdump 各子命令输出格式随版本变化 → 解析集中在 get_wechat_key_and_dir()
  2. 微信 3.x / 4.0 库文件名与消息表名不同 → 用候选列表遍历
  3. PyWxDump 从内存取 key，要求微信正在运行；解密大库需几分钟
  4. **微信 4.x（Weixin.exe / 4.1.x）的库结构和 3.9.x 差异大**，
     PyWxDump 3.1.46 对 4.x 支持不完整，wx_info 可能取不到 key —— 这时补读会静默跳过，
     不影响实时监听（wcferry）和其它功能。

参考：WeChatMsg/留痕（LC044）底层用的就是 PyWxDump（xaoyaoo/PyWxDump）的解密能力。
"""
import os
import re
import sys
import time
import sqlite3
import subprocess
from typing import Callable, Optional

# 消息表候选（微信 3.x 用 MSG，4.0 结构不同，遍历尝试）
MSG_TABLE_CANDIDATES = ["MSG", "Message", "message", "ChatMsg", "msg"]


def _find_wxdump() -> Optional[str]:
    """
    定位 wxdump 可执行文件。按以下顺序找：
      1) 环境变量 WXDUMP_BIN（显式指定）
      2) 项目内 vendor/pywxdump_venv（随安装包分发，最优先，因为有隔离的 protobuf）
      3) 本机 ~/.workbuddy/binaries/python/envs/wxdump（独立 venv）
      4) PATH 上的 wxdump
    找不到返回 None。
    """
    exe = "wxdump.exe" if os.name == "nt" else "wxdump"

    # 1) 显式指定
    env_bin = os.environ.get("WXDUMP_BIN")
    if env_bin and os.path.exists(env_bin):
        return env_bin

    # 2) 项目内（打包后资源在 sys._MEIPASS；开发时在包目录旁边）
    roots = []
    if hasattr(sys, "_MEIPASS"):
        roots.append(sys._MEIPASS)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots.append(here)
    for root in roots:
        for rel in (os.path.join("vendor", "pywxdump_venv", "Scripts", exe),
                    os.path.join("vendor", "pywxdump_venv", "bin", exe)):
            p = os.path.join(root, rel)
            if os.path.exists(p):
                return p

    # 3) 本机独立 venv
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    for rel in (("Scripts", exe), ("bin", exe)):
        p = os.path.join(home, ".workbuddy", "binaries", "python",
                         "envs", "wxdump", *rel)
        if os.path.exists(p):
            return p

    # 4) PATH
    from shutil import which
    found = which("wxdump")
    if found:
        return found
    return None


# 缓存查找结果，避免每条消息都去 stat 文件
_WXDUMP_CACHE = {"path": None, "checked": False}


def wxdump_bin() -> Optional[str]:
    if not _WXDUMP_CACHE["checked"]:
        _WXDUMP_CACHE["path"] = _find_wxdump()
        _WXDUMP_CACHE["checked"] = True
        if _WXDUMP_CACHE["path"]:
            print(f"[backfill] 使用 wxdump: {_WXDUMP_CACHE['path']}")
        else:
            print("[backfill] 未找到 wxdump（补读功能不可用；"
                  "实时监听不受影响。安装见 README「可选依赖」）")
    return _WXDUMP_CACHE["path"]


def _run(cmd: list, timeout: int = 120) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def get_wechat_key_and_dir() -> Optional[dict]:
    """拿数据库密钥 key 与数据目录。返回 {"key","wx_dir"}；失败 None

    ⚠️ 实测（2026-09-30，微信 4.1.15.13）：PyWxDump 3.1.46 只认微信 3.x 的
    进程名 `WeChat.exe`，对微信 4.x 的 `Weixin.exe` 会直接报 `WeChat No Run`
    —— 即使微信明明开着。此时本函数返回 None，补读静默跳过（不影响实时监听）。
    """
    bin_path = wxdump_bin()
    if not bin_path:
        print("[backfill] 未安装 pywxdump，跳过补读")
        return None
    # 子命令名随版本变：3.1.46 是 `info` / `wx_path`（旧版文档写的是 wx_info/wx_db）
    out = ""
    for sub in ("info", "wx_info"):
        try:
            out = _run([bin_path, sub], timeout=90)
        except Exception as e:
            print(f"[backfill] {sub} 调用失败: {e}")
            continue
        if out.strip() and "No Run" not in out:
            break
        if "No Run" in out:
            print("[backfill] wxdump 报 'WeChat No Run' —— 微信未运行，"
                  "或微信版本不受支持（4.x 的 Weixin.exe 不被 PyWxDump 3.x 识别）")
            return None

    key = None
    m = re.search(r"\b[0-9a-fA-F]{64}\b", out)
    if m:
        key = m.group(0)

    wx_dir = None
    mdir = re.search(r"[A-Za-z]:[\\/][^\r\n\"<>]*?(?:xwechat_files|WeChat Files)[^\r\n\"<>]*", out)
    if mdir:
        wx_dir = mdir.group(0).strip().rstrip("\\/")
    else:
        for sub in ("wx_path", "wx_db"):
            try:
                lines = [l for l in _run([bin_path, sub], timeout=60).splitlines() if l.strip()]
                # wx_path 在找不到时会抛 NoneType，这里靠异常/空行兜住
                cand = [l for l in lines if re.search(r"[A-Za-z]:[\\/]", l)]
                if cand:
                    wx_dir = cand[-1].strip().rstrip("\\/")
                    break
            except Exception:
                continue

    if not key:
        print("[backfill] 未能解析出数据库密钥（微信 4.x 常见；跳过补读不影响其它功能）")
        return None
    return {"key": key, "wx_dir": wx_dir}


def decrypt_db(wx_dir: str, key: str) -> Optional[str]:
    """解密微信数据库，返回可遍历的根目录"""
    if not wx_dir:
        return None
    try:
        out = _run([wxdump_bin(), "decrypt", "--db-path", wx_dir, "--key", key], timeout=600)
        print(f"[backfill] decrypt 完成: {out[:160]}")
    except Exception as e:
        print(f"[backfill] 解密失败: {e}")
    # 解密产物一般在原目录或 decrypted 子目录，哪个存在用哪个
    for root in (wx_dir, os.path.join(wx_dir, "decrypted"), "decrypted"):
        if os.path.isdir(root) and _find_dbs(root):
            return root
    return wx_dir


def backfill(store, since_ts: int, on_message: Optional[Callable[[dict], None]] = None) -> int:
    """
    主入口：补读 since_ts 之后的消息。
    - on_message 默认 None：只落库（供统计/汇总），不触发实时视频解析/推送，避免开机轰炸。
    - 传 on_message 则会复用完整处理逻辑（含视频解析），慎用。
    返回补读条数。
    """
    info = get_wechat_key_and_dir()
    if not info:
        return 0
    root = decrypt_db(info["wx_dir"], info["key"])
    if not root:
        return 0

    count = 0
    for db_path in _find_dbs(root):
        try:
            count += _read_db(db_path, since_ts, store, on_message)
        except Exception as e:
            print(f"[backfill] 读库 {db_path} 失败: {e}")
    if count:
        print(f"[backfill] 共补读 {count} 条")
    return count


def _find_dbs(root: str) -> list:
    dbs = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.endswith(".db"):
                dbs.append(os.path.join(dirpath, f))
    return dbs


def _table_columns(conn, table: str) -> list:
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


def _read_db(db_path: str, since_ts: int, store, on_message) -> int:
    conn = sqlite3.connect(db_path)
    count = 0
    for table in MSG_TABLE_CANDIDATES:
        cols = _table_columns(conn, table)
        if not cols:
            continue
        ts_col = next((c for c in ("CreateTime", "createTime", "time", "ts", "timestamp") if c in cols), None)
        content_col = next((c for c in ("StrContent", "content", "Content", "message", "msg") if c in cols), None)
        if not ts_col or not content_col:
            continue
        try:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE {ts_col} >= ? ORDER BY {ts_col} ASC",
                (since_ts,),
            ).fetchall()
        except Exception:
            continue

        for row in rows:
            d = dict(zip(cols, row))
            ts = int(d.get(ts_col) or 0)
            sender = str(d.get("StrTalker") or d.get("sender") or "")
            msg = {
                "msg_id": str(d.get("MsgSvrID") or d.get("msg_id") or d.get("id") or f"bf_{ts}_{count}"),
                "sender": sender,
                "room_id": "",
                "is_group": False,
                "type": int(d.get("Type") or d.get("type") or 0),
                "content": str(d.get(content_col) or ""),
                "xml": str(d.get("BytesExtra") or d.get("xml") or ""),
                "ts": ts,
                "is_self": bool(d.get("IsSender") or d.get("is_self") or 0),
            }
            if sender.endswith("@chatroom"):   # 微信群消息的标志
                msg["is_group"] = True
                msg["room_id"] = sender
            store.add(msg)
            if on_message is not None:
                try:
                    on_message(msg)
                except Exception:
                    pass
            count += 1
    conn.close()
    return count
