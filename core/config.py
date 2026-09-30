# -*- coding: utf-8 -*-
"""配置加载：读 config.yaml 到内存，带默认值"""
import os
import re
import sys
import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# PyInstaller 打包后资源在 sys._MEIPASS；否则用项目根目录
if hasattr(sys, "_MEIPASS"):
    CONFIG_PATH = os.path.join(sys._MEIPASS, "config.yaml")
else:
    CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

_DEFAULTS = {
    "message_source": {"type": "wcferry", "weflow_base": "http://127.0.0.1:5031"},
    "ai": {"base_url": "https://api.deepseek.com/v1", "api_key": "", "model": "deepseek-chat",
           "max_tokens": 800, "vision_model": ""},
    "video": {"enabled": True, "platforms": ["bilibili.com", "youtube.com", "douyin.com"],
              "fetch_comments": True, "use_pipeline": False},
    # 汇总频率（分层规则）：免打扰群每周 / 活跃群每天 / @我实时 / 视频实时
    "schedule": {"muted_group_weekly": "sun 21:00", "daily_stats": "21:00",
                 "realtime_video": True, "realtime_at_me": True},
    # 选中即分析（划词 → DeepSeek → 悬浮输出）
    "selection": {
        "enabled": True,
        "hotkey": "ctrl+alt+d",
        "overlay": {"enabled": True, "width": 420, "height": 560, "opacity": 0.96,
                    "position": "top-right", "auto_hide_sec": 0},
        "kind": {"video": "realtime", "link": "ai", "chat": "ai", "text": "ai", "emoji": "vision"},
    },
    "push": {"serverchan_key": "", "pushplus_token": "", "wecom_webhook": "",
             "toast": True, "overlay": True, "txt_file": "output/summary.txt"},
    "focus": {"contacts": [], "muted_rooms": [], "active_rooms": [], "notify_at_me": True},
    "db": {"path": "data/msgs.db"},
    "backfill": {"enabled": True, "lookback_hours": 24},
}


def load(path: str = CONFIG_PATH) -> dict:
    """读取并合并配置；文件缺失时用默认值兜底（逐层深合并，防旧配置缺键）"""
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _DEFAULTS.items()}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        _deep_update(cfg, user_cfg)
    _migrate(cfg)
    return cfg


def _deep_update(base: dict, new: dict) -> None:
    """递归合并：dict 内的键也要合并（旧配置文件缺新键时不报错）"""
    for k, v in (new or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def _migrate(cfg: dict) -> None:
    """兼容旧配置键（用户可能还留着上一版的 config.yaml）"""
    sc = cfg.setdefault("schedule", {})
    if "muted_group_daily" in sc and "muted_group_weekly" not in sc:
        # 旧「每日汇总免打扰群」→ 新「每周汇总免打扰群」
        sc["muted_group_weekly"] = "sun " + str(sc.pop("muted_group_daily"))
    if "weekly_report" in sc and "daily_stats" not in sc:
        # 旧「每周出统计」→ 新「每天出统计」
        old = str(sc.pop("weekly_report"))
        sc["daily_stats"] = old.split()[-1] if old else "21:00"
    cfg.setdefault("focus", {}).setdefault("active_rooms", [])
    cfg["focus"].setdefault("notify_at_me", True)
    cfg.setdefault("ai", {}).setdefault("vision_model", "")


# ---------------------------------------------------------------------------
# 写回：从网页界面保存配置（只改用户提交的键，其余保持原样）
# ---------------------------------------------------------------------------

# 允许网页界面写入的路径白名单（防止任意键被覆盖）
_WRITABLE = {
    "ai.base_url", "ai.api_key", "ai.model", "ai.max_tokens", "ai.vision_model",
    "message_source.type", "message_source.weflow_base",
    "push.serverchan_key", "push.pushplus_token", "push.wecom_webhook",
    "push.toast", "push.overlay",
    "focus.muted_rooms", "focus.active_rooms", "focus.notify_at_me",
    "video.enabled", "video.fetch_comments",
    "schedule.muted_group_weekly", "schedule.daily_stats",
    "selection.hotkey", "selection.overlay.enabled",
    "backfill.enabled", "backfill.lookback_hours",
}


def _set_path(d: dict, path: str, value) -> None:
    """按点号路径写值，中间层不存在则创建"""
    keys = path.split(".")
    cur = d
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value


def _get_path(d: dict, path: str, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _flatten(patch: dict, prefix: str = "") -> dict:
    """
    把嵌套字典拍平成「点号键」，兼容两种前端写法：
      {"ai": {"api_key": "sk-x"}}        →  {"ai.api_key": "sk-x"}
      {"ai.api_key": "sk-x"}             →  {"ai.api_key": "sk-x"}
    ⚠️ 不加这层兼容时，传嵌套结构会因 key 不在白名单而被**静默忽略**，
    表现为接口返回 ok:true 但 written:[]、配置其实没改（很难查）。
    """
    out = {}
    for k, v in (patch or {}).items():
        full = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, full))
        else:
            out[full] = v
    return out


