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


def verify_exe(port: int = 8099) -> bool:
    """
    构建后自检：真的把 backend.exe 启动起来，问一次 /api/health。

    为什么必须做：PyInstaller 是静态分析，漏掉模块时**构建仍然成功**，
    只有运行时才报 `ModuleNotFoundError`。曾经就因此打出了装包里 exe 起不来的版本
    （app.py 的 `from core import config` 没被收集到）。构建脚本自检能当场抓住。
    """
    import subprocess
    import time
    import urllib.request

    exe = os.path.join(DIST, "backend.exe")
    if not os.path.exists(exe):
        print(f"  ❌ 未找到产物：{exe}")
        return False

    _banner("构建后自检：启动 exe 并请求 /api/health")
    log_path = os.path.join(ROOT, "build-tmp", "selfcheck.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    DETACHED = 0x00000008 | 0x00000200 | 0x08000000
    with open(log_path, "w", encoding="utf-8") as log:
        p = subprocess.Popen(
            [exe, "--port", str(port), "--no-listener"],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=DETACHED if os.name == "nt" else 0,
        )

    ok = False
    try:
        for _ in range(60):          # --onefile 首次要解压，给足 30 秒
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    if r.status == 200:
                        print(f"  ✅ exe 启动正常，/api/health → {r.read().decode()[:80]}")
                        ok = True
                        break
            except Exception:
                pass
        if not ok:
            print("  ❌ 30 秒内没起来 —— 下面是 exe 的输出：")
            try:
                with open(log_path, encoding="utf-8", errors="ignore") as f:
                    print("  " + "\n  ".join(f.read().splitlines()[:20]))
            except Exception:
                pass
    finally:
        try:
            p.terminate()
            time.sleep(0.5)
        except Exception:
            pass
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
        except Exception:
            pass

    return ok


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
        # ⚠️ 必须把仓库根目录加入搜索路径：
        # app.py 里的 `from core import config` 依赖它自己那句 sys.path.insert，
        # 但那是**运行时**才执行的，PyInstaller 静态分析时看不到 →
        # 不传 --paths 打出来的 exe 会报 `ModuleNotFoundError: No module named 'core'`。
        "--paths", ROOT,
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
    # core 下的模块也显式声明，避免动态引用（getattr/字符串）时被漏掉
    for mod in ("core", "core.config", "core.engine", "core.summarizer",
                "core.stats", "core.message_source", "core.pusher", "core.scheduler",
                "core.dispatcher", "core.selection", "core.video_parser"):
        args += ["--hidden-import", mod]

    pyi.run(args)

    copy_vendor()

    if not verify_exe():
        print("\n❌ 自检未通过：exe 起不来，别急着打包 Electron（会做出装不上的安装包）")
        sys.exit(2)

    _banner("打包完成")
    print(f"  exe: {os.path.join(DIST, 'backend.exe')}")
    print("  下一步：cd desktop && npm run dist   # 出 Electron 安装包（含上面的产物）")


if __name__ == "__main__":
    main()
