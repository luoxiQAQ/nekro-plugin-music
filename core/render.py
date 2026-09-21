"""候选歌曲卡片图与歌词图渲染"""

import asyncio
import html
import io
import re
from typing import Dict, List

from PIL import Image, ImageDraw, ImageFont

from nekro_agent.api import core

from .model import Song

logger = core.logger

_TAG_RE = re.compile(r"<[^>]+>")
_LRC_TIME_RE = re.compile(r"\[\d{2}:\d{2}(?:[.:]\d{2,3})?\]")


class CardTheme:
    """候选卡片样式"""

    card_width = 220
    card_height = 278
    thumb_height = 220
    margin = 16
    corner_radius = 10
    font_size = 16
    card_bg = "#ffffff"
    canvas_bg = "#f5f5f5"
    title_color = "#000000"
    sub_text_color = "#666666"
    overlay_text_color = "#ffffff"
    gradient_height = 40
    gradient_max_alpha = 180


class LyricsTheme:
    """歌词图样式"""

    image_width = 1000
    font_size = 30
    line_spacing = 20
    horizontal_padding = 80
    vertical_padding = 50
    top_color = (255, 250, 240)
    bottom_color = (235, 255, 247)
    text_color = (70, 70, 70)


def strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


class MusicRenderer:
    def __init__(self, font_path: str, columns: int = 3):
        self.font_path = font_path
        self.columns = max(1, columns)
        self.card_theme = CardTheme()
        self.lyrics_theme = LyricsTheme()
        self._card_font = ImageFont.truetype(font_path, self.card_theme.font_size)
        self._lyrics_font = ImageFont.truetype(font_path, self.lyrics_theme.font_size)

    # ---------- 候选列表 ----------

    async def render_song_list(self, songs: List[Song], covers: Dict[str, bytes]) -> bytes:
        return await asyncio.to_thread(self._render_list_sync, songs, covers)

    def _render_list_sync(self, songs: List[Song], covers: Dict[str, bytes]) -> bytes:
        cards = [
            self._render_card(song, index, covers.get(song.id))
            for index, song in enumerate(songs, 1)
        ]
        return self._compose_grid(cards)

    def _render_card(self, song: Song, index: int, cover: bytes | None) -> Image.Image:
        theme = self.card_theme
        card = Image.new("RGBA", (theme.card_width, theme.card_height), theme.card_bg)
        draw = ImageDraw.Draw(card)

        thumb = None
        if cover:
            try:
                thumb = Image.open(io.BytesIO(cover)).convert("RGB")
            except Exception as e:
                logger.warning(f"封面解析失败: {type(e).__name__}")
        if thumb is None:
            thumb = Image.new("RGB", (theme.card_width, theme.thumb_height), "#e5e5e5")
        card.paste(thumb.resize((theme.card_width, theme.thumb_height)), (0, 0))

        alpha = Image.new("L", (theme.card_width, theme.gradient_height), 0)
        alpha_draw = ImageDraw.Draw(alpha)
        for y in range(theme.gradient_height):
            alpha_draw.line(
                [(0, y), (theme.card_width, y)],
                fill=int(theme.gradient_max_alpha * (y / theme.gradient_height)),
            )
        overlay = Image.new("RGBA", (theme.card_width, theme.gradient_height), (0, 0, 0, 255))
        overlay.putalpha(alpha)
        card.paste(overlay, (0, theme.thumb_height - theme.gradient_height), overlay)

        draw.text(
            (8, theme.thumb_height - 24),
            song.duration_text(),
            font=self._card_font,
            fill=theme.overlay_text_color,
        )

        title = strip_html(song.name or "")
        if len(title) > 36:
            title = f"{title[:18]}\n{title[18:36]}..."
        elif len(title) > 18:
            title = f"{title[:18]}\n{title[18:]}"
        draw.text((8, theme.thumb_height + 8), title, font=self._card_font, fill=theme.title_color)

        author = strip_html(song.artists or "") or "-"
        draw.text(
            (8, theme.card_height - 30),
            author if len(author) <= 13 else f"{author[:13]}…",
            font=self._card_font,
            fill=theme.sub_text_color,
        )
        draw.text(
            (theme.card_width - 20, theme.card_height - 25),
            str(index),
            font=self._card_font,
            fill=theme.sub_text_color,
        )

        mask = Image.new("L", (theme.card_width, theme.card_height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, theme.card_width, theme.card_height),
            radius=theme.corner_radius,
            fill=255,
        )
        card.putalpha(mask)
        return card

    def _compose_grid(self, cards: List[Image.Image]) -> bytes:
        theme = self.card_theme
        per_row = self.columns
        rows: List[Image.Image] = []
        for start in range(0, len(cards), per_row):
            row_cards = cards[start : start + per_row]
            row_width = theme.margin + len(row_cards) * (theme.card_width + theme.margin)
            row_img = Image.new(
                "RGBA",
                (row_width, theme.card_height + 2 * theme.margin),
                theme.canvas_bg,
            )
            for offset, card in enumerate(row_cards):
                x = theme.margin + offset * (theme.card_width + theme.margin)
                row_img.paste(card, (x, theme.margin), card)
            rows.append(row_img)

        total_height = sum(row.height for row in rows)
        canvas = Image.new("RGBA", (rows[0].width, total_height), theme.canvas_bg)
        offset_y = 0
        for row in rows:
            canvas.paste(row, (0, offset_y), row)
            offset_y += row.height

        final = Image.new("RGB", canvas.size, theme.canvas_bg)
        final.paste(canvas, mask=canvas.split()[3])
        buffer = io.BytesIO()
        final.save(buffer, format="JPEG", quality=82)
        return buffer.getvalue()

    # ---------- 歌词 ----------

    async def render_lyrics(self, lyrics: str) -> bytes:
        return await asyncio.to_thread(self._render_lyrics_sync, lyrics)

    def _render_lyrics_sync(self, lyrics: str) -> bytes:
        theme = self.lyrics_theme
        lines = [_LRC_TIME_RE.sub("", line).strip() for line in lyrics.splitlines()]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        if not lines:
            lines = ["（纯音乐，请欣赏）"]

        probe = Image.new("RGB", (theme.image_width, 1))
        probe_draw = ImageDraw.Draw(probe)
        heights = []
        max_width = 0
        for line in lines:
            bbox = probe_draw.textbbox((0, 0), line or "　", font=self._lyrics_font)
            heights.append(bbox[3] - bbox[1])
            max_width = max(max_width, bbox[2] - bbox[0])

        width = int(max(theme.image_width, max_width + theme.horizontal_padding * 2))
        height = int(
            sum(heights) + theme.line_spacing * (len(lines) - 1) + theme.vertical_padding * 2
        )

        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        for y in range(height):
            ratio = y / height
            color = tuple(
                int(top * (1 - ratio) + bottom * ratio)
                for top, bottom in zip(theme.top_color, theme.bottom_color)
            )
            draw.line([(0, y), (width, y)], fill=color)

        y = theme.vertical_padding
        for line, line_height in zip(lines, heights):
            bbox = draw.textbbox((0, 0), line or "　", font=self._lyrics_font)
            draw.text(
                ((width - (bbox[2] - bbox[0])) / 2, y - bbox[1]),
                line or "　",
                font=self._lyrics_font,
                fill=theme.text_color,
            )
            y += line_height + theme.line_spacing

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()


__all__ = ["MusicRenderer", "strip_html"]
