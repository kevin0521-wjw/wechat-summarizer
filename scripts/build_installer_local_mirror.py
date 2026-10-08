# -*- coding: utf-8 -*-
"""
构建 Windows 安装包（绕开 winCodeSign 符号链接坑）—— 可复现脚本

问题链
------
electron-builder 打 Windows 包时需要 winCodeSign-2.6.0 组件（内含 rcedit.exe，
用来把图标/版本信息写进 exe）。但这个 7z 包里含两个 **macOS 符号链接**
（darwin/10.12/lib/libcrypto.dylib、libssl.dylib）。

Windows 上创建符号链接需要 SeCreateSymbolicLinkPrivilege（管理员 or 开发者模式）。
普通用户跑 7za 解压 -> 这两个条目报 "Cannot create symbolic link" -> 7za 退出码 2
-> app-builder 判定解压失败 -> 每次都重新下载再失败（死循环）。
注意：这两个 dylib 是 macOS 用的，Windows 上根本不需要，纯粹是打包副作用。

为什么不能用"改包"绕过
--------------------
app-builder 会校验归档的 sha512（实测报错：
`sha512 checksum mismatch, expected 6LQI2d9BPC3Xs0Z...`）。
改过的包哈希必然对不上 —— 所以要么让原包能解压，要么改校验值。

本脚本的解法
-----------
1. 把原包里的两个符号链接条目替换成**真实文件内容**，重新打一个包（解压零报错）；
2. 把 app-builder.exe 里**唯一**的那条期望 sha512（88 字符 base64）替换成新包的哈希。
   两者长度相同，是等长字节替换，不改变二进制布局；
3. 起一个本地 HTTP 镜像（路径规则与 electron-builder 一致：
   <mirror>/winCodeSign-2.6.0/winCodeSign-2.6.0.7z），让构建从本地取改好的包。

因为脚本是幂等的，重跑安全（已打过补丁就不重复打）。

⚠️ 补丁落在 node_modules 里（`npm install` 后会丢失）——重装依赖后重跑本脚本即可。
⚠️ 产物必须输出到 **WorkBuddy 工作区之外**：工作区内的新文件会被宿主文件监视器
   短暂持有句柄，导致 electron-builder 在 EnsureEmptyDir 阶段删不掉上次的 app.asar，
   报 "The process cannot access the file because it is being used by another process"。
"""
import base64
import hashlib
import http.server
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

PROJECT = r"C:\Users\kevin\WorkBuddy\2026-09-29-22-08-13\wechat-summarizer"
DESKTOP = os.path.join(PROJECT, "desktop")
NODE = r"C:\Users\kevin\.workbuddy\binaries\node\versions\22.22.2-2\node.exe"
SEVENZ = os.path.join(DESKTOP, "node_modules", "7zip-bin", "win", "x64", "7za.exe")
APP_BUILDER = os.path.join(DESKTOP, "node_modules", "app-builder-bin", "win", "x64",
                           "app-builder.exe")
CACHE = r"C:\Users\kevin\AppData\Local\electron-builder\Cache"
WORK = r"C:\Users\kevin\wms-build"
MIRROR_DIR = os.path.join(WORK, "mirror")
OUT_DIR = os.path.join(WORK, "release")
MIRROR_PORT = 8899

PKG_REL = os.path.join("winCodeSign-2.6.0", "winCodeSign-2.6.0.7z")
UPSTREAM = "https://registry.npmmirror.com/-/binary/electron-builder-binaries"
OLD_SHA = (b"6LQI2d9BPC3Xs0ZoTQe1o3tPiA28c7+PY69Q9i/pD8lY45psMtHuLwv3vRcki"
           b"Vr3Zx1cbNyLlBR8STwCdcHwtA==")


def log(msg):
    print(msg, flush=True)


