# -*- coding: utf-8 -*-
"""
视频/链接解析（已做实）
========================
好友发视频链接 → 自动「取元信息 → 下载字幕 → 抓评论 → 汇总素材」交给 AI 总结。

三层后端（自动降级，不依赖某一套能跑通）：
  1. video-link-pipeline（yunqiasen/xiexikang）：装了 `vlp` 命令就走它的一键「字幕+摘要」
  2. 本地 yt-dlp：默认主力，拿标题/tag/字幕，YouTube 还能 `--write-comments` 抓评论
  3. B站评论区：requests + wbi 签名直连 B 站 API（不依赖第三方库版本）

参考 GitHub：
  - video-link-pipeline（yunqiasen/video-link-pipeline）：平台降级链 + cookies 处理
  - AI-Video-Transcriber（wendy7756）：多平台转录思路
"""
import os
import re
import time
import json
import hashlib
import subprocess
import urllib.parse
from typing import Optional

try:
    import requests
except ImportError:
    requests = None


# ---------------------------------------------------------------------------
# 元信息
# ---------------------------------------------------------------------------

def fetch_video_meta(url: str) -> dict:
    """用 yt-dlp 取元信息（标题/标签/时长/BV号等），不下载视频本体"""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        "--skip-download",
        url,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        lines = [l for l in out.stdout.strip().splitlines() if l.strip().startswith("{")]
        if not lines:
            raise RuntimeError(out.stderr[:200] or "无输出")
        info = json.loads(lines[-1])  # 多 P 时取最后一个
        return {
            "title": info.get("title", ""),
            "tags": info.get("tags", []) or [],
            "duration": info.get("duration", 0),
            "extractor": info.get("extractor", ""),
            "video_id": info.get("id", ""),
            "_raw": info,
        }
    except Exception as e:
        print(f"[video] 元信息抓取失败: {e}")
        return {"title": "", "tags": [], "duration": 0, "extractor": "", "video_id": "", "_raw": {}}


# ---------------------------------------------------------------------------
# 字幕
# ---------------------------------------------------------------------------

def fetch_subtitle(url: str, video_id: Optional[str] = None, out_dir: str = "output/subs") -> Optional[str]:
    """
    下载字幕（B站/YouTube 自动字幕优先，其次人工字幕），返回清洗后的纯文本。
    每个视频一个独立子目录，避免「读到上一次的字幕」。
    """
    sub_dir = os.path.join(out_dir, video_id or "unknown")
    os.makedirs(sub_dir, exist_ok=True)
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-auto-sub",                 # 自动字幕（YouTube）
        "--write-sub",                      # 人工字幕（B站）
        "--sub-lang", "zh-Hans,zh-CN,zh,en",
        "--sub-format", "srt,vtt,ass",      # 逗号分隔，逗号才是 yt-dlp 认可的格式
        "--convert-subs", "srt",
        "-o", os.path.join(sub_dir, "%(id)s.%(ext)s"),
        url,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    except Exception as e:
        print(f"[video] 字幕下载失败: {e}")
        return None

    # 只读本视频目录里的字幕文件
    subs = []
    for f in sorted(os.listdir(sub_dir)):
        if f.endswith((".srt", ".vtt", ".ass")):
            subs.append(_clean_sub(os.path.join(sub_dir, f)))
    if subs:
        return "\n\n".join(subs)
    return None


