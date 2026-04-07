from __future__ import annotations

EXACT_COMMANDS = (
    "报名学习",
    "今日任务",
    "复习一下",
    "我的等级",
    "开始周测",
    "本周总结",
    "帮助",
)
PREFIX_COMMANDS = (
    "提交任务",
    "答题",
)


def normalize_command_text(text: str) -> str:
    return text.strip()


def match_fixed_command(text: str) -> str | None:
    cleaned = normalize_command_text(text)
    if cleaned in EXACT_COMMANDS:
        return cleaned
    for prefix in PREFIX_COMMANDS:
        if cleaned.startswith(prefix):
            return prefix
    return None


def is_fixed_command_text(text: str) -> bool:
    return match_fixed_command(text) is not None


def render_help_text() -> str:
    return (
        "学习系统命令请直接发送，不需要 @机器人。\n\n"
        "固定命令：\n"
        "- 报名学习\n"
        "- 今日任务\n"
        "- 提交任务 <任务ID> <内容>\n"
        "- 复习一下\n"
        "- 我的等级\n"
        "- 开始周测\n"
        "- 答题 <试卷ID> 1:A 2:B\n"
        "- 本周总结\n"
        "- 帮助\n\n"
        "@机器人 只用于翻译、纠错和整体分析。\n"
        "@机器人 用法：\n"
        "- 中文：默认走腾讯翻译\n"
        "- 英文：默认走快速纠错\n"
        "- 大模型润色：<对话内容>\n"
        "- 分析最近聊天内容"
    )
