# -*- coding: utf-8 -*-
"""
通过 GitHub REST API 推送一批文件（绕过 github.com:443 被阻断的问题）
=====================================================================
当 `git push` 因 github.com 域名不通而失败、但 api.github.com 可用时，
用 Git Data API 直接构造一次提交，不需要 git 协议：

  1. GET   /repos/:o/:r/git/ref/heads/:branch   → 拿当前 commit SHA + tree
  2. POST  /repos/:o/:r/git/blobs               → 为每个改动文件建 blob
  3. POST  /repos/:o/:r/git/trees               → 建新 tree（带 base_tree）
  4. POST  /repos/:o/:r/git/commits             → 建 commit
  5. PATCH /repos/:o/:r/git/refs/heads/:branch  → 移动分支指针

用法：
  python tools/github_api_push.py --token <TOKEN> --repo owner/name \
      --branch main --message "提交信息" --paths core/selection.py web/app.py
  # 不传 --paths 则推送当前工作区所有已修改/新增的文件

⚠️ 需要能访问 api.github.com；若直连不通，脚本会尝试本地代理 127.0.0.1:7897。
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

API = "https://api.github.com"


def _req(method: str, url: str, token: str, body=None, proxy: str = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "wechat-summarizer-push")
    if data:
        req.add_header("Content-Type", "application/json")

    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=45) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise RuntimeError(f"HTTP {e.code} {method} {url}\n{detail}")


def detect_proxy() -> str:
    """api.github.com 直连不通时，退到本机 Clash"""
    import socket
    for port in (7897, 7890):
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    return None


def changed_files(root: str) -> list:
    """git status --porcelain 里的改动路径（排除删除）"""
    out = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                         capture_output=True, text=True).stdout
    paths = []
    for line in out.splitlines():
        if not line.strip():
            continue
        status, _, p = line[:2], line[2:3], line[3:].strip()
        if status.strip() == "D":
            continue          # 本脚本不处理删除（需要单独传 sha=null）
        if p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        paths.append(p.replace("\\", "/"))
    return paths


def push(token: str, repo: str, branch: str, message: str, paths: list,
         root: str = ".", proxy: str = None):
    # 1) 当前分支状态
    ref = _req("GET", f"{API}/repos/{repo}/git/ref/heads/{branch}", token, proxy=proxy)
    base_sha = ref["object"]["sha"]
    base_commit = _req("GET", f"{API}/repos/{repo}/git/commits/{base_sha}", token, proxy=proxy)
    base_tree = base_commit["tree"]["sha"]
    print(f"[1/5] 当前 {branch} = {base_sha[:8]}")

    # 2) 上传每个文件为 blob
    entries = []
    for rel in paths:
        full = os.path.join(root, rel)
        if not os.path.exists(full):
            print(f"      跳过（不存在）: {rel}")
            continue
        with open(full, "rb") as f:
            raw = f.read()
        sha = _req("POST", f"{API}/repos/{repo}/git/blobs", token,
                   {"content": base64.b64encode(raw).decode(), "encoding": "base64"},
                   proxy=proxy)["sha"]
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": sha})
        print(f"      已上传 blob: {rel} ({len(raw)} 字节)")

    if not entries:
        print("没有要推送的文件")
        return None

    # 3) 新 tree
    tree = _req("POST", f"{API}/repos/{repo}/git/trees", token,
                {"base_tree": base_tree, "tree": entries}, proxy=proxy)
    print(f"[2/5] 新 tree = {tree['sha'][:8]}")

    # 4) 新 commit
    commit = _req("POST", f"{API}/repos/{repo}/git/commits", token,
                  {"message": message, "tree": tree["sha"], "parents": [base_sha]},
                  proxy=proxy)
    print(f"[3/5] 新 commit = {commit['sha'][:8]}")

    # 5) 移动分支（force=false，防并发覆盖）
    _req("PATCH", f"{API}/repos/{repo}/git/refs/heads/{branch}", token,
         {"sha": commit["sha"], "force": False}, proxy=proxy)
    print(f"[4/5] {branch} 已更新 → {commit['sha'][:8]}")
    return commit["sha"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--repo", default="kevin0521-wjw/wechat-summarizer")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", required=True)
    ap.add_argument("--paths", nargs="*", default=None)
    ap.add_argument("--root", default=".")
    ap.add_argument("--proxy", default=None, help="如 http://127.0.0.1:7897；不传则自动探测")
    a = ap.parse_args()

    proxy = a.proxy
    if proxy is None:
        proxy = detect_proxy()
    print(f"[proxy] 使用: {proxy or '直连'}")

    paths = a.paths if a.paths else changed_files(a.root)
    if not paths:
        print("工作区没有改动")
        return
    print(f"[0/5] 待推送 {len(paths)} 个文件")

    sha = push(a.token, a.repo, a.branch, a.message, paths, a.root, proxy)
    if sha:
        # 同步本地 git 记录，避免下次 status 重复显示（用 fetch 不可用时仅重置指针不可行，
        # 这里只打印提示）
        print(f"[5/5] 完成。远端 {a.branch} = {sha}")
        print(f"      https://github.com/{a.repo}/commit/{sha}")


if __name__ == "__main__":
    main()
