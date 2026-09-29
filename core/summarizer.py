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
        self._apply_cfg(cfg)

    def _apply_cfg(self, cfg: dict) -> None:
        """把配置应用到实例；网页界面改了 key 后调用它即可热更新（无需重启）"""
        self.cfg = cfg
        ai = cfg.get("ai", {}) or {}
        self.api_key = ai.get("api_key", "")
        self.base_url = ai.get("base_url", "https://api.deepseek.com/v1")
        self.model = ai.get("model", "deepseek-chat")
        self.max_tokens = ai.get("max_tokens", 800)
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key or "sk-placeholder")

    def reload(self) -> None:
        """从磁盘重读配置（网页界面保存后由后端调用）"""
        from core.config import load
        self._apply_cfg(load())

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
        """群聊汇总（兼容旧调用）：默认按「活跃群 = 当日统计」处理"""
        return self.analyze_group_messages(messages, freq="daily")

    def suggest_reply(self, context: str) -> str:
        """回复建议：结合历史对话，测算最贴切的回复（几条候选）"""
        return self._chat(
            "你是聊天助手。根据对话上下文，给出 2-3 条自然、符合说话人语气的候选回复，"
            "每条一行。风格贴合上下文的亲密程度，不要生硬。",
            context,
            temperature=0.7,
        )

    # ------------------------------------------------------------------
    # 选中即分析（划词 / 选聊天记录 / 选表情包）
    # ------------------------------------------------------------------

    def analyze_text(self, text: str) -> str:
        """选中一段长文字 → 精炼摘要 + 要点 + 建议动作"""
        return self._chat(
            "你是信息提炼助手。用户选中了一段文字，请用中文输出，控制在 200 字内：\n"
            "• 一句话概括核心\n"
            "• 2-4 条要点（每条一行，开头「•」）\n"
            "• 若有需要我做的事，单列一行「待办：」\n"
            "不要复述原文，不要加客套话。",
            text[:8000],
        )

    def chat_log_analysis(self, text: str) -> str:
        """选中一段聊天记录 → 谁在说什么 / 有没有@我 / 我该回什么"""
        return self._chat(
            "你是群聊观察员。用户选中了一段微信聊天记录，请用中文输出：\n"
            "① 讨论主题（一句话）\n"
            "② 关键信息 / 决定 / 链接（有则列，无则省略这行）\n"
            "③ 有没有点到「我」或与我相关的待办\n"
            "④ 给出 2 条可直接发送的候选回复（若这段对话需要我回）\n"
            "简洁，总字数 250 字内。",
            text[:8000],
        )

    def analyze_group_messages(self, messages: list, freq: str = "daily") -> str:
        """群聊汇总：freq = daily（活跃群/整体）| weekly（免打扰/折叠群）"""
        text = "\n".join(
            f"[{m.get('sender', '?')[:8]}] {m.get('content', '')[:200]}"
            for m in messages[:400]
        )
        if freq == "weekly":
            sys = (
                "你是群聊观察员，负责给「免打扰/折叠群」做**周度**汇总。用中文输出：\n"
                "① 本周主要讨论了哪几件事（分条）\n"
                "② 有没有@我/与我相关的待办（重要）\n"
                "③ 值得点开的链接或重要决定\n"
                "④ 一句话结论：这个群本周值不值得回看\n"
                "控制在 350 字内。"
            )
        else:
            sys = (
                "你是群聊观察员，负责给「活跃群」做**当日**统计摘要。用中文输出：\n"
                "① 今日话题（分条，按热度排序）\n"
                "② 关键信息/链接/决定\n"
                "③ 有没有@我/与我相关的待办\n"
                "④ 发言最活跃的几个人（若有）\n"
                "控制在 300 字内。"
            )
        return self._chat(sys, text)

    def describe_image(self, image_b64: str, prompt: str) -> str:
        """图片/表情包识别（需配置 vision_model）"""
        model = self.cfg_vision_model()
        if not model or not _has_key(self.api_key):
            return "[未配置视觉模型，跳过图片识别]"
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
            max_tokens=self.max_tokens,
        )
        return resp.choices[0].message.content.strip()

    def cfg_vision_model(self) -> str:
        return (self.cfg.get("ai", {}) or {}).get("vision_model", "")


def _has_key(key: str) -> bool:
    """判断是否填了 API key（避免空 key 直接报错）"""
    return bool(key) and key != "sk-xxxxxxxx"
