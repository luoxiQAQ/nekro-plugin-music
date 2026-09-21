"""文件与下载

音频必须落到 NapCat 也能读到的目录（两容器内绝对路径一致的 nbcache），
否则本地语音 / 本地文件两种发送方式无法读取。
"""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from nekro_agent.api import core

from .onebot import shared_dir, transcode_to_mp3

logger = core.logger

AUDIO_SUBDIR = "music/audio"
IMAGE_SUBDIR = "music/image"
CACHE_TTL = 6 * 3600

_AUDIO_EXTS = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".wma", ".ape", ".mp4", ".m4s")


def subdir(name: str) -> Path:
    """返回共享目录下的子目录（不存在则创建）"""
    path = shared_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ext_from(url: str, content_type: str = "") -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in _AUDIO_EXTS:
        return suffix
    mapping = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/aac": ".aac",
        "audio/flac": ".flac",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return mapping.get(content_type.split(";")[0].strip().lower(), "")


def _digest(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _cleanup(directory: Path) -> None:
    deadline = time.time() - CACHE_TTL
    for item in directory.glob("*"):
        try:
            if item.is_file() and item.stat().st_mtime < deadline:
                item.unlink()
        except OSError:
            continue


class MusicDownloader:
    """歌曲音频与封面下载"""

    def __init__(self, timeout: float = 60.0, proxy: Optional[str] = None):
        self.timeout = timeout
        self.proxy = proxy or None
        self._client: Optional[httpx.AsyncClient] = None
        self._cleaned_at = 0.0

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                proxy=self.proxy,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def download_bytes(self, url: str) -> Optional[bytes]:
        """下载封面等小文件到内存"""
        if not url:
            return None
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.warning(f"下载失败 {url[:80]}: {type(e).__name__} {e}")
            return None

    async def download_audio(self, url: str, audio: bool = True) -> Optional[Path]:
        """下载音频到共享目录，返回文件路径

        audio=True 时保证返回的是 mp3（语音消息对格式有要求）
        """
        if not url:
            return None

        directory = subdir(AUDIO_SUBDIR)
        suffix = _ext_from(url)
        target = directory / f"{_digest(url)}{suffix or '.bin'}"

        if not target.exists():
            try:
                async with self.client.stream("GET", url) as response:
                    response.raise_for_status()
                    if not suffix:
                        suffix = _ext_from(url, response.headers.get("content-type", "")) or ".bin"
                        target = directory / f"{_digest(url)}{suffix}"
                    with target.open("wb") as handle:
                        async for chunk in response.aiter_bytes(64 * 1024):
                            handle.write(chunk)
            except Exception as e:
                logger.warning(f"音频下载失败 {url[:80]}: {type(e).__name__} {e}")
                target.unlink(missing_ok=True)
                return None

        if not audio:
            return target

        if target.suffix.lower() == ".mp3":
            return target
        converted = await transcode_to_mp3(target)
        return converted

    def save_temp(self, data: bytes, name: str, image: bool = True) -> Optional[Path]:
        """把内存中的图片/数据落到共享目录，供命令输出与发送使用"""
        directory = subdir(IMAGE_SUBDIR if image else AUDIO_SUBDIR)
        target = directory / f"{_digest(name)}{Path(name).suffix or '.bin'}"
        try:
            target.write_bytes(data)
        except OSError as e:
            logger.warning(f"写入临时文件失败: {type(e).__name__} {e}")
            return None
        return target

    async def maybe_cleanup(self) -> None:
        """低频清理过期缓存，避免共享目录无限增长"""
        if time.time() - self._cleaned_at < 1800:
            return
        self._cleaned_at = time.time()
        await asyncio.gather(
            asyncio.to_thread(_cleanup, subdir(AUDIO_SUBDIR)),
            asyncio.to_thread(_cleanup, subdir(IMAGE_SUBDIR)),
            return_exceptions=True,
        )


__all__ = ["MusicDownloader", "subdir", "AUDIO_SUBDIR", "IMAGE_SUBDIR"]
