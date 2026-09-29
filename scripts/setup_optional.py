# -*- coding: utf-8 -*-
"""
一键把「可选依赖」装进项目内的 vendor/ 目录（隔离环境，不污染主环境）
======================================================================

为什么需要这个脚本：
  `pywxdump`（开机补读微信本地库）硬锁 `protobuf==3.10.0`，
  而 `wcferry`（实时监听）要求 `protobuf>=5.29` —— 3.10.0 里没有
  `google.protobuf.internal.builder`，会让 wcferry 直接 ImportError。
  **两者无法共存于同一环境。**

  所以方案是：主环境只装轻量的 wcferry；把 pywxdump 装到 vendor/ 下
  的独立 venv 里，`core/history_backfill.py` 会自动找到它。

用法：
  python scripts/setup_optional.py              # 装全部可选依赖
  python scripts/setup_optional.py --only wxdump
  python scripts/setup_optional.py --list       # 只看当前状态

产物：
  vendor/pywxdump_venv/     ← 独立 venv（约 60 MB，可随安装包一起分发）
"""
import argparse
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(BASE, "vendor")
WXDUMP_VENV = os.path.join(VENDOR, "pywxdump_venv")

# 国内镜像（清华对 pip 返回 403，用腾讯云）
MIRROR = "https://mirrors.cloud.tencent.com/pypi/simple"


def _python_in(venv: str) -> str:
    return os.path.join(venv, "Scripts", "python.exe") if os.name == "nt" \
        else os.path.join(venv, "bin", "python")


def _clean_env() -> dict:
    """去掉代理与宿主注入，避免 pip 卡住 / 子进程被 shim 干扰"""
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy",
                                "node_options", "electron_run_as_node")}
    return env


def setup_wxdump(force: bool = False) -> bool:
    """把 pywxdump 装进 vendor/pywxdump_venv"""
    py = _python_in(WXDUMP_VENV)
    if os.path.exists(py) and not force:
        r = subprocess.run([py, "-c", "import pywxdump; print(pywxdump.__version__)"],
                           capture_output=True, text=True, env=_clean_env())
        if r.returncode == 0:
            print(f"  ✅ pywxdump 已就绪（{r.stdout.strip()}），跳过")
            return True
        print("  已存在但不可用，重新安装…")

    os.makedirs(VENDOR, exist_ok=True)
    print(f"  创建独立 venv: {WXDUMP_VENV}")
    r = subprocess.run([sys.executable, "-m", "venv", WXDUMP_VENV],
                       env=_clean_env())
    if r.returncode != 0:
        print("  ❌ venv 创建失败")
        return False

    print("  安装 pywxdump（约 60 MB，需 1-3 分钟）…")
    r = subprocess.run([py, "-m", "pip", "install", "-q",
                        "--disable-pip-version-check", "-i", MIRROR, "pywxdump"],
                       env=_clean_env())
    if r.returncode != 0:
        print("  ❌ 安装失败（检查网络；国内可试 -i 换镜像）")
        return False

    r = subprocess.run([py, "-c",
                        "import pywxdump; from pywxdump import get_wx_info;"
                        "print('OK', pywxdump.__version__)"],
                       capture_output=True, text=True, env=_clean_env())
    if r.returncode == 0:
        print(f"  ✅ pywxdump 安装成功（{r.stdout.strip()}）")
        return True
    print(f"  ⚠️ 安装完成但导入失败：{r.stderr.strip()[:200]}")
    return False


def fix_protobuf() -> bool:
    """
    确保主环境的 protobuf 是新版（>=5.29）。
    装 pywxdump 时若不小心动了主环境，protobuf 会被降到 3.10.0，
    导致 wcferry 报 `cannot import name 'builder'`。
    """
    r = subprocess.run([sys.executable, "-c",
                        "import google.protobuf as p; print(p.__version__)"],
                       capture_output=True, text=True, env=_clean_env())
    ver = r.stdout.strip() if r.returncode == 0 else ""
    if ver and ver.split(".")[0].isdigit() and int(ver.split(".")[0]) >= 5:
        print(f"  ✅ protobuf {ver} 正常")
        return True
    print(f"  protobuf 当前为 {ver or '缺失'}，需升级到 >=5.29（wcferry 依赖）")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "--disable-pip-version-check", "-i", MIRROR,
                        "protobuf>=5.29"], env=_clean_env())
    ok = r.returncode == 0
    print("  ✅ protobuf 已升级" if ok else "  ❌ 升级失败")
    return ok


def status():
    print("可选依赖状态：")
    py = _python_in(WXDUMP_VENV)
    if os.path.exists(py):
        r = subprocess.run([py, "-c", "import pywxdump; print(pywxdump.__version__)"],
                           capture_output=True, text=True, env=_clean_env())
        print(f"  pywxdump(隔离): {'✅ ' + r.stdout.strip() if r.returncode == 0 else '❌ 不可用'}")
    else:
        print("  pywxdump(隔离): ❌ 未安装")
    r = subprocess.run([sys.executable, "-c",
                        "import google.protobuf as p; print(p.__version__)"],
                       capture_output=True, text=True, env=_clean_env())
    print(f"  主环境 protobuf: {r.stdout.strip() if r.returncode == 0 else '缺失'}")
    for m in ("wcferry", "fastapi", "openai", "jieba", "yt_dlp"):
        r = subprocess.run([sys.executable, "-c", f"import {m}"],
                           capture_output=True, text=True, env=_clean_env())
        print(f"  {m}: {'✅' if r.returncode == 0 else '❌'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["wxdump"], help="只装某一项")
    ap.add_argument("--force", action="store_true", help="强制重装")
    ap.add_argument("--list", action="store_true", help="只看状态")
    a = ap.parse_args()

    if a.list:
        status()
        return

    print("=== 检查主环境 protobuf（wcferry 依赖）===")
    fix_protobuf()

    if a.only == "wxdump":
        print("=== 安装可选依赖：pywxdump（隔离 venv）===")
        setup_wxdump(force=a.force)
    else:
        print("=== 安装可选依赖：pywxdump（隔离 venv）===")
        setup_wxdump(force=a.force)

    print()
    status()


if __name__ == "__main__":
    main()
