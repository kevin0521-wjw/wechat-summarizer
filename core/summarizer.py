# -*- coding: utf-8 -*-
"""
AI 总结
========
用 DeepSeek（OpenAI 兼容接口）把一段文本/字幕总结成要点。

设计要点：
- 兼容任意 OpenAI 兼容 endpoint（DeepSeek / Qwen / 本地 LLM 都能换）
- 提供多个 prompt 模板：视频总结、群聊汇总、回复建议
"""
from openai import OpenAI


class Summarizer:
    def __init__(self, cfg: dict):
        self.api_key = cfg["ai"]["api_key"]
        self.client = OpenAI(
            base_url=cfg["ai"]["base_url"],
            api_key=self.api_key,
        )
        self.model = cfg["ai"]["model"]
        self.max_tokens = cfg["ai"]["max_tokens"]

    def _chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        if not _has_key(self.api_key):
            return "[未配置 AI key，跳过总结]"
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=self.max_tokens,
        )
        return resp.choices[0].message.content.strip()

    def summarize_video(self, title: str, transcript: str, tags: list = None, comments: str = None) -> str:
        """视频总结：标题 + 字幕 + 评论 → 3-5 条要点 + 观众关注点"""
        tag_str = "、".join(tags) if tags else "无"
        parts = [f"视频标题：{title}", f"标签：{tag_str}", f"字幕文本：\n{transcript[:5000]}"]
        if comments:
            parts.append(f"热门评论：\n{comments[:1500]}")
        user = "\n\n".join(parts)
        return self._chat(
            "你是信息提炼助手。用中文总结视频：先输出 3-5 条内容要点（每条一行，开头「•」），"
            "再单列一行「观众关注点：」概括评论区集中讨论的方向。"
            "若字幕不全，据标题和已知信息推测并注明。",
            user,
        )

    def summarize_group(self, messages: list) -> str:
        """群聊每日汇总：一天的消息 → 一段浓缩总结"""
        text = "\n".join(
            f"[{m.get('sender', '?')[:8]}] {m.get('content', '')[:200]}"
            for m in messages[:200]  # 最多喂 200 条，防止超长
        )
        return self._chat(
            "你是群聊观察员。把一段微信群聊记录浓缩成简洁日报："
            "① 今日讨论了哪些主题 ② 有没有@我/与我相关的待办 ③ 值得关注的链接或决定。"
            "用中文，控制在 200 字内。",
            text,
        )

    def suggest_reply(self, context: str) -> str:
        """回复建议：结合历史对话，测算最贴切的回复（几条候选）"""
        return self._chat(
            "你是聊天助手。根据对话上下文，给出 2-3 条自然、符合说话人语气的候选回复，"
            "每条一行。风格贴合上下文的亲密程度，不要生硬。",
            context,
            temperature=0.7,
        )


def _has_key(key: str) -> bool:
    """判断是否填了 API key（避免空 key 直接报错）"""
    return bool(key) and key != "sk-xxxxxxxx"
