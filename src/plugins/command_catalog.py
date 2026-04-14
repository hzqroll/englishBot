from __future__ import annotations

EXACT_COMMANDS = (
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
    "添加新词",
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
        "默认模式：晨间执行卡会自动推送，白天直接在群里发英文即可。\n\n"
        "兜底命令（不需要 @机器人）：\n"
        "- 今日任务：获取今日学习内容\n"
        "- 提交任务 <任务ID> <内容>\n"
        "- 复习一下：复习待巩固的知识点\n"
        "- 我的等级：查看学习等级和统计\n"
        "- 开始周测：开始本周测试\n"
        "- 答题 <试卷ID> 1:A 2:B\n"
        "- 添加新词 <word1 word2 ...>：批量记录今日新词\n"
        "- 本周总结：查看本周学习报告\n"
        "- 帮助：显示此帮助\n\n"
        "@机器人 只用于翻译 / 纠错 / 分析：\n"
        "- 发英文 → 纠错 + 翻译\n"
        "- 发中文 → 翻译成英文\n"
        "- 大模型润色：<对话内容> → 整体分析\n"
        "- 分析最近聊天内容 → 分析群聊"
    )
