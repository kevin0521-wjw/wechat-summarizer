# -*- coding: utf-8 -*-
"""
环境自检 —— 一条命令看清「哪些功能可用、哪些不可用、为什么」
================================================================
用法：python scripts/doctor.py

输出一张表：每项检查 = ✅通过 / ⚠️降级 / ❌不可用，并给出具体原因和解决建议。
微信 4.x 用户尤其建议先跑这个，免得在「实时监听起不来」上浪费时间。
"""
import os
import re
import sys
import shutil
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

OK, WARN, FAIL, INFO = "✅", "⚠️", "❌", "  "


def _banner(t):
    print(f"\n{'=' * 62}\n{t}\n{'=' * 62}")


def check_python():
    v = sys.version_info
    ok = (3, 10) <= (v.major, v.minor) <= (3, 13)
    tag = OK if ok else WARN
    print(f"{tag} Python {v.major}.{v.minor}.{v.micro}  ({sys.executable})")
    if not ok:
        print("     建议 3.10–3.13；3.14 部分依赖没有预编译 wheel")
    return ok


CORE_MODULES = [
    ("wcferry", "实时监听微信（实时消息/视频自动解析）", True),
    ("fastapi", "网页版后端", True),
    ("uvicorn", "ASGI 服务器", True),
    ("yaml", "读配置", True),
    ("openai", "调 DeepSeek 做总结", True),
    ("schedule", "定时汇总", True),
    ("jieba", "中文分词（热词统计）", True),
    ("yt_dlp", "视频字幕/评论解析", True),
    ("PIL", "图标生成 / 读剪贴板图片", True),
    ("requests", "HTTP 请求 / 推送", True),
]


def check_modules():
    print("\n【核心依赖】")
    missing = []
    for mod, desc, required in CORE_MODULES:
        try:
            __import__(mod)
            print(f"{OK} {mod:12s} {desc}")
        except ImportError as e:
            missing.append(mod)
            tag = FAIL if required else WARN
            print(f"{tag} {mod:12s} {desc}  ← 缺失: {e}")
    if missing:
        print(f"\n  修复：pip install -r requirements.txt")
        print(f"        国内加镜像 -i https://mirrors.cloud.tencent.com/pypi/simple")
    return not missing


def check_protobuf():
    """protobuf 版本是 wcferry 能否 import 的关键"""
    print("\n【protobuf（wcferry 的隐藏依赖）】")
    try:
        import google.protobuf as p
        ver = p.__version__
    except ImportError:
        print(f"{WARN} protobuf 未安装（若不用 wcferry 可忽略）")
        return True
    major = int(ver.split(".")[0])
    if major >= 5:
        print(f"{OK} protobuf {ver}（wcferry 需要 >=3.20 的 builder）")
        return True
    print(f"{FAIL} protobuf {ver} 太旧 → wcferry 会报 "
          f"`cannot import name 'builder'`")
    print(f"     修复：pip install \"protobuf>=5.29\"")
    return False


def check_wechat():
    """判断微信有没有跑、是不是 4.x（4.x 不被 hook 框架支持）"""
    print("\n【微信进程与版本】")
    if os.name != "nt":
        print(f"{INFO} 非 Windows，跳过")
        return None
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception as e:
        print(f"{WARN} 无法查询进程: {e}")
        return None

    has_wechat3 = bool(re.search(r'"WeChat\.exe"', out, re.I))
    has_wechat4 = bool(re.search(r'"Weixin\.exe"', out, re.I))

    if has_wechat4 and not has_wechat3:
        print(f"{WARN} 检测到微信 4.x（Weixin.exe）")
        print(f"     → wcferry 实测无法注入（wcf.exe 退出码 4）")
        print(f"     → pywxdump 报 'WeChat No Run'")
        print(f"     → 可用：「选中即分析 + 悬浮窗」等不依赖 hook 的功能")
        print(f"     → 要实时监听：降级到微信 3.9.x")
        return "v4"
    if has_wechat3:
        print(f"{OK} 检测到微信 3.x（WeChat.exe）—— hook 框架支持良好")
        return "v3"
    print(f"{WARN} 未检测到微信进程（微信没开，或进程名不同）")
    print(f"     实时监听需要微信运行；「选中即分析」不需要")
    return None


