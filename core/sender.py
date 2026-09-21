"""歌曲发送

七种发送方式按配置顺序级联，任一失败自动降级到下一种：
card / ark_card / record_link / record_local / file_link / file_local / text

nekro 自身只有文本 / 图片 / 文件三种消息段，语音与音乐卡片经 OneBot API 补上。
"""

import asyncio
import random
from pathlib import Path
from typing import List, Optional

from nekro_agent.api import message
from nekro_agent.api.schemas import AgentCtx

from ..plugin import SEND_MODE_MAP, config, plugin
from . import onebot
from .files import MusicDownloader
from .model import Song
from .platform.base import BaseMusicPlayer
from .platform.txqq import TXQQMusic
from .render import MusicRenderer

logger = plugin.logger

ALL_MODES = list(SEND_MODE_MAP.values())

_ARK_FORMAT_MAP = {
    "qq": "qq",
    "txqq": "qq",
    "netease": "netease",
    "netease_nodejs": "netease",
    "kugou": "kugou",
    "bilibili": "bilibili",
}


class _SignCardClient:
    """签名音乐卡片（ark_card）"""

    def __init__(self) -> None:
        self._client = None

    @property
    def client(self):
        if self._client is None or self._client.is_closed:
            import httpx

            self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def fetch(self, player: BaseMusicPlayer, song: Song) -> Optional[dict]:
        if not config.SIGN_API_URL or not config.SIGN_API_KEY:
            return None
        if not song.audio_url or not song.cover_url:
            return None

        source = (song.source or player.platform.name).lower()
        card_format = _ARK_FORMAT_MAP.get(source)
        if card_format is None:
            logger.debug(f"签名卡片不支持音源 {source}，跳过")
            return None

        params = {
            "key": config.SIGN_API_KEY,
            "url": song.audio_url,
            "song": song.name or "",
            "singer": song.artists or "未知歌手",
            "cover": song.cover_url,
            "jump": song.audio_url,
            "format": card_format,
        }
        try:
            response = await self.client.get(config.SIGN_API_URL, params=params)
            response.raise_for_status()
            result = response.json()
        except Exception as e:
            logger.warning(f"签名卡片请求失败: {type(e).__name__} {e}")
            return None

        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(result, dict) or result.get("code") != 200 or not isinstance(data, dict):
            logger.warning("签名卡片返回内容异常")
            return None
        if not {"app", "meta", "prompt", "view"}.issubset(data):
            logger.warning("签名卡片缺少必要字段")
            return None
        return data