def update(patch: dict, path: str = CONFIG_PATH) -> dict:
    """
    把网页界面提交的部分配置合并进 config.yaml 并落盘。

    - 只接受 _WRITABLE 白名单里的键（其余忽略）
    - 支持「点号扁平键」和「嵌套字典」两种写法（内部统一拍平）
    - 值为 None / 空字符串且原值非空 时：视为「不改动」（避免误清空已有 key）
    - 返回实际写入的键列表
    """
    # 读原始文件（不套默认值，避免把默认值一股脑写进去）
    raw = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raw = {}

    written = []
    for key, val in _flatten(patch).items():
        if key not in _WRITABLE:
            continue
        if val is None:
            continue
        if isinstance(val, str):
            val = val.strip()
            # 空字符串 = 不修改（保护已填的 key 不被误清空）
            if val == "":
                continue
            if key in ("focus.muted_rooms", "focus.active_rooms"):
                # 逗号/换行分隔 → 列表
                val = [x.strip() for x in val.replace("，", ",").replace("\n", ",").split(",") if x.strip()]
            elif key == "ai.max_tokens":
                try:
                    val = int(val)
                except ValueError:
                    continue
        _set_path(raw, key, val)
        written.append(key)

    # 原子写 + **保留注释**：
    # 早年直接用 yaml.safe_dump 重写，会把 config.yaml 里的所有中文注释和排版全部抹掉
    # （用户精心写的说明一夜清零，属于不可逆的数据损失）。
    # 改成「原地改行」：只替换目标 key 那一行，其余行原样保留。
    _write_preserving_comments(path, written, raw)
    return {"written": written}


def _dump_scalar(val, old_line: str = "") -> str:
    """
    把 Python 值转成可直接写进 yaml 单行的字面量。

    old_line 传入旧行时，会尽量沿用旧行的引号风格（原本带引号的字符串继续带引号），
    避免「只改了值、却把 `"deepseek-chat"` 变成 `deepseek-chat`」这种无意义的 diff。
    """
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        return "[" + ", ".join(_dump_scalar(v) for v in val) + "]"
    s = str(val)
    # 含特殊字符时必须加引号
    need_quote = s == "" or any(c in s for c in ":#{}[],&*?|>'\"%@`")
    # 旧值本来就带引号 → 保持带引号，减少无谓 diff
    if not need_quote and old_line:
        old_val = old_line.split(":", 1)[-1]
        old_val = old_val.split("#", 1)[0].strip()
        if len(old_val) >= 2 and old_val[0] == old_val[-1] and old_val[0] in "\"'":
            need_quote = True
    if need_quote:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _keep_trailing_comment(old_line: str) -> str:
    """
    从旧行里取出行尾注释（如 `api_key: "sk-x"   # 换成你的 key` 里的 `# 换成你的 key`）。
    重写值那一行时把它接回去，避免用户写的行内说明丢失。
    找不到就返回空串。
    """
    # 只在引号外的 '#' 才算注释起始，简单处理：取最后一个 ' #'
    idx = old_line.find("#")
    if idx < 0:
        return ""
    core = old_line[:idx]
    # 引号成对才认为是「真的注释」，否则 # 在字符串里
    if core.count('"') % 2 or core.count("'") % 2:
        return ""
    return old_line[idx:].rstrip()


