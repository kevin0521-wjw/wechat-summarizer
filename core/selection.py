# -*- coding: utf-8 -*-
"""
选中即分析（划词 → DeepSeek → 悬浮输出）
========================================
用户在任意窗口里**选中一段内容**（聊天记录 / 长段文字 / 表情包文件 / 视频链接），
按下全局热键（默认 Ctrl+Alt+D）后：

  1. 用剪贴板方式取到选中文本（先保存旧剪贴板 → Ctrl+C → 读 → 还原）
  2. 判断内容类型：
       视频/链接  → 走「实时解析」（字幕+评论+tag）再让 DeepSeek 总结
       表情包图片 → 把图片交给**视觉模型**（若配置了 vision_model）或提示不支持
       长段文字   → 直接丢 DeepSeek，按「精炼摘要+要点+我的待办」输出
       聊天记录   → 额外做「谁在说什么 / 有没有@我 / 需要我回什么」分析
  3. 结果通过回调返回（桌面端拿去显示在**悬浮窗**里）

设计原则：
- 只读剪贴板、不改用户原文（用完还原）
- 不依赖 GUI 库；剪贴板/热键由具体外壳（桌面端）负责，本模块只做「取词 → 分析」
"""
import os
import re
import time
import base64
import subprocess
import tempfile

from core.dispatcher import extract_links, is_video_link

# 微信聊天记录典型特征：昵称后跟冒号，或带时间戳
CHAT_LINE_RE = re.compile(r"^\s*(?:\[?\d{1,2}:\d{2}\]?\s*)?[\w\u4e00-\u9fa5\-.·]{1,20}[:：]\s*\S", re.M)
TIME_HEAD_RE = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?\s*\d{1,2}:\d{2}")

IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff")
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".webm")


# ---------------------------------------------------------------------------
# 内容分类
# ---------------------------------------------------------------------------

def classify(text: str, is_image: bool = False, file_path: str = "") -> str:
    """
    返回内容类型：video | link | chat | emoji | image | text
    """
    if is_image or (file_path and file_path.lower().endswith(IMG_EXT)):
        return "emoji" if _looks_like_sticker(file_path) else "image"

    t = (text or "").strip()
    if not t and file_path:
        low = file_path.lower()
        if low.endswith(VIDEO_EXT):
            return "video"
        return "text"
    if not t:
        return "text"

    links = extract_links(t)
    if links:
        # 纯链接（或很短）→ 链接类
        return "link"

    if is_chat_log(t):
        return "chat"
    return "text"


def is_chat_log(text: str) -> bool:
    """粗判是否是一段聊天记录：多行「昵称: 内容」或带时间戳"""
    if not text or len(text) < 8:
        return False
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return False
    hit = sum(1 for l in lines if CHAT_LINE_RE.match(l))
    if hit >= 2 and hit / len(lines) >= 0.5:
        return True
    return bool(TIME_HEAD_RE.search(text))


def _looks_like_sticker(path: str) -> bool:
    """表情包多为小尺寸图片（<200KB）或文件名含 emoji/表情"""
    if not path:
        return False
    name = os.path.basename(path).lower()
    if any(k in name for k in ("emoji", "sticker", "表情", "bq")):
        return True
    try:
        return os.path.getsize(path) < 200 * 1024
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 剪贴板取词（Windows，纯 ctypes，不装额外库）
# ---------------------------------------------------------------------------

def grab_selected_text(timeout: float = 0.6) -> str:
    """
    用「Ctrl+C + 剪贴板」拿当前选中文本（Windows）。
    返回文本；失败返回 ""。
    注意：会短暂占用剪贴板，用完尽量还原（见 grab_with_restore）。
    """
    old = read_clipboard_text()
    if not _send_ctrl_c():
        return old or ""
    time.sleep(0.12)          # 等系统把 Ctrl+C 结果写进剪贴板
    new = read_clipboard_text()
    # 没变化说明没选中东西，保留旧值
    return new if new else (old or "")


def read_clipboard_text() -> str:
    """读剪贴板文本（Windows，ctypes 直连 user32）"""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        if not u32.OpenClipboard(None):
            return ""
        try:
            if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return ""
            h = u32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return ""
            p = k32.GlobalLock(h)
            if not p:
                return ""
            try:
                return ctypes.wstring_at(p)
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()
    except Exception:
        return ""


def write_clipboard_text(text: str) -> bool:
    """写剪贴板文本（Windows）"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        data = (text or "").encode("utf-16-le") + b"\x00\x00"
        if not u32.OpenClipboard(None):
            return False
        try:
            u32.EmptyClipboard()
            h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            p = k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            u32.SetClipboardData(CF_UNICODETEXT, h)
            return True
        finally:
            u32.CloseClipboard()
    except Exception:
        return False


def grab_with_restore() -> str:
    """取选中文本，并把用户原剪贴板还原回去（不打扰用户）"""
    old = read_clipboard_text()
    text = grab_selected_text()
    if old and old != text:
        write_clipboard_text(old)
    return text or ""


def read_clipboard_image_b64() -> str:
    """读剪贴板里的图片 → base64（用于表情包/图片分析）。失败返回 """""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        CF_DIB = 8
        u32.OpenClipboard(None)
        h = u32.GetClipboardData(CF_DIB)
        u32.CloseClipboard()
        if not h:
            return ""
        # DIB → PNG 需要拼 BMP 头，交给 Pillow（若可用）
        from PIL import Image
        import io
        k32 = ctypes.windll.kernel32
        p = k32.GlobalLock(h)
        try:
            size = k32.GlobalSize(h)
            raw = ctypes.string_at(p, size)
        finally:
            k32.GlobalUnlock(h)
        # 14 字节 BMP 文件头 + DIB
        bmp = b"BM" + (len(raw) + 14).to_bytes(4, "little") + b"\x00\x00\x00\x00" + (54).to_bytes(4, "little") + raw
        im = Image.open(io.BytesIO(bmp))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def _send_ctrl_c() -> bool:
    """模拟 Ctrl+C（keybd_event，Win32 通用）"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        u32 = ctypes.windll.user32
        VK_CONTROL, VK_C = 0x11, 0x43
        KEYEVENTF_KEYUP = 0x0002
        u32.keybd_event(VK_CONTROL, 0, 0, 0)
        u32.keybd_event(VK_C, 0, 0, 0)
        u32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        u32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 主入口：选中的东西 → 分析结果
