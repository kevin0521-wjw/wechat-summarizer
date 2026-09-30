# -*- coding: utf-8 -*-
"""
以「完全脱离父进程」的方式启动网页版服务。

为什么需要这个脚本
------------------
在 WorkBuddy 沙箱里用 bash 的 `&` / `nohup` / run_in_background 启动 `web/app.py` 时，
Python 进程会在启动瞬间被杀掉（日志 0 字节、端口无监听、exit 0），
但同一条命令加个管道在**前台**跑却是正常的 —— 说明是进程与调用方的生命周期绑定问题。

解法：用 subprocess 的 DETACHED_PROCESS 标志启动，进程不再挂在调用者的控制台上，
调用结束后依然存活。

用法
----
  python tools/serve-detached.py                # 默认 8090 端口
  python tools/serve-detached.py --port 9000
  python tools/serve-detached.py --stop         # 停掉占用该端口的进程
  python tools/serve-detached.py --status       # 查看是否在跑
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(BASE_DIR, "output", "web-server.log")

# Windows 进程创建标志：脱离控制台 + 新进程组 + 不继承句柄
_DETACHED = 0x00000008 | 0x00000200 | 0x08000000


def _pids_on_port(port: int) -> list:
    """找出监听指定端口的进程 PID（Windows netstat）"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="utf-8", errors="ignore").stdout or ""
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.append(int(parts[-1]))
    return sorted(set(pids))


def _health(port: int, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def stop(port: int) -> int:
    pids = _pids_on_port(port)
    if not pids:
        print(f"[serve] {port} 端口没有在跑的进程")
        return 0
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        print(f"[serve] 已停止 PID {pid}")
    return 0


def status(port: int) -> int:
    pids = _pids_on_port(port)
    ok = _health(port)
    print(f"[serve] 端口 {port}: {'🟢 在跑' if ok else '🔴 未响应'}"
          + (f"  PID={pids}" if pids else "  （无监听进程）"))
    return 0 if ok else 1


def start(port: int, host: str) -> int:
    if _pids_on_port(port):
        print(f"[serve] {port} 端口已被占用，先用 --stop 停掉，或换 --port")
        return 1

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log = open(LOG_PATH, "w", encoding="utf-8")

    python = sys.executable
    cmd = [python, "-u", os.path.join("web", "app.py"),
           "--port", str(port), "--host", host, "--no-listener"]
    print(f"[serve] 启动：{' '.join(cmd)}")

    kwargs = dict(cwd=BASE_DIR, stdout=log, stderr=subprocess.STDOUT,
                  stdin=subprocess.DEVNULL)
    if os.name == "nt":
        kwargs["creationflags"] = _DETACHED
    else:
        kwargs["start_new_session"] = True        # POSIX: setsid 等价效果

    p = subprocess.Popen(cmd, **kwargs)
    print(f"[serve] 已脱离父进程启动，PID = {p.pid}")

    # 轮候健康检查（最多 15 秒）
    for _ in range(30):
        time.sleep(0.5)
        if _health(port):
            print(f"[serve] ✅ 已就绪 → http://127.0.0.1:{port}")
            print(f"[serve] 日志：{LOG_PATH}")
            return 0

    print("[serve] ❌ 15 秒内没起来，日志如下：")
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            print(f.read())
    except Exception:
        pass
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="脱离父进程启动网页版服务")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--stop", action="store_true", help="停掉端口上的进程")
    ap.add_argument("--status", action="store_true", help="查看运行状态")
    args = ap.parse_args()

    if args.stop:
        return stop(args.port)
    if args.status:
        return status(args.port)
    return start(args.port, args.host)


if __name__ == "__main__":
    sys.exit(main())