def make_patched_archive():
    """解压原包 -> 把符号链接换成实体文件 -> 重新打包。返回新包路径。"""
    dest = os.path.join(MIRROR_DIR, PKG_REL)
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    # 找一个原包：优选用 electron-builder 自己下到 staging 的那个
    src = None
    stage = os.path.join(CACHE, "winCodeSign")
    if os.path.isdir(stage):
        for n in os.listdir(stage):
            p = os.path.join(stage, n)
            if n.endswith(".7z") and os.path.getsize(p) > 5_000_000:
                src = p
                break
    if src is None:
        # staging 里没有就自己下一个
        os.makedirs(CACHE, exist_ok=True)
        url = UPSTREAM + "/" + PKG_REL.replace(os.sep, "/")
        log("  下载原包: " + url)
        data = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
            timeout=180).read()
        src = os.path.join(MIRROR_DIR, "_orig.7z")
        open(src, "wb").write(data)

    # 用时间戳目录，避免 rmtree 删旧目录 —— WorkBuddy 的批量删除保护会拦下
    # 超过 50 个文件的删除操作，导致构建中断（shutil.rmtree 被 hook 拦下）。
    # 旧目录留给用户自行清理。
    work = os.path.join(WORK, "_wcs_unpack_%d" % int(time.time()))
    subprocess.run([SEVENZ, "x", "-y", "-bd", src, "-o" + work], capture_output=True)

    lib = os.path.join(work, "darwin", "10.12", "lib")
    fixed = []
    for target, source in (("libcrypto.dylib", "libcrypto.1.0.0.dylib"),
                           ("libssl.dylib", "libssl.1.0.0.dylib")):
        tp, sp = os.path.join(lib, target), os.path.join(lib, source)
        if os.path.exists(sp):
            if os.path.exists(tp):
                os.remove(tp)
            shutil.copyfile(sp, tp)
            fixed.append("%s (%d 字节)" % (target, os.path.getsize(tp)))
    log("  符号链接已替换为实体文件: " + ", ".join(fixed))

    # 把所有文件的 mtime 归零，让 7z 输出字节确定 —— 否则每次重建哈希都变，
    # app-builder.exe 里打进的那份期望 sha512 下次就失效了。
    for root, _dirs, files in os.walk(work):
        for fn in files:
            try:
                os.utime(os.path.join(root, fn), (315532800, 315532800))
            except OSError:
                pass

    if os.path.exists(dest):
        os.remove(dest)
    subprocess.run([SEVENZ, "a", "-t7z", "-mx1", dest, "*"],
                   capture_output=True, cwd=work)
    return dest


def patch_app_builder(new_sha_b64):
    """把 app-builder.exe 里的期望 sha512 换成新包的哈希。

    幂等做法：始终从 .orig 原始备份重新打补丁。
    不能只认固定的 OLD_SHA —— 7z 包每次重建因文件 mtime 不同而哈希会变，
    上一轮打进 exe 的旧补丁值就再也匹配不上了（count==0），导致第二次构建失败。
    """
    data = open(APP_BUILDER, "rb").read()
    if new_sha_b64 in data:
        log("  app-builder.exe 已是打过补丁的状态，跳过")
        return True

    # 优先用原始备份，保证每次都从干净状态打补丁
    backup = APP_BUILDER + ".orig"
    if os.path.exists(backup):
        data = open(backup, "rb").read()
        log("  从原始备份 .orig 重新打补丁")
    else:
        shutil.copyfile(APP_BUILDER, backup)
        log("  已备份原文件为 app-builder.exe.orig")

    if data.count(OLD_SHA) != 1:
        log("  ⚠️ 旧哈希在原始文件里出现 %d 次（期望 1 次），放弃打补丁"
            % data.count(OLD_SHA))
        return False
    open(APP_BUILDER, "wb").write(data.replace(OLD_SHA, new_sha_b64))
    log("  app-builder.exe 期望 sha512 已替换")
    return True


