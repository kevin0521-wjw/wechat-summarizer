# -*- coding: utf-8 -*-
"""
消息落库（SQLite）
==================
把所有消息存到本地 SQLite，供：
- 每日/每周汇总查询
- 词频/表情统计
- 历史回溯

用标准库 sqlite3，零额外依赖。
"""
import os
import sqlite3
import time


class Store:
    def __init__(self, path: str = "data/msgs.db"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS msgs (
                msg_id   TEXT PRIMARY KEY,
                sender   TEXT,
                room_id  TEXT,
                is_group INTEGER,
                type     INTEGER,
                content  TEXT,
                xml      TEXT,
                ts       INTEGER,
                is_self  INTEGER
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                title   TEXT,
                content TEXT,
                kind    TEXT,
                ts      INTEGER
            )
        """)
        self.conn.commit()

    def add(self, msg: dict) -> None:
        """写入一条消息（msg_id 去重）"""
        try:
            self.conn.execute(
                "INSERT OR IGNORE INTO msgs VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    msg.get("msg_id", ""),
                    msg.get("sender", ""),
                    msg.get("room_id", ""),
                    int(msg.get("is_group", False)),
                    msg.get("type", 0),
                    msg.get("content", ""),
                    msg.get("xml", ""),
                    msg.get("ts", int(time.time())),
                    int(msg.get("is_self", False)),
                ),
            )
            self.conn.commit()
        except Exception as e:
            print(f"[db] 写入失败: {e}")

    def query_since(self, since_ts: int, room_id: str = None, is_group: bool = None) -> list:
        """查询某时间之后的消息，可按群/私聊过滤。返回 [dict,...]"""
        sql = "SELECT msg_id,sender,room_id,is_group,type,content,xml,ts,is_self FROM msgs WHERE ts >= ?"
        args = [since_ts]
        if room_id is not None:
            sql += " AND room_id = ?"
            args.append(room_id)
        if is_group is not None:
            sql += " AND is_group = ?"
            args.append(int(is_group))
        sql += " ORDER BY ts ASC"
        rows = self.conn.execute(sql, args).fetchall()
        keys = ["msg_id", "sender", "room_id", "is_group", "type", "content", "xml", "ts", "is_self"]
        return [dict(zip(keys, r)) for r in rows]

    def all(self) -> list:
        """全部消息（统计用）"""
        return self.query_since(0)

    def add_summary(self, title: str, content: str, kind: str = "manual") -> None:
        """记录一次汇总/推送结果（供网页版展示历史）"""
        try:
            self.conn.execute(
                "INSERT INTO summaries (title, content, kind, ts) VALUES (?,?,?,?)",
                (title, content, kind, int(time.time())),
            )
            self.conn.commit()
        except Exception as e:
            print(f"[db] 记录汇总失败: {e}")

    def list_summaries(self, limit: int = 50) -> list:
        """最近的汇总记录（倒序）"""
        rows = self.conn.execute(
            "SELECT title, content, kind, ts FROM summaries ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"title": r[0], "content": r[1], "kind": r[2], "ts": r[3]} for r in rows]

    def count(self) -> int:
        """消息总数（仪表盘用）"""
        return self.conn.execute("SELECT COUNT(*) FROM msgs").fetchone()[0]
