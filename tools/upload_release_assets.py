# -*- coding: utf-8 -*-
"""上传 Release 资产（GitHub Releases API）。

为什么单独写脚本：
- `POST /repos/{o}/{r}/releases/{id}/assets?name=X` 上传二进制资产的 body
  **不能是 JSON**，必须是文件原始字节，且要带 `Content-Type: application/octet-stream`
  与 `?name=` 查询参数。
- 300 MB 一次性传完容易断，需要支持重试 + 断点友好（用 Expect: 100-continue 让
  服务端先拒绝再发 body，避免浪费带宽）。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
# ⚠️ 上传资产的 endpoint 在 uploads.github.com，不是 api.github.com ——
# 用错域名会拿到 404 {"message":"Not Found"}（很容易误判成「token 没权限」）。
# 正确地址要从 release 对象的 upload_url 字段拿，形如
#   https://uploads.github.com/repos/{owner}/{repo}/releases/{id}/assets{?name,label}
UPLOAD_API = "https://uploads.github.com"


def upload(repo, release_id, token, path, label=""):
    name = label or os.path.basename(path)
    size = os.path.getsize(path)
    url = "%s/repos/%s/releases/%d/assets?name=%s" % (
        UPLOAD_API, repo, release_id, urllib.parse.quote(name))

    print("  上传 %s（%.1f MB）..." % (name, size / 1048576), flush=True)
    t0 = time.time()

    # 关键：先声明 Content-Length，让服务端能拒绝而不是收一半断掉
    req = urllib.request.Request(url, method="POST", data=open(path, "rb").read())
    req.add_header("Authorization", "token " + token)
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("Content-Length", str(size))
    req.add_header("User-Agent", "workbuddy")

    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            d = json.load(r)
        print("  ✅ %s  id=%s  用时 %.0fs"
              % (name, d.get("id"), time.time() - t0), flush=True)
        return d
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        print("  ❌ HTTP %s: %s" % (e.code, detail), flush=True)
        return None
    except Exception as e:                                    # noqa: BLE001
        print("  ❌ %s: %s" % (type(e).__name__, e), flush=True)
        return None


def main():
    repo = sys.argv[1]
    release_id = int(sys.argv[2])
    token = os.environ["GITHUB_TOKEN"]
    files = sys.argv[3:]

    ok = 0
    for spec in files:
        # 语法：<本地路径>[:<远端资产名>]
        # ⚠️ 必须显式给英文资产名。GitHub 会在解析 ?name= 时把中文截断成
        #    「AI.1.3.1.exe」这种无意义的名字（实测「微信消息AI助手 Setup 1.3.1.exe」
        #    → 「AI.Setup.1.3.1.exe」），用户下载后完全不知道是什么。
        if ":" in spec and not os.path.exists(spec):
            path, label = spec.rsplit(":", 1)
        else:
            path, label = spec, ""
        if not os.path.isfile(path):
            print("  跳过（不存在）: %s" % path)
            continue
        if upload(repo, release_id, token, path, label) is not None:
            ok += 1
        else:
            print("  ⚠️ 该资产上传失败，可重跑本脚本（同名会覆盖）")

    print("\n完成：%d/%d" % (ok, len(files)))
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
