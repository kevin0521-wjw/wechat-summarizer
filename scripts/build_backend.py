# -*- coding: utf-8 -*-
"""
把网页版后端打包成 backend.exe（供 Electron 桌面版分发用）
================================================================
产物：backend-dist/backend.exe（PyInstaller --onefile）

用法：
  pip install pyinstaller
  python scripts/build_backend.py

说明：
  - 打包后，config.yaml 和 web/static 会打进 exe（运行时从 sys._MEIPASS 读取）
  - Electron 的 extraResources 会把 backend-dist/ 一并塞进安装包
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP = ";" if os.name == "nt" else ":"


def main():
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print("未安装 pyinstaller，请先：pip install pyinstaller")
        sys.exit(1)

    args = [
        os.path.join(ROOT, "web", "app.py"),
        "--name", "backend",
        "--onefile",
        "--console",
        "--add-data", f"{os.path.join(ROOT, 'web', 'static')}{SEP}web/static",
        "--add-data", f"{os.path.join(ROOT, 'config.yaml')}{SEP}.",
        "--distpath", os.path.join(ROOT, "backend-dist"),
        "--workpath", os.path.join(ROOT, "build-tmp"),
        "--specpath", os.path.join(ROOT, "build-tmp"),
        "--clean",
    ]
    pyi.run(args)
    print(f"\n打包完成：{os.path.join(ROOT, 'backend-dist', 'backend.exe')}")


if __name__ == "__main__":
    main()
