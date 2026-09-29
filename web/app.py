# -*- coding: utf-8 -*-
"""
网页版后端（FastAPI）
======================
启动后在浏览器打开 http://127.0.0.1:8080 即可用（手机/平板连同一 Wi-Fi 也能访问）：
- 实时消息流 / 数据统计 / 历史汇总
- 手动触发每日/每周汇总
- 配置概览

PWA：手机浏览器「添加到主屏幕」后，可像 App 一样全屏使用（manifest.json + sw.js）。

用法：
  python web/app.py                     # 默认 0.0.0.0:8080，启动微信监听
  python web/app.py --port 9000
  python web/app.py --no-listener       # 只开界面，不连微信（演示/调试）
"""
import os
import sys
import time
import socket
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import load
from core.engine import Engine

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# PyInstaller 打包后资源在 sys._MEIPASS；否则用项目根目录
if hasattr(sys, "_MEIPASS"):
    STATIC_DIR = os.path.join(sys._MEIPASS, "web", "static")
else:
    STATIC_DIR = os.path.join(BASE_DIR, "web", "static")

app = FastAPI(title="微信消息 AI 助手", version="1.1.0")
engine: Engine = None


def create_engine(start_listener: bool = True) -> Engine:
    global engine
    engine = Engine(load())
    if start_listener:
        engine.start_background()
    return engine


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "listener": engine is not None}


@app.get("/api/stats")
def stats():
    if engine is None:
        return JSONResponse({"error": "未初始化"}, status_code=503)
    return engine.get_stats()


@app.get("/api/messages")
def messages(since: int = Query(0), limit: int = Query(100)):
    now = int(time.time())
    if engine is None:
        return {"messages": [], "now": now}
    return {"messages": engine.messages_since(since, limit), "now": now}


@app.get("/api/summaries")
def summaries(limit: int = Query(50)):
    if engine is None:
        return []
    return engine.summaries(limit)


@app.post("/api/summarize")
def summarize(kind: str = "daily"):
    if engine is None:
        return JSONResponse({"error": "未初始化"}, status_code=503)
    return engine.trigger_summary(kind)


@app.post("/api/analyze")
def analyze(payload: dict = None):
    """
    选中即分析：把一段文字/聊天记录/链接交给 DeepSeek，返回结果。
    body: {"text": "...", "hint": "text|chat|link|video|emoji", "use_clipboard": false}
    """
    if engine is None:
        return JSONResponse({"error": "未初始化"}, status_code=503)
    payload = payload or {}
    text = payload.get("text")
    hint = payload.get("hint", "")
    use_clip = bool(payload.get("use_clipboard", False)) and text is None
    try:
        return engine.analyze_selection(text=text, hint=hint, use_clipboard=use_clip)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/selection_config")
def selection_config():
    """给桌面端/前端读热键与悬浮窗配置"""
    cfg = engine.cfg if engine is not None else load()
    sel = cfg.get("selection", {})
    return {
        "enabled": sel.get("enabled", True),
        "hotkey": sel.get("hotkey", "ctrl+alt+d"),
        "overlay": sel.get("overlay", {}),
        "kinds": sel.get("kind", {}),
    }


@app.get("/api/config")
def config():
    cfg = engine.cfg if engine is not None else load()
    return {
        "message_source": cfg["message_source"]["type"],
        "model": cfg["ai"]["model"],
        "schedule": cfg["schedule"],
        "video_enabled": cfg["video"]["enabled"],
        "backfill_enabled": cfg.get("backfill", {}).get("enabled", True),
        "push_channels": _push_channels(cfg),
    }


def _push_channels(cfg: dict) -> dict:
    p = cfg["push"]
    return {
        "serverchan": bool(p.get("serverchan_key")),
        "pushplus": bool(p.get("pushplus_token")),
        "wecom": bool(p.get("wecom_webhook")),
        "toast": bool(p.get("toast", True)),
        "txt": True,
    }


# ---------------------------------------------------------------------------
# 首页 + PWA 资源
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/manifest.json")
def manifest():
    return FileResponse(os.path.join(STATIC_DIR, "manifest.json"), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"), media_type="application/javascript")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-listener", action="store_true", help="不启动微信监听，仅展示界面")
    args = parser.parse_args()

    create_engine(start_listener=not args.no_listener)

    import uvicorn
    print(f"[web] 本机访问   http://127.0.0.1:{args.port}")
    print(f"[web] 手机/平板 http://{_lan_ip()}:{args.port}   （需连同一 Wi-Fi）")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
