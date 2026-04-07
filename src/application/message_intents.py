from __future__ import annotations


EXPLICIT_DIALOGUE_ANALYSIS_PREFIX = "大模型润色"
RECENT_CHAT_ANALYSIS_KEYWORD = "分析最近聊天内容"


def normalize_message_text(text: str) -> str:
    return text.strip()


def extract_explicit_dialogue_analysis_text(text: str) -> str | None:
    cleaned = normalize_message_text(text)
    if not cleaned.startswith(EXPLICIT_DIALOGUE_ANALYSIS_PREFIX):
        return None

    suffix = cleaned[len(EXPLICIT_DIALOGUE_ANALYSIS_PREFIX):].lstrip()
    if not suffix or suffix[0] not in {":", "："}:
        return None

    payload = suffix[1:].strip()
    return payload or None


def is_recent_chat_analysis_request(text: str) -> bool:
    return normalize_message_text(text) == RECENT_CHAT_ANALYSIS_KEYWORD


def is_analysis_control_text(text: str) -> bool:
    cleaned = normalize_message_text(text)
    return cleaned == EXPLICIT_DIALOGUE_ANALYSIS_PREFIX or cleaned.startswith(EXPLICIT_DIALOGUE_ANALYSIS_PREFIX) or cleaned == RECENT_CHAT_ANALYSIS_KEYWORD