# ---------------------------------------------------------------------------

class SelectionAnalyzer:
    """
    把「选中内容」交给 DeepSeek 得出结果。
    返回 {"kind": ..., "title": ..., "text": ..., "source": ...}
    """

    def __init__(self, cfg: dict, summarizer=None):
        self.cfg = cfg
        self.summarizer = summarizer
        self.platforms = cfg.get("video", {}).get("platforms", [])

    def analyze_text(self, text: str, hint: str = "") -> dict:
        text = (text or "").strip()
        if not text:
            return {"kind": "empty", "title": "没有取到内容",
                    "text": "选中一段文字/聊天记录后再按热键（默认 Ctrl+Alt+D）。"}

        kind = classify(text)
        if hint:
            kind = hint  # 允许外部强制指定（如网页版传 kind）

        # ---- 视频/链接：先解析再总结（秒级） ----
        if kind in ("link", "video"):
            links = extract_links(text)
            vlink = next((u for u in links if is_video_link(u, self.platforms)), None)
            if vlink:
                return self._analyze_video(vlink, text)
            return {"kind": "link", "title": "链接解析",
                    "text": self._analyze_plain_link(text)}

        # ---- 表情包 / 图片 ----
        if kind in ("emoji", "image"):
            return self._analyze_image(text)

        # ---- 聊天记录 ----
        if kind == "chat":
            out = self.summarizer.chat_log_analysis(text) if self.summarizer else "[未配置 AI]"
            return {"kind": "chat", "title": "聊天记录分析", "text": out}

        # ---- 普通长文字 ----
        out = self.summarizer.analyze_text(text) if self.summarizer else "[未配置 AI]"
        return {"kind": "text", "title": "内容分析", "text": out}

    def _analyze_video(self, url: str, origin_text: str) -> dict:
        title = url[:40]
        if not self.summarizer:
            return {"kind": "video", "title": f"视频链接 · {title}",
                    "text": "[未配置 AI key，跳过总结]", "url": url}
        from core.video_parser import collect_video, try_pipeline
        summary = None
        if self.cfg.get("video", {}).get("use_pipeline"):
            summary = try_pipeline(url)
        if not summary:
            try:
                v = collect_video(url)
            except Exception as e:
                return {"kind": "video", "title": f"视频解析失败 · {title}",
                        "text": f"解析失败（可能需要 cookies 或网络不通）：{e}", "url": url}
            summary = self.summarizer.summarize_video(
                v.get("title", ""), v.get("subtitle") or "", v.get("tags"), v.get("comments"))
            title = v.get("title") or title
        return {"kind": "video", "title": f"视频解析 · {title}", "text": summary, "url": url}

    def _analyze_plain_link(self, text: str) -> str:
        """非视频链接：让 AI 就链接上下文做判断（不抓网页，避免慢）"""
        if not self.summarizer:
            return "[未配置 AI]"
        return self.summarizer.analyze_text(
            f"以下内容包含链接，请说明这些链接可能指向什么、是否值得点开、"
            f"以及有没有风险（钓鱼/广告）：\n\n{text}"
        )

    def _analyze_image(self, text: str) -> dict:
        """表情包/图片：有视觉模型则识别，否则给文字提示"""
        vision = self.cfg.get("ai", {}).get("vision_model") or ""
        img = read_clipboard_image_b64()
        if img and vision and self.summarizer:
            # 走 OpenAI 兼容的多模态消息
            prompt = (
                "请识别这张表情包/图片：说明画面内容、传达的情绪、适合什么场合回复，"
                "并给 2 条可直接发送的回复。"
            )
            out = self.summarizer.describe_image(img, prompt)
            return {"kind": "emoji", "title": "表情包解析", "text": out}
        return {"kind": "emoji", "title": "表情包解析",
                "text": "（未配置视觉模型 vision_model，无法识别图片内容）\n"
                        "可在 config.yaml 的 ai.vision_model 填入支持图片的模型（如 gpt-4o-mini / qwen-vl-max）。"}


# ---------------------------------------------------------------------------
# 便捷函数（供引擎/CLI 调用）
# ---------------------------------------------------------------------------

def analyze_selection(cfg: dict, summarizer, text: str = None, hint: str = "") -> dict:
    """取选中内容（或传入 text）→ 分析结果"""
    if text is None:
        text = grab_with_restore()
    return SelectionAnalyzer(cfg, summarizer).analyze_text(text, hint)