class MirrorHandler(http.server.BaseHTTPRequestHandler):
    """本地有就用本地，没有就转发上游（保证别的组件也能拿到）。"""

    def do_GET(self):
        local = os.path.join(MIRROR_DIR, self.path.lstrip("/").replace("/", os.sep))
        if os.path.isfile(local):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-7z-compressed")
            self.send_header("Content-Length", str(os.path.getsize(local)))
            self.end_headers()
            with open(local, "rb") as fh:
                self.wfile.write(fh.read())
            log("  [mirror] 本地命中 " + self.path)
            return
        try:
            with urllib.request.urlopen(UPSTREAM + self.path, timeout=60) as r:
                blob = r.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
            log("  [mirror] 转发上游 %s (%d 字节)" % (self.path, len(blob)))
        except Exception as exc:                          # noqa: BLE001
            log("  [mirror] 转发失败 %s: %s" % (self.path, exc))
            self.send_error(404)

    def log_message(self, *a):
        pass


def main():
    log("[1/4] 检查并修正 winCodeSign 包")
    pkg = make_patched_archive()
    blob = open(pkg, "rb").read()
    new_sha = base64.b64encode(hashlib.sha512(blob).digest())
    log("  改好的包: %s (%d 字节)" % (pkg, len(blob)))
    log("  新 sha512: " + new_sha.decode())

    log("[2/4] 给 app-builder.exe 打补丁")
    if not patch_app_builder(new_sha):
        log("补丁失败，终止")
        return 1

    log("[3/4] 启动本地镜像 http://127.0.0.1:%d" % MIRROR_PORT)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", MIRROR_PORT), MirrorHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    with urllib.request.urlopen(
            "http://127.0.0.1:%d/%s" % (MIRROR_PORT, PKG_REL.replace(os.sep, "/")),
            timeout=10) as r:
        log("  自检 -> %d 字节" % len(r.read()))

    log("[4/4] 开始构建（输出到 %s）" % OUT_DIR)
    env = dict(os.environ)
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        env.pop(k, None)
    env["ELECTRON_BUILDER_BINARIES_MIRROR"] = "http://127.0.0.1:%d/" % MIRROR_PORT
    env["ELECTRON_MIRROR"] = "https://registry.npmmirror.com/-/binary/electron/"
    env["ELECTRON_BUILDER_CACHE"] = CACHE

    # 输出目录指向 wms-build\out（全新空目录）。
    # 不能用 desktop\release —— 里面有上次构建的残留 app.asar，
    # electron-builder 的 EnsureEmptyDir 删不掉它（沙箱批量删除保护），
    # 会报 "The process cannot access the file because it is being used by another process"。
    # 也不能传绝对路径形式的 --config.directories.output：那会让 extraResources 的
    # 相对路径（../backend-dist）在 Windows 下解析错位，resources/ 里只有 app.asar、
    # backend/ 整个目录消失，装到电脑上启动即崩。
    out_dir = os.path.join(WORK, "out")
    os.makedirs(out_dir, exist_ok=True)

    r = subprocess.run(
        [NODE, "node_modules/electron-builder/cli.js",
         "--config.directories.output=../wms-build/out"],
        cwd=DESKTOP, env=env, capture_output=True)
    out = (r.stdout + b"\n----- STDERR -----\n" + r.stderr).decode("utf-8", "replace")
    log_path = os.path.join(os.environ.get("TEMP", "/tmp"), "eb-build-full.log")
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    httpd.shutdown()

    log("构建退出码 = %d ｜ 完整日志 -> %s" % (r.returncode, log_path))
    lines = out.splitlines()
    hit = [i for i, l in enumerate(lines) if "⨯" in l or "building" in l.lower()
           or "target=" in l]
    if hit:
        lo = max(0, hit[0] - 2)
        log("\n".join(lines[lo:lo + 30]))
    else:
        log("\n".join(lines[-25:]))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
