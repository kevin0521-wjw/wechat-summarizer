# -*- coding: utf-8 -*-
"""
数据统计 / 分析
================
分析历史聊天记录：
- 词频（jieba 分词，中文热词）
- emoji 频率
- 表情包使用（微信表情 [微笑] [笑哭] 这类文本 token 的统计）
- 回复建议（测算最佳回复，接 Summarizer.suggest_reply）

参考现成项目：
- WeChatMsg / MemoTrace（LC044/WeChatMsg）：16.6k star，词云/情感/年度报告
- Message_Analysis（oorangeeee）：词频 + emoji 频率 + 表情包分类统计
- wechat-emojis（xxk8）：109 个微信内置表情的资源与映射
"""
import re
from collections import Counter

# 微信内置表情 token：形如 [微笑]、[笑哭]、[捂脸] 的方括号文本
WX_EMOJI_RE = re.compile(r"\[[^\]]{1,8}\]")
# 常见 emoji 字符（简化版，覆盖常用范围）
UNICODE_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF\uFE0F]"
)


def top_words(messages: list, k: int = 20, stopwords: set = None) -> list:
    """词频统计（需 jieba）。返回 [(词, 次数), ...]"""
    try:
        import jieba
    except ImportError:
        return []
    stop = stopwords or {"的", "了", "是", "我", "你", "他", "她", "在", "就", "不", "也", "有", "和", "啊", "吧", "呢"}
    counter = Counter()
    for m in messages:
        text = m.get("content", "")
        for w in jieba.cut(text):
            w = w.strip()
            if len(w) >= 2 and w not in stop:
                counter[w] += 1
    return counter.most_common(k)


def top_wx_emoji(messages: list, k: int = 10) -> list:
    """微信内置表情（[微笑] 这类）使用频率"""
    counter = Counter()
    for m in messages:
        for e in WX_EMOJI_RE.findall(m.get("content", "")):
            counter[e] += 1
    return counter.most_common(k)


def top_unicode_emoji(messages: list, k: int = 10) -> list:
    """Unicode emoji（😀😂👍）使用频率"""
    counter = Counter()
    for m in messages:
        for e in UNICODE_EMOJI_RE.findall(m.get("content", "")):
            counter[e] += 1
    return counter.most_common(k)


def stats_report(messages: list) -> str:
    """生成一段可读的统计报告文本"""
    words = top_words(messages, 10)
    wx_e = top_wx_emoji(messages, 8)
    uni_e = top_unicode_emoji(messages, 8)

    lines = ["【聊天数据统计】", f"消息总数：{len(messages)}"]
    if words:
        lines.append("热词 Top：" + "、".join(f"{w}({n})" for w, n in words))
    if wx_e:
        lines.append("微信表情 Top：" + "、".join(f"{e}({n})" for e, n in wx_e))
    if uni_e:
        lines.append("Emoji Top：" + "、".join(f"{e}({n})" for e, n in uni_e))
    return "\n".join(lines)