def _write_preserving_comments(path: str, keys: list, raw: dict) -> None:
    """
    只改 keys 里那几个键的行，其它内容（注释、空行、注释块）一字不动。

    做法：把文件按行读入，用「顶层键 / 二级键」的缩进状态机定位目标行并替换。
    找不到的目标键则追加到对应段落末尾（或文件末尾新建）。
    """
    lines = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")

    # 目标键 → (父键, 子键)，parent 为空表示顶层
    targets = {}
    for k in keys:
        if "." in k:
            parent, child = k.split(".", 1)
            targets.setdefault(parent, {})[child] = True
        else:
            targets[k] = None

    done = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # 顶层键（无缩进、非注释）
        m_top = re.match(r"^([A-Za-z_][\w\-]*)\s*:(.*)$", line)
        if m_top and m_top.group(1) in targets:
            parent = m_top.group(1)
            sub = targets[parent]
            if sub is None:                       # 顶层标量
                val = raw.get(parent)
                if val is not None and not isinstance(val, dict):
                    cmt = _keep_trailing_comment(line)
                    lines[i] = f"{parent}: {_dump_scalar(val, line)}" + (f"  {cmt}" if cmt else "")
                    done.add(parent)
                i += 1
                continue
            # 进入该段落，往下找二级键
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() and not nxt.startswith((" ", "\t", "#")):
                    break                          # 回到顶层，段落结束
                m_sub = re.match(r"^(\s+)([A-Za-z_][\w\-]*)\s*:(.*)$", nxt)
                if m_sub and m_sub.group(2) in sub:
                    child = m_sub.group(2)
                    val = (raw.get(parent) or {}).get(child)
                    if val is not None:
                        cmt = _keep_trailing_comment(nxt)
                        lines[j] = (f"{m_sub.group(1)}{child}: {_dump_scalar(val, nxt)}"
                                    + (f"  {cmt}" if cmt else ""))
                        done.add(f"{parent}.{child}")
                j += 1
            # 有没找到的子键 → 追加到段落末尾
            for child in sub:
                full = f"{parent}.{child}"
                if full not in done:
                    val = (raw.get(parent) or {}).get(child)
                    if val is not None:
                        lines.insert(j, f"  {child}: {_dump_scalar(val)}")
                        j += 1
            i = j
            continue
        i += 1

    # 完全没出现在文件里的顶层键 → 追加到文件末尾
    for k in keys:
        top = k.split(".", 1)[0]
        if top in done or (top in targets and targets[top] is None and top in done):
            continue
        if top not in done and top in targets and targets[top] is None:
            val = raw.get(top)
            if val is not None and not isinstance(val, dict):
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append(f"{top}: {_dump_scalar(val)}")
                done.add(top)

    text = "\n".join(lines)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def mask_key(key: str) -> str:
    """把 key 变成 'sk-ab****yz' 形式，用于回显（绝不返回完整 key）"""
    if not key:
        return ""
    k = str(key)
    if len(k) <= 8:
        return "*" * len(k)
    return f"{k[:5]}{'*' * 6}{k[-4:]}"


def is_real_key(key: str) -> bool:
    """
    判断 api_key 是不是「真的填了」。

    为什么不能只用 bool()：config.yaml 里默认写着 `sk-xxxxxxxx` 这种占位符，
    bool() 会返回 True → 首页误判成「已配置」→ 用户永远看不到「去填 key」的引导，
    只在真正调用 AI 时才失败，非常难排查。

    规则：
      - 空 / None          → 不是
      - 含占位符特征（xxxxxxxx / your / 你的 / 换成 / 填）→ 不是
      - 明显是真实 key     → 是（sk- 开头且长度足够，或 >= 20 位的高熵串）
    """
    if not key:
        return False
    k = str(key).strip()
    if len(k) < 12:
        return False                          # 太短，肯定不是有效 key
    low = k.lower()
    placeholders = ("xxxxxxxx", "your", "你的", "换成", "填", "example", "todo", "changeme")
    if any(p in low for p in placeholders):
        return False
    return True
