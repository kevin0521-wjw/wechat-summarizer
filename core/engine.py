# -*- coding: utf-8 -*-
"""
核心引擎
========
把「消息监听 → 落库 → 路由 → 视频解析/回复建议」与「定时汇总」串成一个 Engine。
CLI（main.py）和 Web（web/app.py）都复用它，避免两套逻辑。

用法：
  # CLI（阻塞）
  Engine(cfg).start()

  # Web（后台监听，主线程留给 FastAPI）
  engine = Engine(cfg)
  engine.start_background()
"""
import os
import time
import threading

from db.store import Store
from core.dispatcher import Dispatcher, is_video_link
from core.summarizer import Summarizer
from core.video_parser import collect_video, try_pipeline
from core.pusher import Pusher
from core.scheduler import Scheduler
from core import history_backfill
from core.message_source import WeChatFerrySource, WeFlowSource

LAST_RUN_FILE = "data/last_run.txt"


class Engine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.store = Store(cfg["db"]["path"])
        self.dispatcher = Dispatcher(cfg)
        self.summarizer = Summarizer(cfg)
        self.pusher = Pusher(cfg)
        self.scheduler = Scheduler(cfg, self.store, self.summarizer, self.pusher)

    # ------------------------------------------------------------------
    # 核心消息处理
    # ------------------------------------------------------------------
    def on_message(self, msg: dict) -> None:
        """每条消息：落库 → 路由 → 实时动作（视频/@我/回复建议）"""
        self.store.add(msg)
        r = self.dispatcher.route(msg)
        action = r["action"]

        if action == Dispatcher.ACTION_VIDEO:
            # 视频解析耗时（下载字幕+AI），丢线程避免阻塞消息回调
            threading.Thread(target=self._handle_video, args=(r["links"],), daemon=True).start()

        # @我的 → 实时抽出（群聊 + 私聊都算；私聊本身就是找我的）
        if self._is_at_me(msg):
            threading.Thread(target=self._handle_at_me, args=(msg,), daemon=True).start()

        focus = set(self.cfg["focus"]["contacts"])
        if (not msg.get("is_group")) and (msg.get("sender") in focus):
            threading.Thread(target=self._suggest_reply, args=(msg,), daemon=True).start()

    def _is_at_me(self, msg: dict) -> bool:
        """判定是否有人 @我"""
        if msg.get("is_self"):
            return False
        if not self.cfg.get("focus", {}).get("notify_at_me", True):
            return False
        content = msg.get("content", "") or ""
        xml = msg.get("xml", "") or ""
        # 微信 @ 在文本里是 "@昵称"，在 xml 里是 <atuserlist>
        if "@" in content:
            return True
        if "atuserlist" in xml.lower():
            return True
        # 私聊（非群）默认算「找我」，但避免刷屏：只对关注的联系人
        return False

    def _handle_at_me(self, msg: dict) -> None:
        """@我 → 立即抽出这条（附上下文）推给我"""
        room = msg.get("room_name") or msg.get("room_id") or "私聊"
        sender = msg.get("sender") or "?"
        content = (msg.get("content") or "").strip()
        # 附上最近 5 条上下文，方便判断在说什么
        ctx = self.store.query_since(int(time.time()) - 600)
        ctx = [m for m in ctx if (m.get("room_id") or "") == (msg.get("room_id") or "")][-6:]
        ctx_text = "\n".join(
            f"[{'我' if m.get('is_self') else (m.get('sender') or '?')[:10]}] {(m.get('content') or '')[:150]}"
            for m in ctx
        )
        title = f"[@我] {room} · {sender}"
        try:
            if self.summarizer:
                out = self.summarizer.chat_log_analysis(
                    f"以下是 {room} 的近期对话，其中 {sender} @了我：\n\n{ctx_text}\n\n"
                    f"请告诉我：①他在问什么 ②我该怎么回（给 2 条候选）"
                )
            else:
                out = content
        except Exception as e:
            out = f"{sender} 在 {room} 提到你：{content}\n（AI 分析失败：{e}）"
        self.pusher.send(title, out)
        self.store.add_summary(title, out, "at_me")
        print(f"[@我] 已实时推送：{title}")

    def _handle_video(self, links: list) -> None:
        platforms = self.cfg["video"]["platforms"]
        for url in links:
            if not is_video_link(url, platforms):
                continue
            print(f"[video] 开始解析: {url}")
            title = url[:40]
            summary = None
            if self.cfg["video"].get("use_pipeline"):
                summary = try_pipeline(url)
            if not summary:
                v = collect_video(url)
                summary = self.summarizer.summarize_video(
                    v["title"], v["subtitle"] or "", v["tags"], v["comments"])
                title = v["title"] or title
            t = f"[视频解析] {title}"
            self.pusher.send(t, summary)
            self.store.add_summary(t, summary, "video")

    def _suggest_reply(self, msg: dict) -> None:
        recent = self.store.query_since(int(time.time()) - 3600, is_group=False)
        context = "\n".join(
            f"[{'我' if m['is_self'] else '对方'}] {m['content'][:120]}"
            for m in recent[-10:]
        )
        if not context:
            context = msg.get("content", "")
        try:
            cand = self.summarizer.suggest_reply(context)
            self.pusher.send("[回复建议]", cand)
            self.store.add_summary("[回复建议]", cand, "reply")
        except Exception as e:
            print(f"[reply] 回复建议失败: {e}")

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------
    def _make_source(self):
        if self.cfg["message_source"]["type"] == "weflow":
            return WeFlowSource(self.cfg["message_source"]["weflow_base"])
        return WeChatFerrySource()

    def _start_backfill(self) -> None:
        if not self.cfg.get("backfill", {}).get("enabled", True):
            return
        lookback = self.cfg["backfill"].get("lookback_hours", 24)

        def _run():
            last = self._read_last_run(lookback)
            history_backfill.backfill(self.store, since_ts=last)  # 只落库，不触发实时动作
            self._save_last_run()

        threading.Thread(target=_run, daemon=True).start()

    def start(self) -> None:
        """CLI 用：阻塞监听（Ctrl+C 退出）"""
        self._start_backfill()
        self.scheduler.start()
        source = self._make_source()
        try:
            source.start(self.on_message)
        except KeyboardInterrupt:
            self._save_last_run()
            print("\n已退出")

    def start_background(self) -> None:
        """Web 用：后台线程监听，不阻塞；监听失败则进入「仅查看模式」"""
        self._start_backfill()
        self.scheduler.start()
        try:
            source = self._make_source()
        except Exception as e:
            print(f"[engine] 消息源初始化失败（进入仅查看模式，界面仍可用）: {e}")
            return

        def _run():
            try:
                source.start(self.on_message)
            except Exception as e:
                print(f"[engine] 消息监听失败（进入仅查看模式）: {e}")

        threading.Thread(target=_run, daemon=True).start()
        print("[engine] 后台监听已启动")

    # ------------------------------------------------------------------
    # 供 Web 调用
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 选中即分析（划词 → DeepSeek → 结果）
    # ------------------------------------------------------------------
    def analyze_selection(self, text: str = None, hint: str = "", use_clipboard: bool = True) -> dict:
        """
        分析「选中的内容」。
        - text 传了就用 text；没传且 use_clipboard=True 则从剪贴板/选中区取
        - 返回 {"kind","title","text",...}，供悬浮窗 / 网页展示
        """
        from core.selection import analyze_selection as _analyze
        if text is None and use_clipboard:
            from core.selection import grab_with_restore
            text = grab_with_restore()
        res = _analyze(self.cfg, self.summarizer, text=text or "", hint=hint)
        # 落库，方便网页/桌面回看
        try:
            self.store.add_summary(f"[选中] {res.get('title', '')}", res.get("text", ""),
                                   f"selection_{res.get('kind', 'text')}")
        except Exception:
            pass
        return res

    def get_stats(self) -> dict:
        from core import stats as st
        msgs = self.store.all()
        # 覆盖的会话数（群 + 私聊），用于首页统计卡
        rooms = len({m.get("roomid") or m.get("room_id") or m.get("sender") or ""
                     for m in msgs} - {""})
        return {
            "total": len(msgs),
            "rooms": rooms,
            "words": st.top_words(msgs, 10),
            "wx_emoji": st.top_wx_emoji(msgs, 8),
            "emoji": st.top_unicode_emoji(msgs, 8),
        }

    def messages_since(self, since_ts: int, limit: int = 100) -> list:
        return self.store.query_since(since_ts)[-limit:]

    def summaries(self, limit: int = 50) -> list:
        return self.store.list_summaries(limit)

    def trigger_summary(self, kind: str = "daily") -> dict:
        """
        kind:
          daily  → 活跃群/整体，出当天统计（每天一次的那个）
          weekly → 免打扰/折叠群，出一周汇总（每周一次的那个）
        """
        if kind in ("weekly", "weekly_muted", "muted"):
            self.scheduler._weekly_muted()
            return {"ok": True, "kind": "weekly_muted"}
        self.scheduler._daily_all()
        return {"ok": True, "kind": "daily_all"}

    # ------------------------------------------------------------------
    # 时间戳持久化
    # ------------------------------------------------------------------
    def _read_last_run(self, lookback_hours: int = 24) -> int:
        try:
            with open(LAST_RUN_FILE, "r") as f:
                return int(f.read().strip())
        except Exception:
            return int(time.time()) - lookback_hours * 3600

    def _save_last_run(self) -> None:
        try:
            os.makedirs(os.path.dirname(LAST_RUN_FILE), exist_ok=True)
            with open(LAST_RUN_FILE, "w") as f:
                f.write(str(int(time.time())))
        except Exception:
            pass
