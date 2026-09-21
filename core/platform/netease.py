"""网易云音乐（NodeJS API）"""

from typing import ClassVar, Dict, List, Optional

from nekro_agent.api import core

from ..model import Platform, Song
from .base import BaseMusicPlayer

logger = core.logger


class NetEaseMusic(BaseMusicPlayer):
    """网易云音乐，走 NodeJS API（/search /song/url /song/detail /lyric /comment/hot）"""

    platform: ClassVar[Platform] = Platform(
        name="netease",
        display_name="网易云音乐",
        keywords=["网易点歌", "网易nj", "nj点歌", "网易云"],
    )

    def __init__(self, base_url: str, proxy: Optional[str] = None):
        super().__init__(proxy)
        self.base_url = base_url.rstrip("/")

    async def fetch_songs(self, keyword: str, limit: int = 5, extra: Optional[str] = None) -> List[Song]:
        result = await self._request(
            f"{self.base_url}/search",
            method="POST",
            json_body={"keywords": keyword, "limit": limit, "type": 1, "offset": 0},
        )
        raw = ((result or {}).get("result") or {}).get("songs") if isinstance(result, dict) else None
        if not raw:
            logger.warning(f"[netease] 搜索无结果或响应异常: {keyword}")
            return []

        return [
            Song(
                id=str(item.get("id")),
                source="netease",
                name=item.get("name"),
                artists="、".join(a.get("name", "") for a in item.get("artists") or []),
                duration=item.get("duration"),
            )
            for item in raw[:limit]
        ]

    async def fetch_covers(self, songs: List[Song]) -> Dict[str, str]:
        ids = [s.id for s in songs if s.id]
        if not ids:
            return {}
        result = await self._request(f"{self.base_url}/song/detail", params={"ids": ",".join(ids)})
        details = (result or {}).get("songs") if isinstance(result, dict) else None
        if not details:
            return {}

        covers: Dict[str, str] = {}
        for item in details:
            cover = (item.get("al") or {}).get("picUrl")
            if cover:
                covers[str(item.get("id"))] = cover
        return covers

    async def fetch_extra(self, song: Song) -> Song:
        result = await self._request(f"{self.base_url}/song/url", params={"id": song.id})
        data = (result or {}).get("data") if isinstance(result, dict) else None
        if data:
            url = data[0].get("url")
            if url:
                song.audio_url = url

        if not song.cover_url:
            result = await self._request(f"{self.base_url}/song/detail", params={"ids": song.id})
            details = (result or {}).get("songs") if isinstance(result, dict) else None
            if details:
                song.cover_url = (details[0].get("al") or {}).get("picUrl")
        return song

    async def fetch_comments(self, song: Song) -> Song:
        if song.comments:
            return song
        result = await self._request(f"{self.base_url}/comment/hot", params={"id": song.id, "type": 0})
        if isinstance(result, dict):
            comments = result.get("hotComments")
            if comments:
                song.comments = comments
        return song

    async def fetch_lyrics(self, song: Song) -> Song:
        if song.lyrics:
            return song
        result = await self._request(f"{self.base_url}/lyric", params={"id": song.id})
        if isinstance(result, dict):
            lyric = (result.get("lrc") or {}).get("lyric")
            if lyric:
                song.lyrics = lyric
        return song


__all__ = ["NetEaseMusic"]
