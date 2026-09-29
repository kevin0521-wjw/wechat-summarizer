# -*- coding: utf-8 -*-
"""
定时汇总调度
==============
- 每日：把「免打扰/折叠群」过去 24h 的消息汇总成一段日报，推送给你
- 每周：出聊天数据周报（词频/表情统计 + AI 总结）
- 实时视频：不走这里，在 main 的消息回调里即时处理

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

    def start(self) -> None:
        """在后台线程里注册并运行定时任务"""
        daily = self.cfg["schedule"]["muted_group_daily"]
        weekly = self.cfg["schedule"]["weekly_report"]
        schedule.every().day.at(daily).do(self._daily_muted)
        schedule.every().monday.at(weekly.split(" ")[-1]).do(self._weekly)

        def _loop():
            while True:
                schedule.run_pending()
                time.sleep(30)  # 30 秒检查一次

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        print(f"[schedule] 已注册：每日汇总 {daily} / 周报 {weekly}")

    def _daily_muted(self) -> None:
        """汇总过去 24h 的群消息（按群分组）"""
        since = int(time.time()) - 24 * 3600
        msgs = self.store.query_since(since, is_group=True)
        # 按群分组
        rooms: dict = {}
        for m in msgs:
            rid = m["room_id"]
            # 只汇总免打扰群（若配置为空则汇总所有群）
            if self.muted_rooms and rid not in self.muted_rooms:
                continue
            rooms.setdefault(rid, []).append(m)

        if not rooms:
            print("[schedule] 今日无免打扰群消息")
            return

        for rid, rmsgs in rooms.items():
            summary = self.summarizer.summarize_group(rmsgs)
            title = f"[每日汇总] 群 {rid[:12]}"
            self.pusher.send(title, summary)
            self.store.add_summary(title, summary, "daily")   # 记录供网页版查看
        print(f"[schedule] 已汇总 {len(rooms)} 个群")

    def _weekly(self) -> None:
        """周报：统计 + AI 总结"""
        from core import stats
        since = int(time.time()) - 7 * 24 * 3600
        msgs = self.store.query_since(since)
        report = stats.stats_report(msgs)
        # 把统计结果交给 AI 润色成一段周报（可选）
        self.pusher.send("[每周报告] 聊天数据周报", report)
        self.store.add_summary("[每周报告] 聊天数据周报", report, "weekly")
        print("[schedule] 周报已发送")
