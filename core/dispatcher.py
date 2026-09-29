# -*- coding: utf-8 -*-
"""
消息路由 / 分类
================
决定「这条消息该走哪条处理路径」：

  ┌─ 视频/链接（命中视频平台）→ 实时解析（下载字幕 → AI 总结）→ 立即推送
  ├─ 文件（视频/文档）        → 记录，可触发下载+总结
  ├─ 免打扰群 / 折叠群        → 只落库，等「每日汇总」统一处理
  ├─ 关注私聊                 → 实时记录，按需即时回复建议
  └─ 其它                    → 仅落库（供统计/周报）
"""
import re
from typing import Optional

# 通用链接正则
URL_RE = re.compile(r"https?://[^\s，。！？、\"'<>（）()]+")


def extract_links(text: str) -> list:
    """从文本里抽所有 http(s) 链接"""
    return URL_RE.findall(text or "")


def is_video_link(url: str, platforms: list) -> bool:
    """判断链接是否命中视频平台白名单"""
    low = url.lower()
    return any(p in low for p in platforms)


class Dispatcher:
    """把消息分类，返回一个『动作』标记 + 元信息"""

    ACTION_VIDEO = "video"        # 实时解析视频/链接
    ACTION_STORE = "store"        # 只落库
    ACTION_DAILY = "daily"        # 进每日汇总池

    def __init__(self, cfg: dict):
        self.platforms = cfg["video"]["platforms"]
        self.muted_rooms = set(cfg["focus"]["muted_rooms"])
        self.focus_contacts = set(cfg["focus"]["contacts"])

    def route(self, msg: dict) -> dict:
        """
        返回 {"action": str, "links": [...], "is_muted": bool}
        """
        content = msg.get("content", "")
        xml = msg.get("xml", "")
        is_group = msg.get("is_group", False)
        room_id = msg.get("room_id", "")
        sender = msg.get("sender", "")
        msg_type = msg.get("type", 0)

        # 1) 提取所有链接
        links = extract_links(content) + extract_links(xml)

        # 2) 是否免打扰群 / 折叠群
        is_muted = room_id in self.muted_rooms or \
            (is_group and (msg.get("room_name", "") in self.muted_rooms))

        # 3) 视频/链接 → 实时解析（除非是免打扰群，此时并入每日汇总）
        if links and any(is_video_link(u, self.platforms) for u in links):
            if is_muted:
                return {"action": self.ACTION_DAILY, "links": links, "is_muted": True}
            return {"action": self.ACTION_VIDEO, "links": links, "is_muted": False}

        # 4) 免打扰群消息 → 每日汇总池
        if is_muted:
            return {"action": self.ACTION_DAILY, "links": links, "is_muted": True}

        # 5) 文件/视频消息（type=43 视频 / 49 文件），先记录
        if msg_type in (43, 49):
            return {"action": self.ACTION_STORE, "links": links, "is_muted": False}

        # 6) 其余 → 落库（供统计/周报）
        return {"action": self.ACTION_STORE, "links": links, "is_muted": False}
