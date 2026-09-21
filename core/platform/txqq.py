"""txqq 聚合音源（QQ音乐 / 酷狗 / 酷我 / 百度 / 咪咕 / 荔枝 / 一听 / 蜻蜓 等）"""

from typing import ClassVar, List, Optional

from nekro_agent.api import core

from ..model import Platform, Song
from .base import BaseMusicPlayer

logger = core.logger


class TXQQMusic(BaseMusicPlayer):
    """music.txqq.pro 聚合接口，搜索结果自带音频直链、封面与歌词"""

    platform: ClassVar[Platform] = Platform(
        name="txqq",
        display_name="聚合音源",
        keywords=[
            "QQ点歌",
            "酷狗点歌",
            "酷我点歌",
            "百度点歌",
            "一听点歌",
            "咪咕点歌",
            "荔枝点歌",
            "蜻蜓点歌",
            "喜马点歌",
        ],
    )

    BASE_URL = "https://music.txqq.pro/"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://music.txqq.pro",
        "Referer": "https://music.txqq.pro",
    }

    # 命令关键词 -> 聚合接口的 type 参数
    PLATFORM_MAP = {
        "qq": ["qq"],
        "kugou": ["酷狗"],
        "kuwo": ["酷我"],
        "baidu": ["百度"],
        "1ting": ["一听"],
        "migu": ["咪咕"],
        "lizhi": ["荔枝"],
        "qingting": ["蜻蜓"],
        "ximalaya": ["喜马"],
        "5singyc": ["5sing原创"],
        "5singfc": ["5sing翻唱"],
        "kg": ["全民"],
    }

    async def fetch_songs(self, keyword: str, limit: int = 5, extra: Optional[str] = None) -> List[Song]:
        source = self._detect_platform(extra) if extra else "qq"
        result = await self._request(
            self.BASE_URL,
            method="POST",
            data={"input": keyword, "filter": "name", "type": source, "page": 1},
            headers=self.HEADERS,
        )
        data = (result or {}).get("data") if isinstance(result, dict) else None
        if not isinstance(data, list) or not data:
            logger.warning(f"[txqq:{source}] 搜索无结果: {keyword}")
            return []

        songs: List[Song] = []
        for item in data[:limit]:
            songs.append(
                Song(
                    id=str(item.get("songid") or ""),
                    source=source,
                    name=item.get("title"),
                    artists=item.get("author"),
                    audio_url=item.get("url") or None,
                    cover_url=item.get("pic") or None,
                    lyrics=item.get("lrc") or None,
                    note=item.get("link") or None,
                )
            )
        return songs

    async def fetch_extra(self, song: Song) -> Song:
        """txqq 的搜索结果通常已带直链，缺失时用同名词重新取一次"""
        if song.audio_url:
            return song
        candidates = await self.fetch_songs(song.name or "", limit=1, extra=song.source)
        if candidates and candidates[0].audio_url:
            song.audio_url = candidates[0].audio_url
            if not song.cover_url:
                song.cover_url = candidates[0].cover_url
        return song

    def _detect_platform(self, keyword: str) -> str:
        raw = keyword.lower()
        for source, keys in self.PLATFORM_MAP.items():
            for key in keys:
                if key.lower() in raw:
                    return source
        return "qq"


__all__ = ["TXQQMusic"]
