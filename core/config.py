# -*- coding: utf-8 -*-
"""配置加载：读 config.yaml 到内存，带默认值"""
import os
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


def update(patch: dict, path: str = CONFIG_PATH) -> dict:
    """
    把网页界面提交的部分配置合并进 config.yaml 并落盘。

    - 只接受 _WRITABLE 白名单里的键（其余忽略）
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
    for key, val in (patch or {}).items():
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

    # 原子写：先写临时文件再替换，避免写一半崩了把配置弄坏
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    os.replace(tmp, path)
    return {"written": written}


def mask_key(key: str) -> str:
    """把 key 变成 'sk-ab****yz' 形式，用于回显（绝不返回完整 key）"""
    if not key:
        return ""
    k = str(key)
    if len(k) <= 8:
        return "*" * len(k)
    return f"{k[:5]}{'*' * 6}{k[-4:]}"
