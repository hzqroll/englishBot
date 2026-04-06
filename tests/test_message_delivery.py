from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.messaging.renderers import ImageCardRenderer, MessageDeliveryService, PlainTextRenderer


class _RuntimeConfigStub:
    def __init__(self, *, render_mode: str, fallback: bool = True) -> None:
        self._render_mode = render_mode
        self._fallback = fallback

    def render_mode(self) -> str:
        return self._render_mode

    def enable_task_cards(self) -> bool:
        return True

    def card_fallback_to_text(self) -> bool:
        return self._fallback


class _ImageRendererStub:
    def __init__(self, *, pages: list[Path] | None = None, fail: bool = False) -> None:
        self._pages = pages or [Path("/tmp/demo-card.png")]
        self._fail = fail

    def render_document(self, document) -> list[Path]:
        if self._fail:
            raise RuntimeError("render failed")
        return self._pages

    def image_data_uri(self, image_path: Path) -> str:
        return "base64://ZmFrZS1pbWFnZQ=="


class _BotStub:
    def __init__(self, *, fail_image_once: bool = False, fail_forward: bool = False) -> None:
        self.messages: list[str] = []
        self.forward_calls: list[dict] = []
        self._fail_image_once = fail_image_once
        self._fail_forward = fail_forward
        self.self_id = "1256735256"

    async def send_group_msg(self, *, group_id: int, message) -> None:
        rendered = str(message)
        if self._fail_image_once and "CQ:image" in rendered:
            self._fail_image_once = False
            raise RuntimeError("image send failed")
        self.messages.append(rendered)

    async def call_api(self, action: str, **params):
        if self._fail_forward:
            raise RuntimeError("forward failed")
        self.forward_calls.append({"action": action, "params": params})


def _document() -> CardDocument:
    return CardDocument(
        title="今日任务",
        subtitle="共 3 个任务",
        sections=[CardSection(title="任务 1", lines=["用英语描述今天的天气。"])],
    )


@pytest.mark.asyncio
async def test_message_delivery_falls_back_to_text_when_rendering_disabled() -> None:
    service = MessageDeliveryService(
        runtime_config=_RuntimeConfigStub(render_mode="text"),
        plain_text_renderer=PlainTextRenderer(),
        image_card_renderer=_ImageRendererStub(),
    )
    envelope = MessageEnvelope(
        plain_text="今日任务文本",
        card_document=_document(),
    )
    bot = _BotStub()

    result = await service.send_group_envelope(bots=[bot], group_id="123", envelope=envelope)

    assert bot.messages == ["今日任务文本"]
    assert result.delivery_mode == "text"


@pytest.mark.asyncio
async def test_message_delivery_sends_single_image_card() -> None:
    service = MessageDeliveryService(
        runtime_config=_RuntimeConfigStub(render_mode="image_card"),
        plain_text_renderer=PlainTextRenderer(),
        image_card_renderer=_ImageRendererStub(pages=[Path("/tmp/single.png")]),
    )
    envelope = MessageEnvelope(
        plain_text="fallback",
        card_document=_document(),
    )
    bot = _BotStub()

    result = await service.send_group_envelope(bots=[bot], group_id="123", envelope=envelope, mention_qq="456")

    assert len(bot.messages) == 1
    assert "CQ:image" in bot.messages[0]
    assert "CQ:at,qq=456" in bot.messages[0]
    assert result.delivery_mode == "image_single"
    assert result.image_paths == ["/tmp/single.png"]


@pytest.mark.asyncio
async def test_message_delivery_uses_forward_for_multi_page_cards() -> None:
    service = MessageDeliveryService(
        runtime_config=_RuntimeConfigStub(render_mode="image_card"),
        plain_text_renderer=PlainTextRenderer(),
        image_card_renderer=_ImageRendererStub(
            pages=[Path("/tmp/page1.png"), Path("/tmp/page2.png")]
        ),
    )
    envelope = MessageEnvelope(
        plain_text="fallback",
        card_document=_document(),
    )
    bot = _BotStub()

    result = await service.send_group_envelope(bots=[bot], group_id="123", envelope=envelope, mention_qq="456")

    assert bot.messages[0].startswith("[CQ:at,qq=456]")
    assert len(bot.forward_calls) == 1
    assert bot.forward_calls[0]["action"] == "send_group_forward_msg"
    assert result.delivery_mode == "image_multi_page"


@pytest.mark.asyncio
async def test_message_delivery_falls_back_after_image_failure() -> None:
    service = MessageDeliveryService(
        runtime_config=_RuntimeConfigStub(render_mode="image_card"),
        plain_text_renderer=PlainTextRenderer(),
        image_card_renderer=_ImageRendererStub(pages=[Path("/tmp/single.png")]),
    )
    envelope = MessageEnvelope(
        plain_text="plain",
        fallback_text="fallback text",
        card_document=_document(),
    )
    bot = _BotStub(fail_image_once=True)

    result = await service.send_group_envelope(bots=[bot], group_id="123", envelope=envelope)

    assert bot.messages == ["fallback text"]
    assert result.delivery_mode == "text"


def test_image_card_renderer_creates_png_files(tmp_path: Path) -> None:
    renderer = ImageCardRenderer(output_dir=tmp_path)

    pages = renderer.render_document(
        CardDocument(
            title="周报",
            subtitle="学习 3 天，完成率 80%",
            sections=[
                CardSection(title="本周概览", lines=["学习天数：3 天", "完成率：80%", "累计积分：28"]),
                CardSection(title="薄弱点", lines=["介词", "表达自然度"]),
            ],
        )
    )

    assert pages
    assert pages[0].suffix == ".png"
    assert pages[0].exists()