class MusicSender:
    def __init__(self, renderer: MusicRenderer, downloader: MusicDownloader) -> None:
        self.renderer = renderer
        self.downloader = downloader
        self.ark = _SignCardClient()

    async def close(self) -> None:
        await self.ark.close()

    # ---------- 候选列表 ----------

    def selection_text(self, songs: List[Song], player: BaseMusicPlayer) -> str:
        lines = [f"【{player.platform.display_name}】给你找到了这些，回复序号选歌："]
        lines.extend(f"{index}. {song.label()}" for index, song in enumerate(songs, 1))
        return "\n".join(lines)

    async def render_selection(self, songs: List[Song], player: BaseMusicPlayer) -> Optional[Path]:
        """渲染候选卡片图并写到共享目录"""
        await asyncio.gather(
            *[
                player.fetch_extra(song)
                for song in songs
                if not song.cover_url or not song.audio_url
            ],
            return_exceptions=True,
        )

        cover_map = await player.fetch_covers(songs)
        results = await asyncio.gather(
            *[self.downloader.download_bytes(url) for url in cover_map.values()],
            return_exceptions=True,
        )
        covers = {
            song_id: data
            for song_id, data in zip(cover_map.keys(), results)
            if isinstance(data, bytes)
        }

        image = await self.renderer.render_song_list(songs, covers)
        if not image:
            return None
        return self.downloader.save_temp(image, f"selection_{len(songs)}.jpg")

    # ---------- 发送 ----------

    @staticmethod
    def _is_mode_supported(chat_key: str, mode: str) -> bool:
        if mode == "text":
            return True
        if mode not in ALL_MODES:
            return False
        return onebot.parse_chat_key(chat_key) is not None

    async def _prepare(self, player: BaseMusicPlayer, song: Song) -> Song:
        if not song.audio_url or not song.cover_url:
            song = await player.fetch_extra(song)
        return song

    async def _send_card(self, chat_key: str, ctx: AgentCtx, player: BaseMusicPlayer, song: Song) -> bool:
        if isinstance(player, TXQQMusic):
            # 聚合音源不在 QQ 曲库内，只能用自定义卡片
            await onebot.send_custom_music_card(
                chat_key,
                url=song.audio_url or "",
                audio=song.audio_url or "",
                title=song.name or "",
                image=song.cover_url or "",
                singer=song.artists or "",
            )
        else:
            await onebot.send_music_card(chat_key, "163", song.id)
        return True

    async def _send_ark_card(self, chat_key: str, ctx: AgentCtx, player: BaseMusicPlayer, song: Song) -> bool:
        card = await self.ark.fetch(player, song)
        if not card:
            return False
        await onebot.send_json_card(chat_key, card)
        return True

    async def _send_record_link(self, chat_key: str, ctx: AgentCtx, player: BaseMusicPlayer, song: Song) -> bool:
        if not song.audio_url:
            return False
        await onebot.send_record(chat_key, song.audio_url)
        return True

    async def _send_record_local(self, chat_key: str, ctx: AgentCtx, player: BaseMusicPlayer, song: Song) -> bool:
        if not song.audio_url:
            return False
        path = await self.downloader.download_audio(song.audio_url, audio=True)
        if not path:
            return False
        await onebot.send_record(chat_key, str(path))
        return True

    async def _send_file_link(self, chat_key: str, ctx: AgentCtx, player: BaseMusicPlayer, song: Song) -> bool:
        if not song.audio_url:
            return False
        await onebot.upload_file(chat_key, song.audio_url, f"{song.name}_{song.artists}.mp3")
        return True

    async def _send_file_local(self, chat_key: str, ctx: AgentCtx, player: BaseMusicPlayer, song: Song) -> bool:
        if not song.audio_url:
            return False
        path = await self.downloader.download_audio(song.audio_url, audio=False)
        if not path:
            return False
        await onebot.upload_file(chat_key, str(path), f"{song.name}_{song.artists}{path.suffix}")
        return True

    async def _send_text(self, chat_key: str, ctx: AgentCtx, player: BaseMusicPlayer, song: Song) -> bool:
        if not song.audio_url:
            return False
        await message.send_text(chat_key, f"《{song.label()}》\n{song.audio_url}", ctx, record=True)
        return True

    def _get_sender(self, mode: str):
        return {
            "card": self._send_card,
            "ark_card": self._send_ark_card,
            "record_link": self._send_record_link,
            "record_local": self._send_record_local,
            "file_link": self._send_file_link,
            "file_local": self._send_file_local,
            "text": self._send_text,
        }.get(mode)

    async def _notify(self, chat_key: str, ctx: AgentCtx, text: str) -> None:
        """提示消息发送失败不再向上抛，避免整个命令报错"""
        try:
            await message.send_text(chat_key, text, ctx)
        except Exception as e:
            logger.warning(f"[music] 提示消息发送失败: {type(e).__name__} {e}")

    async def send_song(
        self,
        chat_key: str,
        ctx: AgentCtx,
        player: BaseMusicPlayer,
        song: Song,
        modes: Optional[List[str]] = None,
        with_comment: bool = True,
    ) -> bool:
        """按配置顺序尝试发送，返回是否成功"""
        song = await self._prepare(player, song)
        if not song.audio_url:
            await self._notify(chat_key, ctx, f"《{song.name}》音频获取失败，换一首试试～")
            return False

        target_modes = modes or config.send_modes
        if not target_modes:
            await self._notify(chat_key, ctx, "没有可用的发送方式，检查下插件配置吧～")
            return False
        sent = False
        for mode in target_modes:
            if not self._is_mode_supported(chat_key, mode):
                logger.debug(f"[music] 发送方式 {mode} 在当前会话不可用，跳过")
                continue
            sender = self._get_sender(mode)
            if sender is None:
                logger.warning(f"[music] 未知发送方式: {mode}")
                continue
            try:
                if await sender(chat_key, ctx, player, song):
                    logger.info(f"[music] 已通过 {mode} 发送《{song.label()}》")
                    sent = True
                    break
            except Exception as e:
                logger.warning(f"[music] 发送方式 {mode} 异常: {type(e).__name__} {e}")

        if not sent:
            await self._notify(chat_key, ctx, "歌曲发送失败，请稍后再试～")
            return False

        await self.downloader.maybe_cleanup()

        if config.ENABLE_COMMENTS and with_comment:
            await self.send_comment(chat_key, ctx, player, song)
        if config.ENABLE_LYRICS:
            await self.send_lyrics(chat_key, ctx, player, song)
        return True

    async def _send_image(self, chat_key: str, ctx: AgentCtx, path: Path) -> bool:
        """发图。OneBot 会话直发，其余适配器回退到通用接口"""
        try:
            if onebot.parse_chat_key(chat_key):
                await onebot.send_image(chat_key, path)
            else:
                await message.send_image(chat_key, str(path), ctx, record=True)
            return True
        except Exception as e:
            logger.warning(f"[music] 图片发送失败: {type(e).__name__} {e}")
            return False

    async def send_comment(self, chat_key: str, ctx: AgentCtx, player: BaseMusicPlayer, song: Song) -> bool:
        """发一条热门评论"""
        if not song.comments:
            song = await player.fetch_comments(song)
        if not song.comments:
            return False
        contents = [c.get("content") for c in song.comments if isinstance(c, dict) and c.get("content")]
        if not contents:
            return False
        try:
            await message.send_text(chat_key, f"热评：{random.choice(contents)}", ctx, record=True)
            return True
        except Exception as e:
            logger.warning(f"[music] 评论发送失败: {type(e).__name__} {e}")
            return False

    async def send_lyrics(self, chat_key: str, ctx: AgentCtx, player: BaseMusicPlayer, song: Song) -> bool:
        """发歌词图片"""
        if not song.lyrics:
            song = await player.fetch_lyrics(song)
        if not song.lyrics:
            logger.warning(f"[music] 《{song.name}》歌词获取失败")
            return False
        try:
            image = await self.renderer.render_lyrics(song.lyrics)
            path = self.downloader.save_temp(image, f"lyrics_{song.id}.jpg")
            if not path:
                return False
            return await self._send_image(chat_key, ctx, path)
        except Exception as e:
            logger.warning(f"[music] 歌词图发送失败: {type(e).__name__} {e}")
            return False
