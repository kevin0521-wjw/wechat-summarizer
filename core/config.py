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
    "ai": {"base_url": "https://api.deepseek.com/v1", "api_key": "", "model": "deepseek-chat", "max_tokens": 800},
    "video": {"enabled": True, "platforms": ["bilibili.com", "youtube.com", "douyin.com"]},
    "schedule": {"muted_group_daily": "21:00", "weekly_report": "mon 09:00", "realtime_video": True},
    "push": {"serverchan_key": "", "pushplus_token": "", "wecom_webhook": "", "toast": True, "txt_file": "output/summary.txt"},
    "focus": {"contacts": [], "muted_rooms": []},
    "db": {"path": "data/msgs.db"},
}


def load(path: str = CONFIG_PATH) -> dict:
    """读取并合并配置；文件缺失时用默认值兜底"""
    cfg = _DEFAULTS.copy()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        # 浅合并（够用：默认值 + 用户覆盖）
        for k, v in user_cfg.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg
