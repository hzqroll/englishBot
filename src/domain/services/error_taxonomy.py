from __future__ import annotations


WORD_ERROR_TYPES = {
    "expression",
    "natural_expression",
    "spelling",
    "word_choice",
}

GRAMMAR_ERROR_TYPES = {
    "agreement",
    "article",
    "grammar",
    "plural",
    "preposition",
    "tense",
}


def categorize_error_type(error_type: str) -> str:
    normalized = (error_type or "").strip().lower()
    if normalized in WORD_ERROR_TYPES:
        return "word"
    if normalized in GRAMMAR_ERROR_TYPES:
        return "grammar"
    return "grammar"


def label_error_type(error_type: str) -> str:
    labels = {
        "tense": "时态",
        "preposition": "介词",
        "article": "冠词",
        "plural": "单复数",
        "spelling": "拼写",
        "word_choice": "词语搭配",
        "agreement": "主谓一致",
        "natural_expression": "表达自然度",
        "expression": "表达问题",
        "grammar": "语法结构",
    }
    return labels.get((error_type or "").strip().lower(), error_type or "未分类")
