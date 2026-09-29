# -*- coding: utf-8 -*-
"""
微信消息 AI 助手 —— CLI 入口
==============================
命令行方式启动：监听微信消息 + AI 总结 + 推送。

若要看图形界面，请用网页版（web/app.py）或 PC 桌面版（desktop/）。

用法（在项目根目录）：
  python main.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import load
from core.engine import Engine


def main():
    cfg = load()
    Engine(cfg).start()


if __name__ == "__main__":
    main()
