from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from PIL import Image, ImageDraw, ImageFont

from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.settings.runtime import RuntimeConfigService


@dataclass(slots=True)
class _Line:
    text: str
    role: str


@dataclass(slots=True)
class DeliveryResult:
    delivery_mode: str
    image_paths: list[str]


class PlainTextRenderer:
    def render(self, envelope: MessageEnvelope, *, mention_qq: str | None = None) -> str:
        text = envelope.delivery_text()
        if mention_qq:
            return f"[CQ:at,qq={mention_qq}]\n{text}"
        return text


class ImageCardRenderer:
    def __init__(self, *, output_dir: Path, width: int = 1080, height: int = 1520) -> None:
        self._output_dir = output_dir
        self._width = width
        self._height = height
        self._padding_x = 72
        self._padding_y = 56
        self._header_height = 220
        self._body_top = self._padding_y + self._header_height + 28
        self._body_bottom = self._height - 72
        self._fonts = {
            "title": self._load_font(size=50, bold=True),
            "subtitle": self._load_font(size=28),
            "section": self._load_font(size=32, bold=True),
            "body": self._load_font(size=26),
            "footer": self._load_font(size=24),
            "page": self._load_font(size=22),
        }

    def render_document(self, document: CardDocument) -> list[Path]:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_old_files()
        lines = self._build_lines(document)
        pages = self._paginate(lines)
        rendered: list[Path] = []
        for index, page_lines in enumerate(pages, start=1):
            path = self._output_dir / f"card-{uuid4().hex}-{index}.png"
            self._render_page(path=path, document=document, page_lines=page_lines, page_no=index, page_count=len(pages))
            rendered.append(path)
        return rendered

    def _build_lines(self, document: CardDocument) -> list[_Line]:
        lines: list[_Line] = []
        if document.subtitle:
            lines.extend(self._wrap_lines(document.subtitle, role="subtitle"))
            lines.append(_Line("", "space"))
        for section in document.sections:
            lines.extend(self._build_section_lines(section))
        if document.footer_lines:
            lines.append(_Line("", "space"))
            lines.append(_Line("操作提示", "section"))
            for line in document.footer_lines:
                lines.extend(self._wrap_lines(line, role="footer"))
        while lines and lines[-1].role == "space":
            lines.pop()
        return lines

    def _build_section_lines(self, section: CardSection) -> list[_Line]:
        result: list[_Line] = []
        if section.title:
            result.append(_Line(section.title, "section"))
        for line in section.lines:
            result.extend(self._wrap_lines(line, role="body"))
        result.append(_Line("", "space"))
        return result

    def _paginate(self, lines: list[_Line]) -> list[list[_Line]]:
        available_height = self._body_bottom - self._body_top
        pages: list[list[_Line]] = []
        current: list[_Line] = []
        current_height = 0
        for line in lines:
            line_height = self._line_height(line.role)
            if current and current_height + line_height > available_height:
                pages.append(current)
                current = []
                current_height = 0
            current.append(line)
            current_height += line_height
        if current:
            pages.append(current)
        return pages or [[_Line("暂无内容", "body")]]

    def _render_page(
        self,
        *,
        path: Path,
        document: CardDocument,
        page_lines: list[_Line],
        page_no: int,
        page_count: int,
    ) -> None:
        image = Image.new("RGB", (self._width, self._height), self._background_color(document.theme))
        draw = ImageDraw.Draw(image)

        header_box = (36, 32, self._width - 36, 32 + self._header_height)
        body_box = (36, self._padding_y + self._header_height, self._width - 36, self._height - 36)
        draw.rounded_rectangle(body_box, radius=30, fill="#FFFFFF")
        draw.rounded_rectangle(header_box, radius=30, fill=self._header_color(document.theme))

        draw.text(
            (self._padding_x, self._padding_y + 32),
            document.title,
            font=self._fonts["title"],
            fill="#FFFFFF",
        )
        if document.subtitle:
            draw.text(
                (self._padding_x, self._padding_y + 112),
                document.subtitle,
                font=self._fonts["subtitle"],
                fill="#DDE7FF",
            )
        if page_count > 1:
            page_label = f"{page_no}/{page_count}"
            bbox = draw.textbbox((0, 0), page_label, font=self._fonts["page"])
            draw.text(
                (self._width - self._padding_x - (bbox[2] - bbox[0]), self._padding_y + 40),
                page_label,
                font=self._fonts["page"],
                fill="#DDE7FF",
            )

        y = self._body_top
        for line in page_lines:
            if line.role == "space":
                y += self._line_height("space")
                continue
            font = self._fonts["body"]
            fill = "#1F2A44"
            if line.role == "section":
                font = self._fonts["section"]
                fill = "#1B4DCC"
            elif line.role == "subtitle":
                font = self._fonts["subtitle"]
                fill = "#405271"
            elif line.role == "footer":
                font = self._fonts["footer"]
                fill = "#5B6782"
            draw.text((self._padding_x, y), line.text, font=font, fill=fill)
            y += self._line_height(line.role)

        image.save(path, format="PNG")

    def _wrap_lines(self, text: str, *, role: str) -> list[_Line]:
        if not text:
            return []
        paragraphs = str(text).splitlines() or [text]
        wrapped: list[_Line] = []
        for paragraph in paragraphs:
            if not paragraph.strip():
                wrapped.append(_Line("", "space"))
                continue
            for chunk in self._wrap_text(paragraph.strip(), font=self._font_for_role(role)):
                wrapped.append(_Line(chunk, role))
        return wrapped

    def _wrap_text(self, text: str, *, font) -> list[str]:
        max_width = self._width - self._padding_x * 2
        image = Image.new("RGB", (10, 10))
        draw = ImageDraw.Draw(image)
        lines: list[str] = []
        current = ""
        for char in text:
            candidate = current + char
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if current and (bbox[2] - bbox[0]) > max_width:
                lines.append(current.rstrip())
                current = char.lstrip()
            else:
                current = candidate
        if current:
            lines.append(current.rstrip())
        return lines or [text]

    def _line_height(self, role: str) -> int:
        mapping = {
            "title": 64,
            "subtitle": 42,
            "section": 48,
            "body": 40,
            "footer": 36,
            "page": 28,
            "space": 18,
        }
        return mapping.get(role, 40)

    def _font_for_role(self, role: str):
        if role == "section":
            return self._fonts["section"]
        if role == "subtitle":
            return self._fonts["subtitle"]
        if role == "footer":
            return self._fonts["footer"]
        return self._fonts["body"]

    def _load_font(self, *, size: int, bold: bool = False):
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for candidate in candidates:
            path = Path(candidate)
            if not path.exists():
                continue
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _background_color(self, theme: str) -> str:
        return {
            "blue": "#EFF4FF",
            "green": "#EDF8F1",
            "amber": "#FFF7E8",
        }.get(theme, "#EFF4FF")

    def _header_color(self, theme: str) -> str:
        return {
            "blue": "#163D91",
            "green": "#18634B",
            "amber": "#A05A00",
        }.get(theme, "#163D91")

    def _cleanup_old_files(self) -> None:
        files = sorted(self._output_dir.glob("card-*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in files[200:]:
            stale.unlink(missing_ok=True)

    def image_data_uri(self, image_path: Path) -> str:
        return "base64://" + base64.b64encode(image_path.read_bytes()).decode("ascii")


class MessageDeliveryService:
    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService,
        plain_text_renderer: PlainTextRenderer,
        image_card_renderer: ImageCardRenderer,
    ) -> None:
        self._runtime_config = runtime_config
        self._plain_text_renderer = plain_text_renderer
        self._image_card_renderer = image_card_renderer

    def can_send_card(self, envelope: MessageEnvelope) -> bool:
        return (
            self._runtime_config.render_mode() != "text"
            and self._runtime_config.enable_task_cards()
            and envelope.card_document is not None
        )

    async def send_group_envelope(
        self,
        *,
        bots: list,
        group_id: str,
        envelope: MessageEnvelope,
        mention_qq: str | None = None,
    ) -> DeliveryResult:
        if self.can_send_card(envelope):
            try:
                pages = self._image_card_renderer.render_document(envelope.card_document)
                if len(pages) == 1:
                    await self._send_single_image(
                        bots=bots,
                        group_id=group_id,
                        image_path=pages[0],
                        mention_qq=mention_qq,
                    )
                    return DeliveryResult(
                        delivery_mode="image_single",
                        image_paths=[str(pages[0])],
                    )
                else:
                    await self._send_multi_page_card(
                        bots=bots,
                        group_id=group_id,
                        image_paths=pages,
                        title=envelope.card_document.title,
                        mention_qq=mention_qq,
                    )
                    return DeliveryResult(
                        delivery_mode="image_multi_page",
                        image_paths=[str(page) for page in pages],
                    )
            except Exception:
                if not self._runtime_config.card_fallback_to_text():
                    raise
        text_message = self._plain_text_renderer.render(envelope, mention_qq=mention_qq)
        await self._send_message(bots=bots, group_id=group_id, message=text_message)
        return DeliveryResult(delivery_mode="text", image_paths=[])

    async def reply_group_envelope(
        self,
        *,
        bot,
        group_id: str,
        envelope: MessageEnvelope,
        mention_qq: str | None = None,
    ) -> DeliveryResult:
        return await self.send_group_envelope(
            bots=[bot],
            group_id=group_id,
            envelope=envelope,
            mention_qq=mention_qq,
        )

    async def _send_single_image(self, *, bots: list, group_id: str, image_path: Path, mention_qq: str | None) -> None:
        message = Message()
        if mention_qq:
            message += MessageSegment.at(int(mention_qq))
            message += MessageSegment.text("\n")
        message += MessageSegment.image(self._image_card_renderer.image_data_uri(image_path))
        await self._send_message(bots=bots, group_id=group_id, message=message)

    async def _send_multi_page_card(
        self,
        *,
        bots: list,
        group_id: str,
        image_paths: list[Path],
        title: str,
        mention_qq: str | None,
    ) -> None:
        if mention_qq:
            text = f"[CQ:at,qq={mention_qq}]\n你的内容较长，以下为分页卡片。"
            await self._send_message(bots=bots, group_id=group_id, message=text)
        try:
            await self._send_forward_images(bots=bots, group_id=group_id, title=title, image_paths=image_paths)
            return
        except Exception:
            for image_path in image_paths:
                await self._send_single_image(
                    bots=bots,
                    group_id=group_id,
                    image_path=image_path,
                    mention_qq=None,
                )

    async def _send_forward_images(self, *, bots: list, group_id: str, title: str, image_paths: list[Path]) -> None:
        last_error: Exception | None = None
        for bot in bots:
            try:
                nodes = []
                bot_name = "英语学习机器人"
                bot_uin = str(getattr(bot, "self_id", "0"))
                for index, image_path in enumerate(image_paths, start=1):
                    content = [
                        {"type": "text", "data": {"text": f"{title}（第 {index} 页）\n"}},
                        {"type": "image", "data": {"file": self._image_card_renderer.image_data_uri(image_path)}},
                    ]
                    nodes.append(
                        {
                            "type": "node",
                            "data": {
                                "name": bot_name,
                                "uin": bot_uin,
                                "content": content,
                            },
                        }
                    )
                await bot.call_api("send_group_forward_msg", group_id=int(group_id), messages=nodes)
                return
            except Exception as exc:  # pragma: no cover - live integration path
                last_error = exc
        if last_error is not None:
            raise last_error

    async def _send_message(self, *, bots: list, group_id: str, message) -> None:
        last_error: Exception | None = None
        for bot in bots:
            try:
                await bot.send_group_msg(group_id=int(group_id), message=message)
                return
            except Exception as exc:  # pragma: no cover - only used in live integrations
                last_error = exc
        if last_error is not None:
            raise last_error
