from __future__ import annotations

import pytest

from src.domain.value_objects.messaging import MessageEnvelope
from src.infrastructure.messaging.renderers import MessageDeliveryService, NapCatCardRenderer, PlainTextRenderer


class _RuntimeConfigStub:
    def __init__(self, *, render_mode: str, public_base_url: str, fallback: bool = True) -> None:
        self._render_mode = render_mode
        self._public_base_url = public_base_url
        self._fallback = fallback

    def render_mode(self) -> str:
        return self._render_mode

    def enable_task_cards(self) -> bool:
        return True

    def public_base_url(self) -> str:
        return self._public_base_url

    def card_fallback_to_text(self) -> bool:
        return self._fallback


class _BotStub:
    def __init__(self, *, fail_json_once: bool = False) -> None:
        self.messages: list[str] = []
        self._fail_json_once = fail_json_once

    async def send_group_msg(self, *, group_id: int, message) -> None:
        rendered = str(message)
        if self._fail_json_once and "CQ:json" in rendered:
            self._fail_json_once = False
            raise RuntimeError("json send failed")
        self.messages.append(rendered)


@pytest.mark.asyncio
async def test_message_delivery_falls_back_to_text_when_public_url_missing() -> None:
    service = MessageDeliveryService(
        runtime_config=_RuntimeConfigStub(render_mode="hybrid", public_base_url=""),
        plain_text_renderer=PlainTextRenderer(),
        napcat_card_renderer=NapCatCardRenderer(),
    )
    envelope = MessageEnvelope(
        plain_text="今日任务文本",
        card_payload={"demo": True},
    )
    bot = _BotStub()

    await service.send_group_envelope(bots=[bot], group_id="123", envelope=envelope)

    assert bot.messages == ["今日任务文本"]


@pytest.mark.asyncio
async def test_message_delivery_sends_card_when_enabled() -> None:
    renderer = NapCatCardRenderer()
    service = MessageDeliveryService(
        runtime_config=_RuntimeConfigStub(render_mode="hybrid", public_base_url="http://127.0.0.1:8080"),
        plain_text_renderer=PlainTextRenderer(),
        napcat_card_renderer=renderer,
    )
    envelope = MessageEnvelope(
        plain_text="fallback",
        card_payload=renderer.build_click_card(
            title="今日任务",
            summary="点击打开任务页",
            url="http://127.0.0.1:8080/learn/task/demo",
            action_label="打开任务页",
        ),
    )
    bot = _BotStub()

    await service.send_group_envelope(bots=[bot], group_id="123", envelope=envelope, mention_qq="456")

    assert len(bot.messages) == 1
    assert "CQ:json" in bot.messages[0]
    assert "CQ:at,qq=456" in bot.messages[0]


@pytest.mark.asyncio
async def test_message_delivery_falls_back_after_card_failure() -> None:
    renderer = NapCatCardRenderer()
    service = MessageDeliveryService(
        runtime_config=_RuntimeConfigStub(render_mode="hybrid", public_base_url="http://127.0.0.1:8080"),
        plain_text_renderer=PlainTextRenderer(),
        napcat_card_renderer=renderer,
    )
    envelope = MessageEnvelope(
        plain_text="plain",
        fallback_text="fallback text",
        card_payload=renderer.build_click_card(
            title="周报",
            summary="点击查看周报",
            url="http://127.0.0.1:8080/learn/report/demo",
            action_label="查看周报",
        ),
    )
    bot = _BotStub(fail_json_once=True)

    await service.send_group_envelope(bots=[bot], group_id="123", envelope=envelope)

    assert bot.messages == ["fallback text"]
