"""OneBot v11 原生发送

nekro 的消息段只有 文本 / 图片 / 文件，缺少语音与音乐卡片，
这里直接经 nonebot 的 bot 连接调用 OneBot API 补上这部分能力。
"""

import asyncio
import re
from pathlib import Path
from typing import Any, Optional, Union

from nekro_agent.api import core

logger = core.logger

_CHAT_KEY_RE = re.compile(r"^onebot_v11-(group|private)_(\d+)$")

SHARED_DIR_NAME = "nbcache"
"""该目录在 nekro_agent 与 napcat 容器内的绝对路径一致，可用于传递本地文件"""


def parse_chat_key(chat_key: str) -> Optional[tuple[str, int]]:
    """把 onebot_v11-group_123 解析为 ("group", 123)"""
    matched = _CHAT_KEY_RE.match(chat_key)
    if not matched:
        return None
    return matched.group(1), int(matched.group(2))


def shared_dir() -> Path:
    """返回与 NapCat 共享的可读目录"""
    from nekro_agent.core.os_env import OsEnv

    return Path(OsEnv.DATA_DIR) / SHARED_DIR_NAME


def get_bot():
    from nonebot import get_bot as _get_bot

    return _get_bot()


async def _call(chat_key: str, api: str, **params: Any):
    parts = parse_chat_key(chat_key)
    if not parts:
        raise ValueError(f"不是 onebot_v11 聊天标识: {chat_key}")
    chat_type, chat_id = parts
    if chat_type == "group":
        params["group_id"] = chat_id
    else:
        params["user_id"] = chat_id
    return await get_bot().call_api(api, **params)


async def send_message(chat_key: str, message: Union[str, list], api: Optional[str] = None) -> Any:
    """发送一条原始消息（支持 CQ 码字符串、消息段列表或 Message 对象）"""
    from nonebot.adapters.onebot.v11 import Message

    parts = parse_chat_key(chat_key)
    if not parts:
        raise ValueError(f"不是 onebot_v11 聊天标识: {chat_key}")
    chat_type, _ = parts

    if isinstance(message, str):
        message = Message(message)
    elif isinstance(message, list):
        message = Message(message)

    target_api = api or ("send_group_msg" if chat_type == "group" else "send_private_msg")
    return await _call(chat_key, target_api, message=message)


async def send_record(chat_key: str, source: str) -> Any:
    """发送语音。source 可以是 http(s) 链接、file:// 路径或本地绝对路径"""
    file_value = source
    if not source.startswith(("http://", "https://", "file://", "base64://")):
        file_value = f"file://{Path(source).resolve()}"

    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    return await send_message(chat_key, Message([MessageSegment.record(file_value)]))


async def send_image(chat_key: str, source: Union[str, Path, bytes]) -> Any:
    """发送图片。source 可以是本地路径、http(s) 链接或图片字节

    走 OneBot API 直发：nekro 的通用发送接口只认 uploads / shared 形式的沙盒路径，
    缓存目录里的图片会被判为非法路径，最终只发出去一条报错文本。
    """
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    if isinstance(source, bytes):
        segment = MessageSegment.image(source)
    elif str(source).startswith(("http://", "https://", "base64://")):
        segment = MessageSegment.image(str(source))
    else:
        segment = MessageSegment.image(Path(source).read_bytes())
    return await send_message(chat_key, Message([segment]))


async def send_music_card(chat_key: str, song_type: str, song_id: str) -> Any:
    """发送 QQ 音乐卡片，如 163（网易云）/ qq"""
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    return await send_message(chat_key, Message([MessageSegment.music(song_type, song_id)]))


async def send_custom_music_card(
    chat_key: str,
    url: str,
    audio: str,
    title: str,
    image: str,
    singer: str = "",
) -> Any:
    """发送自定义音乐卡片（非 QQ / 网易曲库）"""
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    segment = MessageSegment.music(
        "custom",
        {
            "url": url,
            "audio": audio,
            "title": title,
            "image": image,
            "singer": singer,
        },
    )
    return await send_message(chat_key, Message([segment]))


async def send_json_card(chat_key: str, card: dict) -> Any:
    """发送 JSON 卡片（签名音乐卡片走这里）"""
    import json as _json

    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    payload = _json.dumps(card, ensure_ascii=False)
    return await send_message(chat_key, Message([MessageSegment("json", {"data": payload})]))


async def upload_file(chat_key: str, file: str, name: str) -> Any:
    """上传文件，file 为 NapCat 可访问的路径或 URL"""
    parts = parse_chat_key(chat_key)
    if not parts:
        raise ValueError(f"不是 onebot_v11 聊天标识: {chat_key}")
    chat_type, _ = parts
    api = "upload_group_file" if chat_type == "group" else "upload_private_file"
    return await _call(chat_key, api, file=file, name=name)


async def transcode_to_mp3(src: Path, dst: Optional[Path] = None) -> Optional[Path]:
    """把任意音频转成 mp3（语音消息对格式有要求，m4a 之类需转换）"""
    if src.suffix.lower() == ".mp3":
        return src
    target = dst or src.with_suffix(".mp3")
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-ar",
        "44100",
        "-b:a",
        "128k",
        str(target),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0 or not target.exists():
        logger.warning(f"ffmpeg 转码失败: {stderr.decode(errors='ignore')[:200]}")
        return None
    return target


__all__ = [
    "SHARED_DIR_NAME",
    "parse_chat_key",
    "send_custom_music_card",
    "send_image",
    "send_json_card",
    "send_message",
    "send_music_card",
    "send_record",
    "shared_dir",
    "transcode_to_mp3",
    "upload_file",
]
