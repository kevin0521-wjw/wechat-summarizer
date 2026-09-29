# -*- coding: utf-8 -*-
"""
把网页版后端打包成 backend.exe（供 Electron 桌面版分发用）
================================================================
产物：backend-dist/backend.exe（PyInstaller --onefile）

用法：
  pip install pyinstaller
  python scripts/setup_optional.py     # 先装可选依赖（pywxdump 隔离环境）
  python scripts/build_backend.py

说明：
  - config.yaml 和 web/static 会打进 exe（运行时从 sys._MEIPASS 读取）
  - **vendor/pywxdump_venv 不打进 exe**（一个 venv 里有大量 .pyd/.dll，
    PyInstaller 处理不了嵌套解释器）。它改为放在 exe 旁边，
    由 electron-builder 的 extraResources 一并复制进安装包，
    history_backfill.py 会自动在同级目录找到它。
  - Electron 的 extraResources 会把 backend-dist/ 整个塞进安装包。

打包后的目录布局（安装包里）：
  resources/
    backend/
      backend.exe
      vendor/pywxdump_venv/     ← 可选：随包分发的隔离环境（约 100 MB）
    ...
"""
import os
import sys
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP = ";" if os.name == "nt" else ":"
DIST = os.path.join(ROOT, "backend-dist")


def _banner(msg: str):
    print(f"\n=== {msg} ===")


def check_optional_deps():
    """提示可选依赖状态（不阻塞构建）"""
    _banner("检查可选依赖")
    venv = os.path.join(ROOT, "vendor", "pywxdump_venv")
    exe = os.path.join(venv, "Scripts", "wxdump.exe" if os.name == "nt" else "wxdump")
    if os.path.exists(exe):
        print(f"  ✅ pywxdump 隔离环境就绪：{exe}")
        print("     （会随安装包一起分发，用户无需自行安装）")
        return True
    print("  ⚠️ 未找到 vendor/pywxdump_venv")
    print("     → 「开机补读微信本地库」功能在打包版里不可用（其它功能不受影响）")
    print("     → 需要的话先跑：python scripts/setup_optional.py")
    return False


def copy_vendor():
    """把 vendor/ 复制到 backend-dist/（与 backend.exe 同级）"""
    src = os.path.join(ROOT, "vendor")
    if not os.path.isdir(src):
        return
    dst = os.path.join(DIST, "vendor")
    _banner(f"复制可选依赖到产物目录\n  {src}  →  {dst}")
    if os.path.exists(dst):
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(dst) for f in fs)
    print(f"  已复制 {total / 1024 / 1024:.1f} MB")


def main():
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print("未安装 pyinstaller，请先：pip install pyinstaller")
        sys.exit(1)

    check_optional_deps()

    args = [
        os.path.join(ROOT, "web", "app.py"),
        "--name", "backend",
        "--onefile",
        "--console",
        "--add-data", f"{os.path.join(ROOT, 'web', 'static')}{SEP}web/static",
        "--add-data", f"{os.path.join(ROOT, 'config.yaml')}{SEP}.",
        "--distpath", DIST,
        "--workpath", os.path.join(ROOT, "build-tmp"),
        "--specpath", os.path.join(ROOT, "build-tmp"),
        "--clean",
    ]
    # 隐藏导入：这几个是动态 import / 被 openai 间接使用的
    for mod in ("uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                "uvicorn.lifespan.on", "wcferry", "jieba"):
        args += ["--hidden-import", mod]

    pyi.run(args)

    copy_vendor()

    _banner("打包完成")
    print(f"  exe: {os.path.join(DIST, 'backend.exe')}")
    print("  下一步：cd desktop && npm run dist   # 出 Electron 安装包（含上面的产物）")


if __name__ == "__main__":
    main()
