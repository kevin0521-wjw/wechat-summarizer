# -*- coding: utf-8 -*-
"""
定时汇总调度
==============
按用户确定的规则分层（**注意方向，与常见直觉相反**）：

  ├─ 免打扰 / 折叠群  → **每周一次**汇总（这些群消息多又杂，天天推是噪音）
  ├─ 活跃群 / 整体    → **每天**出统计（词频/表情/发言排行）
  ├─ @我的           → **实时**抽出（不走定时，见 engine.on_message）
  └─ 视频/链接        → **实时**秒级解析（同上，不走定时）

用 schedule 库在独立线程里跑（消息源在主线程阻塞）。
"""
import time
import threading
import schedule


class Scheduler:
    def __init__(self, cfg: dict, store, summarizer, pusher):
        self.cfg = cfg
        self.store = store
        self.summarizer = summarizer
        self.pusher = pusher
        self.muted_rooms = set(cfg["focus"]["muted_rooms"])
        self.active_rooms = set(cfg["focus"].get("active_rooms", []))

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------
    def start(self) -> None:
        """在后台线程里注册并运行定时任务"""
        sc = self.cfg["schedule"]
        muted_time = sc.get("muted_group_weekly", "sun 21:00")   # 免打扰/折叠群 → 每周
        daily_time = sc.get("daily_stats", "21:00")              # 活跃群/整体 → 每天

        # 每周几 + 时间
        weekday, hhmm = self._parse_weekly(muted_time)
        getattr(schedule.every(), weekday).at(hhmm).do(self._weekly_muted)
        schedule.every().day.at(daily_time).do(self._daily_all)

        def _loop():
            while True:
                schedule.run_pending()
                time.sleep(30)  # 30 秒检查一次

        threading.Thread(target=_loop, daemon=True).start()
        print(f"[schedule] 已注册：免打扰群汇总 {muted_time}（每周）/ 活跃群统计 {daily_time}（每天）")

    @staticmethod
    def _parse_weekly(expr: str):
        """'sun 21:00' → ('sunday', '21:00')"""
        parts = expr.strip().split()
        if len(parts) == 2:
            day, hhmm = parts
        else:
            day, hhmm = "sunday", parts[0] if parts else "21:00"
        days = {"mon": "monday", "tue": "tuesday", "wed": "wednesday",
                "thu": "thursday", "fri": "friday", "sat": "saturday", "sun": "sunday"}
        return days.get(day.lower()[:3], "sunday"), hhmm

    # ------------------------------------------------------------------
    # 免打扰 / 折叠群 → 每周一次 AI 汇总
    # ------------------------------------------------------------------
    def _weekly_muted(self) -> None:
        since = int(time.time()) - 7 * 24 * 3600
        msgs = self.store.query_since(since, is_group=True)

        rooms: dict = {}
        for m in msgs:
            rid = m.get("room_id") or ""
            room_name = m.get("room_name") or rid
            # 只处理免打扰/折叠群；配置为空则跳过（避免把正常群也周汇总）
            if not self.muted_rooms:
                continue
            if rid not in self.muted_rooms and room_name not in self.muted_rooms:
                continue
            rooms.setdefault(room_name, []).append(m)

        if not rooms:
            print("[schedule] 本周无免打扰群消息")
            return

        for room_name, rmsgs in rooms.items():
            summary = self.summarizer.analyze_group_messages(rmsgs, freq="weekly")
            title = f"[每周汇总] {room_name}"
            self.pusher.send(title, summary)
            self.store.add_summary(title, summary, "weekly_muted")
        print(f"[schedule] 已周度汇总 {len(rooms)} 个免打扰群")

    # ------------------------------------------------------------------
    # 活跃群 / 整体 → 每天出统计
    # ------------------------------------------------------------------
    def _daily_all(self) -> None:
        from core import stats
        since = int(time.time()) - 24 * 3600
        msgs = self.store.query_since(since)
        if not msgs:
            print("[schedule] 今日无消息，跳过日统计")
            return

        report = self._build_daily_report(msgs, since)

        # 活跃群单独出 AI 摘要（每天）
        active = {r: [m for m in msgs if (m.get("room_name") or m.get("room_id")) == r]
                  for r in self._active_room_names(msgs)}
        for room_name, rmsgs in active.items():
            if len(rmsgs) < 5:      # 太冷清的群不单独出
                continue
            ai_sum = self.summarizer.analyze_group_messages(rmsgs, freq="daily")
            title = f"[每日统计] {room_name}"
            self.pusher.send(title, ai_sum + "\n\n— — —\n" + report)
            self.store.add_summary(title, ai_sum, "daily_active")

        # 整体统计
        self.pusher.send("[每日统计] 全部聊天", report)
        self.store.add_summary("[每日统计] 全部聊天", report, "daily_all")
        print(f"[schedule] 日统计已发送（{len(msgs)} 条消息 / {len(active)} 个活跃群）")

    def _active_room_names(self, msgs: list) -> list:
        """活跃群 = 配置的 active_rooms；未配置则按消息量取当天 top 5"""
        if self.active_rooms:
            return list(self.active_rooms)
        counter: dict = {}
        for m in msgs:
            if not m.get("is_group"):
                continue
            name = m.get("room_name") or m.get("room_id") or ""
            if name:
                counter[name] = counter.get(name, 0) + 1
        ranked = sorted(counter.items(), key=lambda kv: -kv[1])
        return [name for name, cnt in ranked[:5] if cnt >= 5]

    def _build_daily_report(self, msgs: list, since: int) -> str:
        """纯统计部分（不花 AI token，永远可用）"""
        from core import stats
        parts = [f"统计区间：{time.strftime('%m-%d %H:%M', time.localtime(since))} ~ 现在",
                 f"消息总数：{len(msgs)} 条"]

        groups = [m for m in msgs if m.get("is_group")]
        privates = [m for m in msgs if not m.get("is_group")]
        parts.append(f"群聊 {len(groups)} 条 / 私聊 {len(privates)} 条")

        # 发言排行
        speaker: dict = {}
        for m in msgs:
            if not m.get("is_self"):
                s = m.get("sender") or "?"
                speaker[s] = speaker.get(s, 0) + 1
        top = sorted(speaker.items(), key=lambda kv: -kv[1])[:5]
        if top:
            parts.append("发言最多：" + "、".join(f"{s}({c})" for s, c in top))

        # 热词 / 表情
        try:
            words = stats.top_words(msgs, 8)
            if words:
                pairs = [w if isinstance(w, (tuple, list)) else (w, "") for w in words]
                parts.append("热词：" + "、".join(
                    f"{w}({c})" if c != "" else str(w) for w, c in pairs))
        except Exception:
            pass
        try:
            emoji = stats.top_wx_emoji(msgs, 5)
            if emoji:
                parts.append("常用表情：" + "、".join(f"{e}x{c}" for e, c in emoji))
        except Exception:
            pass

        # 链接汇总
        from core.dispatcher import extract_links
        links = []
        for m in msgs:
            links += extract_links(m.get("content", ""))
        if links:
            parts.append(f"今日链接 {len(links)} 个，前 3 个：")
            parts += [f"  · {u}" for u in links[:3]]

        return "\n".join(parts)

    # 兼容旧接口（网页版按钮 / 手动触发）
    def _daily_muted(self) -> None:
        self._daily_all()

    def _weekly(self) -> None:
        self._weekly_muted()
