"""验证飞书卡片 JSON 2.0 结构正确性。"""

import json

from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
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


def test_daily_session_card_uses_specialized_renderer():
    ch = _make_channel()
    envelope = MessageEnvelope(
        plain_text="demo",
        card_type="daily_session",
        card_document=CardDocument(
            title="Day 04/13 | 项目延期说明",
            subtitle="语音日",
            metadata={"chat_id": "oc_test", "biz_date": "2026-04-13"},
            sections=[
                CardSection(title="今日目标", lines=["今天练一轮真实工作场景互动。"]),
                CardSection(title="今日角色", lines=["A 发起：Alice", "B 接棒：Bob"]),
                CardSection(title="必须复用", lines=["Just a quick update on ..."]),
                CardSection(title="今天动作", lines=["A 先发 2-3 句", "B 接棒追问 2 句"]),
                CardSection(title="完成标准", lines=["至少完成 1 轮互动"]),
            ],
            footer_lines=["直接在群里开始。"],
        ),
    )

    card_json = ch._render_envelope_card(envelope)
    _assert_valid_json2(card_json)
    elements = card_json["body"]["elements"]
    hero_panels = [
        el for el in elements
        if el.get("tag") == "collapsible_panel" and "今天先做这一轮" in el.get("header", {}).get("title", {}).get("content", "")
    ]
    assert hero_panels, "daily_session 应走执行卡专用 renderer"
    action_bars = [el for el in elements if el.get("tag") == "action"]
    assert not action_bars, "schema 2.0 不支持 action tag"
    action_rows = [el for el in elements if el.get("tag") == "column_set"]
    assert action_rows, "执行卡应包含按钮行"
    labels = [col["elements"][0]["text"]["content"] for col in action_rows[0]["columns"]]
    assert labels == ["我先发起", "切到保底版", "查看本周文档"]
    action_value = action_rows[0]["columns"][0]["elements"][0]["value"]
    assert action_value["action"] == "claim_baton"
    assert action_value["chat_id"] == "oc_test"
    assert action_value["biz_date"] == "2026-04-13"


def test_progress_card_uses_compact_sections():
    ch = _make_channel()
    envelope = MessageEnvelope(
        plain_text="demo",
        card_type="progress",
        card_document=CardDocument(
            title="今晚进展",
            subtitle="A 已发起，等待 B 接棒。",
            metadata={"chat_id": "oc_test", "biz_date": "2026-04-13"},
            sections=[
                CardSection(title="今天到了哪", lines=["A 已发起，等待 B 接棒。"]),
                CardSection(title="学习证据", lines=["今天最像真实输出的一句：Could we reschedule the meeting?"]),
                CardSection(title="下一步", lines=["B 追问、澄清或补充 2 句。"]),
            ],
        ),
    )

    card_json = ch._render_envelope_card(envelope)
    _assert_valid_json2(card_json)
    panels = [el for el in card_json["body"]["elements"] if el.get("tag") == "collapsible_panel"]
    assert len(panels) == 3
    action_rows = [el for el in card_json["body"]["elements"] if el.get("tag") == "column_set"]
    assert action_rows
    assert action_rows[0]["columns"][0]["elements"][0]["value"]["action"] == "open_week_doc"


def test_session_reminder_card_has_followup_actions():
    ch = _make_channel()
    envelope = MessageEnvelope(
        plain_text="demo",
        card_type="session_reminder",
        card_document=CardDocument(
            title="中午接棒提醒",
            subtitle="项目延期说明",
            metadata={"chat_id": "oc_test", "biz_date": "2026-04-13"},
            sections=[CardSection(title="现在该做什么", lines=["A：还没看到今天第一棒。"])],
        ),
    )

    card_json = ch._render_envelope_card(envelope)
    _assert_valid_json2(card_json)
    action_rows = [el for el in card_json["body"]["elements"] if el.get("tag") == "column_set"]
    assert action_rows
    labels = [col["elements"][0]["text"]["content"] for col in action_rows[0]["columns"]]
    assert labels == ["今晚再提醒我", "查看本周文档"]
