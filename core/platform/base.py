"""音乐平台基类"""

from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List, Optional

import httpx

from nekro_agent.api import core

from ..model import Platform, Song

logger = core.logger


class BaseMusicPlayer(ABC):
    """音乐平台基类，封装搜索与 HTTP 请求"""

    _registry: ClassVar[List[type["BaseMusicPlayer"]]] = []

    platform: ClassVar[Platform]

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy or None
        self._client: Optional[httpx.AsyncClient] = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if ABC not in cls.__bases__:
            BaseMusicPlayer._registry.append(cls)

    @classmethod
    def get_all_subclass(cls) -> List[type["BaseMusicPlayer"]]:
        return cls._registry

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(20.0),
                headers=self.HEADERS,
                proxy=self.proxy,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # ---------- 子类实现 ----------

    @abstractmethod
    async def fetch_songs(self, keyword: str, limit: int, extra: Optional[str] = None) -> List[Song]:
        """搜索歌曲"""

    # ---------- 可选覆写 ----------

    async def fetch_extra(self, song: Song) -> Song:
        """补齐音频直链；默认不改动"""
        return song

    async def fetch_covers(self, songs: List[Song]) -> Dict[str, str]:
        """批量补齐封面，返回 {歌曲 id: 封面 url}"""
        return {s.id: s.cover_url for s in songs if s.cover_url}

    async def fetch_comments(self, song: Song) -> Song:
        """获取热门评论；默认无"""
        return song

    async def fetch_lyrics(self, song: Song) -> Song:
        """获取歌词；默认无"""
        return song

    # ---------- 请求工具 ----------

    async def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: Optional[dict] = None,
        json_body: Optional[dict] = None,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
    ):
        try:
            response = await self.client.request(
                method.upper(),
                url,
                data=data,
                json=json_body,
                headers=headers,
                params=params,
            )
        except Exception as e:
            logger.warning(f"[{self.platform.name}] 请求失败 {url}: {type(e).__name__} {e}")
            return None

        if response.status_code != 200:
            logger.warning(f"[{self.platform.name}] HTTP {response.status_code}: {url}")
            return None

        text = response.text.strip()
        if not text:
            logger.warning(f"[{self.platform.name}] 响应为空: {url}")
            return None
        try:
            return response.json()
        except ValueError:
            return text


__all__ = ["BaseMusicPlayer"]
