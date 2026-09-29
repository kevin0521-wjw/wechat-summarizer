# -*- coding: utf-8 -*-
"""
推送层
=======
把「总结结果」发到你方便看到的地方。多通道可同时开：

  ┌─ Server 酱      → 推到你微信（服务号），手机端首选，免费额度够日常
  ├─ PushPlus       → 同样推微信，备用
  ├─ 企业微信群机器人 → 推到你自己的企微群（免费注册企微即可）
  ├─ Windows Toast  → 电脑桌面右下角弹窗（电脑在线时最直观）
  └─ txt 落盘       → 兜底，永远可用
"""
import os
import requests


class Pusher:
    def __init__(self, cfg: dict):
        self.cfg = cfg["push"]
        self.txt_file = self.cfg.get("txt_file", "output/summary.txt")

    def send(self, title: str, content: str) -> None:
        """按配置把一条消息推到所有开启的通道"""
        results = []
        results.append(("txt", self._to_txt(title, content)))
        results.append(("serverchan", self._serverchan(title, content)))
        results.append(("pushplus", self._pushplus(title, content)))
        results.append(("wecom", self._wecom(content)))
        results.append(("toast", self._toast(title, content)))
        # 打印各通道结果，方便排查
        done = [name for name, ok in results if ok]
        print(f"[push] 已发送: {', '.join(done) if done else '无'}")

    # ---------- 各通道实现 ----------

    def _to_txt(self, title: str, content: str) -> bool:
        try:
            os.makedirs(os.path.dirname(self.txt_file), exist_ok=True)
            with open(self.txt_file, "a", encoding="utf-8") as f:
                f.write(f"\n===== {title} =====\n{content}\n")
            return True
        except Exception:
            return False

    def _serverchan(self, title: str, content: str) -> bool:
        key = self.cfg.get("serverchan_key", "")
        if not key:
            return False
        try:
            # 新版 Server 酱 Turbo：https://sctapi.ftqq.com/{SendKey}.send
            r = requests.post(
                f"https://sctapi.ftqq.com/{key}.send",
                data={"title": title, "desp": content},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def _pushplus(self, title: str, content: str) -> bool:
        token = self.cfg.get("pushplus_token", "")
        if not token:
            return False
        try:
            r = requests.post(
                "http://www.pushplus.plus/send",
                json={"token": token, "title": title, "content": content},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def _wecom(self, content: str) -> bool:
        """企业微信群机器人 webhook（纯 markdown 文本）"""
        url = self.cfg.get("wecom_webhook", "")
        if not url:
            return False
        try:
            r = requests.post(
                url,
                json={"msgtype": "text", "text": {"content": content[:4000]}},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def _toast(self, title: str, content: str) -> bool:
        """Windows Toast 桌面弹窗（winotify）"""
        if not self.cfg.get("toast", True):
            return False
        try:
            from winotify import Notification
            toast = Notification(
                app_id="微信AI助手",
                title=title,
                msg=content[:120],  # Toast 正文有长度限制
                duration="short",
            )
            toast.show()
            return True
        except Exception:
            return False
