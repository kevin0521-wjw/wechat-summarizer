# -*- coding: utf-8 -*-
"""
消息源抽象层
=============
把「微信消息从哪来」与「拿到消息后干什么」解耦，方便换底层框架。

统一回调签名：on_message(msg: dict) -> None
msg 结构（两种消息源都归一化成这个 dict）：
{
  "msg_id":   str,   # 消息唯一 id
  "sender":   str,   # 发送者 wxid
  "room_id":  str,   # 群 id（私聊为空字符串）
  "is_group": bool,  # 是否群聊
  "type":     int,   # 1=文本 3=图片 34=语音 43=视频 49=文件/链接/小程序
  "content":  str,   # 文本内容 / 文件路径
  "xml":      str,   # 原始 XML（链接/视频号/小程序的信息都藏在这里）
  "ts":       int,   # 时间戳（秒）
  "is_self":  bool,  # 是否自己发的
}
"""
import time
from abc import ABC, abstractmethod
from typing import Callable, Optional


class MessageSource(ABC):
    """消息源接口"""

    @abstractmethod
    def start(self, on_message: Callable[[dict], None]) -> None:
        """启动监听，收到消息回调 on_message"""

    def send_text(self, to: str, text: str, at: Optional[list] = None) -> bool:
        """主动发文本消息（回复/推送用）。子类按需覆写。"""
        raise NotImplementedError


class WeChatFerrySource(MessageSource):
    """
    基于 WeChatFerry（wcferry）的消息源 —— 推荐主力方案。
    - 注入微信 PC 进程，实时回调，功能最全（可下载视频/文件、查数据库）
    - 前提：电脑开着微信并登录；微信版本需与 wcferry 匹配（微信 3.9/4.x 有对应版本）
    - GitHub: https://github.com/lich0821/WeChatFerry
    """
    # 消息类型 → 说明（wcferry 的 msg.type）
    TYPE_TEXT, TYPE_IMAGE = 1, 3
    TYPE_VOICE, TYPE_VIDEO = 34, 43
    TYPE_ATTACH = 49  # 文件 / 链接 / 小程序 / 视频号（信息在 xml 里）

    def __init__(self):
        self._wcf = None
        self._cb = None

    def start(self, on_message: Callable[[dict], None]) -> None:
        self._cb = on_message
        from wcferry import Wcf  # 延迟导入，未装 wcferry 不影响其它模块
        self._wcf = Wcf()
        self._wcf.enable_receiving_msg()   # 开启接收消息
        print("[wcferry] 已连接微信，开始监听消息……")
        self._wcf.on_message(self._dispatch)
        # 阻塞主线程，保持回调活跃（用 keep_running 或循环）
        from wcferry import Wcf
        import time as _t
        while True:
            _t.sleep(1)

    def _dispatch(self, wcf, raw) -> None:
        """把 wcferry 的 WxMsg 对象归一化成统一 dict 后回调"""
        if self._cb is None:
            return
        msg = {
            "msg_id": getattr(raw, "id", ""),
            "sender": getattr(raw, "sender", ""),
            "room_id": getattr(raw, "roomid", ""),
            "is_group": bool(getattr(raw, "roomid", "")),
            "type": getattr(raw, "type", 0),
            "content": getattr(raw, "content", ""),
            "xml": getattr(raw, "xml", ""),
            "ts": getattr(raw, "ts", int(time.time())),
            "is_self": bool(getattr(raw, "is_self", False)),
        }
        try:
            self._cb(msg)
        except Exception as e:  # 回调异常不能打断监听
            print(f"[wcferry] 处理消息异常: {e}")

    def send_text(self, to: str, text: str, at: Optional[list] = None) -> bool:
        if self._wcf is None:
            return False
        return self._wcf.send_text(text, to, at if at else [])


class WeFlowSource(MessageSource):
    """
    基于 WeFlow 本地 HTTP API 的消息源 —— 你（Kevin）已经在用的方案。
    - WeFlow 本身是 Electron 工具，本地运行，暴露 HTTP API（默认 127.0.0.1:5031）
    - 注意：WeFlow 2026-07 已被 DMCA 下架，无官方维护，仅作已有环境复用
    - GitHub: https://github.com/hicccc77/WeFlow

    TODO（接入前需确认）：
      1. 查 WeFlow 的「完整接口文档」确认拉取新消息的端点与字段
         （README 提到「支持原始 JSON 或 ChatLab 标准格式」「查询消息数据」接口）
      2. 当前用「轮询」方式：定时 GET 最新消息，与上次游标比对去重
      3. 更省事：直接复用你已有的 wechat-weflow-bridge-ob11（OneBot 11 协议），
         从 OneBot 11 的 websocket 事件里取消息，AstrBot 那套已经通了
    """
    def __init__(self, base: str = "http://127.0.0.1:5031"):
        self._base = base
        self._cb = None
        self._last_ts = 0  # 上次拉到的最新消息时间戳，做增量去重

    def start(self, on_message: Callable[[dict], None]) -> None:
        self._cb = on_message
        import requests
        print(f"[weflow] 开始轮询 {self._base} ……")
        while True:
            try:
                # TODO: 换成 WeFlow 实际的消息查询端点与参数
                r = requests.get(f"{self._base}/api/messages", timeout=5)
                if r.status_code == 200:
                    for item in r.json().get("data", []):
                        if item.get("ts", 0) > self._last_ts:
                            self._last_ts = item["ts"]
                            self._cb(self._normalize(item))
            except Exception as e:
                print(f"[weflow] 轮询异常: {e}")
            time.sleep(2)  # 轮询间隔 2 秒

    def _normalize(self, item: dict) -> dict:
        """把 WeFlow 的消息 JSON 归一化成统一结构（字段名需按实际接口调整）"""
        return {
            "msg_id": item.get("id", ""),
            "sender": item.get("sender", ""),
            "room_id": item.get("room_id", ""),
            "is_group": bool(item.get("room_id", "")),
            "type": item.get("type", 0),
            "content": item.get("content", ""),
            "xml": item.get("xml", ""),
            "ts": item.get("ts", 0),
            "is_self": item.get("is_self", False),
        }
