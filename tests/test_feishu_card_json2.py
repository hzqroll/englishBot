"""验证飞书卡片 JSON 2.0 结构正确性。"""

import json

from src.domain.value_objects.messaging import CardDocument, CardSection
from src.infrastructure.channels.feishu import FeishuChannel


def _make_channel() -> FeishuChannel:
    return FeishuChannel(app_id="test", app_secret="test")


def _sample_doc() -> CardDocument:
    return CardDocument(
        title="测试卡片",
        subtitle="副标题",
        sections=[
            CardSection(title="核心词块", lines=["apple  /ˈæpl/\n苹果\n场景：水果店\n例句：I bought an apple."]),
            CardSection(title="支持词汇", lines=["banana"]),
            CardSection(title="办公室情景对话", lines=["A: Hello! B: Hi!"]),
            CardSection(title="任务 1 · 造句", lines=["用 apple 造句", "提交命令：提交任务 1 你的答案"]),
            CardSection(title="任务 2 · 翻译", lines=["翻译以下句子", "提交命令：提交任务 2 你的答案"]),
        ],
        footer_lines=["完成后直接在群里发送对应提交命令。"],
    )


def _assert_valid_json2(card_json: dict) -> None:
    """断言 JSON 2.0 必要结构。"""
    assert card_json["schema"] == "2.0", "必须有 schema: 2.0"
    assert "config" not in card_json, "JSON 2.0 不应有 config.wide_screen_mode"
    body = card_json["body"]
    assert body["direction"] == "vertical", "body.direction 必须为 vertical"
    assert "padding" in body, "body 必须有 padding"
    assert "elements" in body, "body 必须有 elements"
    header = card_json["header"]
    assert "padding" in header, "header 必须有 padding"
    assert header["title"]["tag"] == "plain_text"
    assert header["subtitle"]["tag"] == "plain_text"
    # elements 中不应有 JSON 1.0 的 div/lark_md tag，也不应有 note
    for el in body["elements"]:
        if "tag" in el and el["tag"] == "markdown":
            assert "content" in el, "markdown element 必须有 content"
        assert el.get("tag") != "note", "JSON 2.0 不支持 note tag"


def test_generic_card_json2_structure():
    """通用渲染器 (_render_card_document) 输出正确的 JSON 2.0 结构。"""
    ch = _make_channel()
    doc = _sample_doc()
    card_json = ch._render_card_document(doc)
    _assert_valid_json2(card_json)
    # 验证内容存在
    elements = card_json["body"]["elements"]
    tags = [e.get("tag") for e in elements]
    assert "markdown" in tags
    assert "hr" in tags
    # 页脚用 markdown + grey font 代替 note
    footer_md = [e for e in elements if e.get("tag") == "markdown" and "grey" in (e.get("content") or "")]
    assert len(footer_md) > 0, "页脚应使用 markdown + grey font"


def test_task_card_json2_structure():
    """每日任务渲染器 (_render_task_card) 输出正确的 JSON 2.0 结构。"""
    ch = _make_channel()
    doc = _sample_doc()
    card_json = ch._render_task_card(doc)
    _assert_valid_json2(card_json)
    elements = card_json["body"]["elements"]
    # 应包含 collapsible_panel
    tags = [e.get("tag") for e in elements]
    assert "collapsible_panel" in tags, "应包含折叠面板（支持词汇）"
    # 任务应合并为一个折叠面板
    task_panels = [e for e in elements if e.get("tag") == "collapsible_panel" and "任务" in e.get("header", {}).get("title", {}).get("content", "")]
    assert len(task_panels) == 1, "应有一个任务折叠面板"
    task_elements = task_panels[0].get("elements", [])
    task_contents = [e.get("content", "") for e in task_elements if e.get("tag") == "markdown"]
    assert any("造句" in c for c in task_contents), "任务面板中应包含造句任务"


def test_task_card_compact_vocab():
    """词汇 4 行格式应压缩为 2 行。"""
    line = "apple  /ˈæpl/\n苹果\n场景：水果店\n例句：I bought an apple."
    result = FeishuChannel._compact_vocab_line(line)
    assert result.count("\n") == 1, f"应为 2 行，实际：{result}"
    assert "**apple" in result
    assert "苹果" in result


def test_card_json_serializable():
    """渲染结果应可 JSON 序列化。"""
    ch = _make_channel()
    doc = _sample_doc()
    for renderer in (ch._render_card_document, ch._render_task_card):
        card_json = renderer(doc)
        text = json.dumps(card_json, ensure_ascii=False)
        assert '"schema": "2.0"' in text