def _clean_sub(path: str) -> str:
    """字幕文件 → 纯文本（去时间轴、序号、样式标签）"""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    raw = re.sub(r"\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}", "", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = re.sub(r"^\d+$", "", raw, flags=re.M)
    raw = raw.replace("WEBVTT", "").replace("Kind: captions", "")
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    # 去重相邻重复行（VTT 常见）
    out = []
    for l in lines:
        if not out or out[-1] != l:
            out.append(l)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 评论区（尽力而为，失败静默降级）
# ---------------------------------------------------------------------------

def fetch_comments(url: str, meta: dict) -> Optional[str]:
    """抓取评论区热评文本，返回拼接好的字符串；失败返回 None"""
    extractor = (meta.get("extractor") or "").lower()
    if "youtube" in extractor or "youtu" in url.lower():
        return _fetch_youtube_comments(url)
    if "bilibili" in extractor or "bilibili" in url.lower() or "b23" in url.lower():
        bvid = meta.get("video_id") or _extract_bvid(url)
        if bvid:
            return _fetch_bilibili_comments(bvid)
    return None


def _fetch_youtube_comments(url: str) -> Optional[str]:
    """YouTube 评论：yt-dlp 原生支持 --write-comments"""
    out_dir = "output/comments"
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-comments",
        "--no-playlist",
        "--max-comments", "20",          # 只取前 20 条热评
        "--write-info-json",
        "-o", os.path.join(out_dir, "%(id)s.%(ext)s"),
        url,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as e:
        print(f"[video] YouTube 评论抓取失败: {e}")
        return None
    # 找 info.json，读 comments 字段
    for f in os.listdir(out_dir):
        if f.endswith(".info.json"):
            try:
                with open(os.path.join(out_dir, f), "r", encoding="utf-8") as fp:
                    info = json.load(fp)
                comments = info.get("comments", [])
                texts = [c.get("text", "") for c in comments if c.get("text")]
                if texts:
                    return "\n".join(f"• {t[:200]}" for t in texts[:20])
            except Exception:
                pass
    return None


# B站 wbi 签名（2023+ 强制，游客态可用）
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19,
    29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def _extract_bvid(url: str) -> Optional[str]:
    m = re.search(r"(BV[0-9A-Za-z]{10})", url)
    return m.group(1) if m else None


def _wbi_keys(session) -> tuple:
    r = session.get("https://api.bilibili.com/x/web-interface/nav", timeout=10)
    wbi = r.json()["data"]["wbi_img"]
    img_key = wbi["img_url"].rsplit("/", 1)[1].split(".")[0]
    sub_key = wbi["sub_url"].rsplit("/", 1)[1].split(".")[0]
    return img_key, sub_key


def _mixin_key(img_key: str, sub_key: str) -> str:
    s = img_key + sub_key
    return "".join(s[i] for i in _MIXIN_KEY_ENC_TAB)[:32]


def _wbi_sign(params: dict, mixin_key: str) -> str:
    p = dict(params)
    p["wts"] = int(time.time())
    p = dict(sorted(p.items()))
    query = urllib.parse.urlencode(p)
    # 过滤 B站不参与签名的字符
    query = query.replace("!", "").replace("'", "").replace("(", "").replace(")", "").replace("*", "")
    return hashlib.md5((query + mixin_key).encode()).hexdigest()


def _fetch_bilibili_comments(bvid: str) -> Optional[str]:
    """B站评论区：先拿 aid，再调评论接口拿热评（top20）"""
    if requests is None:
        return None
    try:
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/",
        })
        img_key, sub_key = _wbi_keys(s)
        mk = _mixin_key(img_key, sub_key)

        # 1) 拿 aid
        params = {"bvid": bvid}
        w_rid = _wbi_sign(params, mk)
        r = s.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={**params, "w_rid": w_rid},
            timeout=10,
        )
        aid = r.json()["data"]["aid"]

        # 2) 拿热评（sort=2 按热度）
        params = {"type": 1, "oid": aid, "sort": 2, "ps": 20, "pn": 1}
        w_rid = _wbi_sign(params, mk)
        r = s.get(
            "https://api.bilibili.com/x/v2/reply",
            params={**params, "w_rid": w_rid},
            timeout=10,
        )
        replies = r.json()["data"].get("replies", []) or []
        texts = []
        for c in replies:
            msg = c.get("content", {}).get("message", "")
            like = c.get("like", 0)
            if msg:
                texts.append(f"• {msg[:150]}" + (f"（赞{like}）" if like else ""))
        return "\n".join(texts[:20]) if texts else None
    except Exception as e:
        print(f"[video] B站评论抓取失败: {e}")
        return None


# ---------------------------------------------------------------------------
# 一站式素材收集
# ---------------------------------------------------------------------------

def collect_video(url: str) -> dict:
    """取齐「标题 / tag / 字幕 / 评论」，返回给 AI 总结的原始素材"""
    meta = fetch_video_meta(url)
    vid = meta.get("video_id")
    subs = fetch_subtitle(url, vid)
    comments = fetch_comments(url, meta)
    return {
        "title": meta.get("title", ""),
        "tags": meta.get("tags", []),
        "subtitle": subs,
        "comments": comments,
    }


def try_pipeline(url: str) -> Optional[str]:
    """
    可选后端：若装了 video-link-pipeline（`vlp` 命令），走它的一键「字幕+摘要」。
    返回摘要文本；没装 / 失败返回 None，由调用方降级到本地流程。
    """
    try:
        # 先探测命令是否存在
        if subprocess.run(["vlp", "--help"], capture_output=True).returncode != 0:
            return None
        out = subprocess.run(
            ["vlp", "run", url, "--do-summary"],
            capture_output=True, text=True, timeout=600,
        )
        # summary 通常落在 output/<id>/summary.md，这里简化：抓 stdout 尾部
        tail = out.stdout.strip()[-2000:]
        return tail if tail else None
    except Exception as e:
        print(f"[video] pipeline 后端不可用: {e}")
        return None