def check_wxdump():
    print("\n【可选依赖：wxdump（开机补读本地库）】")
    try:
        from core.history_backfill import wxdump_bin
        p = wxdump_bin()
    except Exception as e:
        print(f"{WARN} 检查失败: {e}")
        return False
    if not p:
        print(f"{WARN} 未找到 wxdump（补读不可用，其它功能不受影响）")
        print(f"     安装：python scripts/setup_optional.py")
        return False
    print(f"{OK} 已找到：{p}")
    try:
        r = subprocess.run([p, "info"], capture_output=True, text=True, timeout=90)
        out = (r.stdout or "") + (r.stderr or "")
        if "No Run" in out:
            print(f"{WARN} wxdump 报 'WeChat No Run' "
                  f"（微信 4.x 不支持；或微信没开）")
            return False
        print(f"{OK} wxdump 可读取微信信息")
        return True
    except Exception as e:
        print(f"{WARN} wxdump 调用失败: {e}")
        return False


def check_config():
    print("\n【配置】")
    try:
        from core.config import load
        cfg = load()
    except Exception as e:
        print(f"{FAIL} 配置加载失败: {e}")
        return False
    ok = True
    key = cfg.get("ai", {}).get("api_key", "")
    if not key or key == "sk-xxxxxxxx":
        print(f"{WARN} ai.api_key 未填 → AI 分析会返回「未配置 AI key」")
        print(f"     去 config.yaml 填入 DeepSeek key")
        ok = False
    else:
        print(f"{OK} ai.api_key 已配置（长度 {len(key)}）")

    vm = cfg.get("ai", {}).get("vision_model", "")
    print(f"{OK if vm else INFO} ai.vision_model: {vm or '未填（表情包识别不可用，可选）'}")

    for field, label in (("muted_rooms", "免打扰群(每周汇总)"),
                         ("active_rooms", "活跃群(每日统计)")):
        v = cfg.get("focus", {}).get(field, [])
        tag = OK if v else WARN
        print(f"{tag} focus.{field}: {v or '空（该功能无对象可汇总）'}")
        if not v:
            ok = False

    push = cfg.get("push", {})
    chans = [k for k in ("serverchan_key", "pushplus_token", "wecom_webhook") if push.get(k)]
    print(f"{OK if chans else INFO} 手机推送通道: {chans or '未配（仅悬浮窗/Toast/落盘可用）'}")
    return ok


def check_web():
    print("\n【网页版端口】")
    import socket
    for port in (8080, 8090):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            print(f"{OK} 端口 {port} 可用")
        except OSError:
            print(f"{WARN} 端口 {port} 被占用（启动时用 --port 换一个）")
        finally:
            s.close()


def check_node():
    print("\n【桌面版（Electron）】")
    node = shutil.which("node")
    if node:
        v = subprocess.run([node, "-v"], capture_output=True, text=True).stdout.strip()
        print(f"{OK} Node {v}")
    else:
        print(f"{WARN} 未找到 Node（桌面版/悬浮窗需要；网页版不需要）")
    d = os.path.join(BASE, "desktop", "node_modules", "electron")
    print(f"{OK if os.path.isdir(d) else WARN} Electron 依赖: "
          f"{'已安装' if os.path.isdir(d) else '未装（cd desktop && npm install）'}")


def main():
    _banner("微信消息 AI 助手 —— 环境自检")
    check_python()
    check_modules()
    check_protobuf()
    wx = check_wechat()
    check_wxdump()
    check_config()
    check_web()
    check_node()

    _banner("结论")
    if wx == "v4":
        print("微信是 4.x：实时监听不可用（上游限制），但以下功能完全可用 ——")
        print("  • 桌面版「选中即分析 + 悬浮窗」（Ctrl+Alt+D）")
        print("  • 网页版「手动粘贴分析」")
        print("  • 视频/链接解析、聊天记录分析、表情包识别")
        print("  • 历史汇总查看、PWA 手机端")
        print("\n想要实时监听 → 需把微信降级到 3.9.x")
    elif wx == "v3":
        print("微信 3.x：实时监听应可用。启动后看日志有没有 "
              "[engine] 后台监听已启动")
    else:
        print("微信未运行：先启动微信，再跑 python web/app.py")
    print("\n启动界面（零风险，不连微信）："
          "\n  python web/app.py --no-listener --port 8090")


if __name__ == "__main__":
    main()
