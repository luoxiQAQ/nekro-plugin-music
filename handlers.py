"""命令、AI 工具与选歌回调"""

import re
import time
from pathlib import Path
from typing import Annotated, AsyncIterator, Dict, List, Optional, Tuple

from nekro_agent.api.plugin import CmdCtl, CommandResponse, SandboxMethodType
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.services.command.schemas import (
    Arg,
    CommandExecutionContext,
    CommandOutputSegment,
    CommandOutputSegmentType,
)

from .core.files import MusicDownloader
from .core.model import PendingSelection, Song
from .core.platform import BaseMusicPlayer, NetEaseMusic, TXQQMusic
from .core.render import MusicRenderer
from .core.sender import MusicSender
from .plugin import ASSETS_DIR, config, plugin

logger = plugin.logger

FONT_PATH = ASSETS_DIR / "fonts" / "simhei.ttf"
"""候选图与歌词图使用的字体"""

PENDING_TTL = 600
"""待选歌曲的兜底有效期（秒），正常由 wait 超时控制"""

renderer = MusicRenderer(str(FONT_PATH), columns=config.CARD_COLUMNS)
downloader = MusicDownloader()
sender = MusicSender(renderer, downloader)

_players: List[BaseMusicPlayer] = []
_pending: Dict[Tuple[str, str], PendingSelection] = {}

_CANCEL_WORDS = {"取消", "退出", "不听了", "算了", "cancel", "q"}


# ---------- 音源管理 ----------


def _build_players() -> None:
    """按配置实例化可用音源"""
    global _players
    for player in _players:
        logger.debug(f"[music] 释放音源 {player.platform.name}")
    _players = []

    base = (config.NETEASE_API_BASE or "").strip()
    if base:
        _players.append(NetEaseMusic(base))
    else:
        logger.info("[music] 未配置网易云 API 地址，网易音源不可用")

    if config.ENABLE_TXQQ:
        _players.append(TXQQMusic())

    logger.info(f"[music] 已启用音源: {[p.platform.display_name for p in _players]}")


def _find_player(name: str) -> Optional[BaseMusicPlayer]:
    """按平台标识 / 展示名 / 关键词匹配音源"""
    target = (name or "").strip().lower()
    if not target:
        return None
    for player in _players:
        platform = player.platform
        if target in (platform.name.lower(), platform.display_name.lower()):
            return player
        if any(keyword.lower() == target for keyword in platform.keywords):
            return player
    return None


def _all_keywords() -> List[str]:
    keywords: List[str] = []
    for player_cls in BaseMusicPlayer.get_all_subclass():
        for keyword in player_cls.platform.keywords:
            if keyword not in keywords:
                keywords.append(keyword)
    return keywords


def _platform_aliases() -> Dict[str, str]:
    """平台别名 → 平台指令关键词，供「点歌 QQ 晴天」这种开头写法使用"""
    aliases: Dict[str, str] = {}
    for player_cls in BaseMusicPlayer.get_all_subclass():
        platform = player_cls.platform
        for name in (platform.name, platform.display_name):
            aliases.setdefault(name.lower(), platform.keywords[0])
        for keyword in platform.keywords:
            aliases.setdefault(keyword.lower(), keyword)
            if keyword.endswith("点歌") and len(keyword) > 2:
                aliases.setdefault(keyword[:-2].lower(), keyword)
    return aliases


_PLATFORM_ALIASES: Dict[str, str] = _platform_aliases()


def _default_target() -> Tuple[Optional[BaseMusicPlayer], str]:
    """默认平台对应的音源与平台关键词，后者决定聚合源走哪个曲库"""
    keyword = config.DEFAULT_PLATFORM
    player = _find_player(keyword)
    if player is None and _players:
        player = _players[0]
        logger.warning(f"[music] 默认平台 {keyword} 当前不可用，改用 {player.platform.display_name}")
        keyword = player.platform.keywords[0]
    return player, keyword


def _split_leading_platform(text: str) -> Tuple[Optional[str], str]:
    """拆出开头的平台词；首词不是平台时原样返回"""
    parts = (text or "").strip().split(maxsplit=1)
    if not parts:
        return None, ""
    keyword = _PLATFORM_ALIASES.get(parts[0].lower())
    if keyword is None:
        return None, text.strip()
    return keyword, (parts[1].strip() if len(parts) > 1 else "")


# ---------- 待选状态 ----------


def _store_pending(selection: PendingSelection) -> None:
    now = time.time()
    for key, item in list(_pending.items()):
        if now - item.created_at > PENDING_TTL:
            _pending.pop(key, None)
    _pending[(selection.chat_key, selection.user_id)] = selection


def _peek_pending(chat_key: str, user_id: str) -> Optional[PendingSelection]:
    item = _pending.get((chat_key, user_id))
    if item and time.time() - item.created_at > PENDING_TTL:
        _pending.pop((chat_key, user_id), None)
        return None
    return item


def _drop_pending(chat_key: str, user_id: str) -> None:
    _pending.pop((chat_key, user_id), None)


# ---------- 业务 ----------


async def _search(player: BaseMusicPlayer, keyword: str, limit: Optional[int] = None, extra: str = "") -> List[Song]:
    limit = max(1, min(limit or config.SONG_LIMIT, 20))
    try:
        return await player.fetch_songs(keyword, limit=limit, extra=extra or None)
    except Exception as e:
        logger.exception(f"[music] 搜索歌曲失败: {e}")
        return []


async def _send_song(chat_key: str, player: BaseMusicPlayer, song: Song, with_comment: bool = True) -> bool:
    """发送单曲（命令与 AI 工具共用，AI 工具不附热评）"""
    ctx = await AgentCtx.create_by_chat_key(chat_key)
    return await sender.send_song(chat_key, ctx, player, song, with_comment=with_comment)


def _selection_segments(songs: List[Song], player: BaseMusicPlayer, image_path: Optional[Path]) -> List[CommandOutputSegment]:
    segments = [
        CommandOutputSegment(
            type=CommandOutputSegmentType.TEXT,
            text=sender.selection_text(songs, player),
        )
    ]
    if image_path:
        segments.append(
            CommandOutputSegment(type=CommandOutputSegmentType.IMAGE, file_path=str(image_path))
        )
    return segments


def _split_trailing_index(keyword: str) -> Tuple[str, int]:
    """把「晴天 2」拆成歌名与序号"""
    parts = keyword.strip().split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return " ".join(parts[:-1]), int(parts[-1])
    return keyword.strip(), 0


async def _request_flow(
    context: CommandExecutionContext,
    player: Optional[BaseMusicPlayer],
    keyword: str,
    extra: str = "",
) -> AsyncIterator[CommandResponse]:
    """搜索并进入选歌流程，命令与回调共用"""
    if player is None:
        yield CmdCtl.failed("当前没有可用的音源，请先在插件配置里启用音源～")
        return

    song_name, index = _split_trailing_index(keyword or "")
    if not song_name:
        yield CmdCtl.failed("想听什么歌呢？发送「/点歌 歌名」试试～")
        return

    logger.info(f"[music] {context.username or context.user_id} 在 {player.platform.display_name} 搜索: {song_name}")
    songs = await _search(player, song_name, extra=extra)
    if not songs:
        yield CmdCtl.failed(f"没有搜到「{song_name}」，换个关键词试试～")
        return

    if index and 1 <= index <= len(songs):
        song = songs[index - 1]
        ok = await _send_song(context.chat_key, player, song)
        yield CmdCtl.success(f"已为你点播《{song.label()}》" if ok else "歌曲发送失败，请稍后再试～")
        return

    if len(songs) == 1:
        ok = await _send_song(context.chat_key, player, songs[0])
        yield CmdCtl.success(f"已为你点播《{songs[0].label()}》" if ok else "歌曲发送失败，请稍后再试～")
        return

    image_path: Optional[Path] = None
    if config.SELECT_MODE == "image":
        image_path = await sender.render_selection(songs, player)
        if image_path is None:
            logger.warning("[music] 候选图渲染失败，回退为文本列表")

    _store_pending(
        PendingSelection(
            chat_key=context.chat_key,
            user_id=context.user_id,
            songs=songs,
            player_name=player.platform.name,
            created_at=time.time(),
            extra=extra or None,
        )
    )

    yield CmdCtl.message(_selection_segments(songs, player, image_path))
    yield CmdCtl.wait(
        message=f"回复序号选歌（{config.SELECT_TIMEOUT} 秒内有效）",
        callback_cmd="点歌选择",
        options=[str(i) for i in range(1, len(songs) + 1)],
        timeout=float(config.SELECT_TIMEOUT),
        on_timeout_message="点歌超时，已取消～",
    )


# ---------- 命令 ----------


@plugin.mount_command(
    name="点歌",
    description="搜索歌曲并选择播放，可在开头写平台名指定音源",
    aliases=["点歌台"],
    usage="点歌 [平台] 歌名 [序号]",
    category="娱乐",
    tags=["音乐", "点歌"],
)
async def music_command(
    context: CommandExecutionContext,
    keyword: Annotated[str, Arg("歌曲名或关键词", positional=True, greedy=True)] = "",
) -> AsyncIterator[CommandResponse]:
    platform_keyword, song_part = _split_leading_platform(keyword)
    if platform_keyword:
        player = _find_player(platform_keyword)
        if player is None:
            yield CmdCtl.failed(f"平台「{platform_keyword}」当前不可用，检查下插件配置吧～")
            return
        extra = platform_keyword
    else:
        player, extra = _default_target()

    async for response in _request_flow(context, player, song_part, extra=extra):
        yield response


@plugin.mount_command(
    name="查歌词",
    description="按歌名搜索并发送歌词图片",
    aliases=["查看歌词"],
    usage="查歌词 歌名",
    category="娱乐",
    tags=["音乐", "歌词"],
)
async def music_lyrics_command(
    context: CommandExecutionContext,
    keyword: Annotated[str, Arg("歌曲名或关键词", positional=True, greedy=True)] = "",
) -> CommandResponse:
    player, extra = _default_target()
    if player is None:
        return CmdCtl.failed("当前没有可用的音源，请先在插件配置里启用音源～")

    song_name = (keyword or "").strip()
    if not song_name:
        return CmdCtl.failed("想查哪首歌的歌词呢？发送「/查歌词 歌名」试试～")

    songs = await _search(player, song_name, limit=1, extra=extra)
    if not songs:
        return CmdCtl.failed(f"没有搜到「{song_name}」～")

    song = songs[0]
    ctx = await AgentCtx.create_by_chat_key(context.chat_key)
    if not await sender.send_lyrics(context.chat_key, ctx, player, song):
        return CmdCtl.failed(f"《{song.label()}》没有取到歌词～")

    return CmdCtl.success(f"这是《{song.label()}》的歌词～")


@plugin.mount_command(
    name="点歌选择",
    description="选择要播放的歌曲（点歌后回复序号自动触发）",
    usage="点歌选择 序号",
    category="娱乐",
    internal=True,
)
async def music_select_command(
    context: CommandExecutionContext,
    choice: Annotated[str, Arg("歌曲序号", positional=True, greedy=True)] = "",
) -> CommandResponse:
    pending = _peek_pending(context.chat_key, context.user_id)
    if pending is None:
        return CmdCtl.failed("没有待选择的歌曲，发送「/点歌 歌名」重新开始吧～")

    raw = (choice or "").strip()
    if raw.lower() in _CANCEL_WORDS:
        _drop_pending(context.chat_key, context.user_id)
        return CmdCtl.success("已取消点歌～")

    matched = re.search(r"\d+", raw)
    if not matched:
        return CmdCtl.failed(f"请回复歌曲序号（1-{len(pending.songs)}），或回复「取消」")

    index = int(matched.group())
    if index < 1 or index > len(pending.songs):
        return CmdCtl.failed(f"序号超出范围了，请回复 1-{len(pending.songs)}")

    player = _find_player(pending.player_name)
    if player is None:
        _drop_pending(context.chat_key, context.user_id)
        return CmdCtl.failed("音源已不可用，请重新点歌～")

    _drop_pending(context.chat_key, context.user_id)
    song = pending.songs[index - 1]
    ok = await _send_song(context.chat_key, player, song)
    return CmdCtl.success(f"已为你点播《{song.label()}》") if ok else CmdCtl.failed("歌曲发送失败，请稍后再试～")


# ---------- AI 工具 ----------


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="点歌",
    description="用户想听歌、让你放歌时使用：按歌名（可含歌手）搜索并直接播放到当前聊天，支持网易云 / QQ音乐 / 酷狗 / 酷我等平台",
)
async def music_play_tool(_ctx: AgentCtx, song_name: str, platform: str = "") -> str:
    """搜索歌曲并直接播放到当前聊天 (use lang: zh-CN)

    **应用场景: 用户想听歌、让你放歌时使用**——例如「放首歌」「来首歌」「我想听晴天」「放一下周杰伦的歌」
    「能不能播 xxx」「点歌 xxx」「换一首」。

    **注意**: 一次只播放搜索到的第一首；若用户想挑版本，提示他发送「/点歌 歌名」从候选里选。

    Args:
        song_name (str): 歌曲名或包含歌手的关键词，例如「晴天」「周杰伦 晴天」
        platform (str): 点歌平台，留空使用默认音源。可用短名：网易 / QQ / 酷狗 / 酷我 / 百度 / 咪咕 / 荔枝 / 一听 / 蜻蜓 / 喜马

    Returns:
        str: 播放结果
    """
    token = (platform or "").strip()
    if not token:
        player, extra = _default_target()
        if player is None:
            return "当前没有可用的音源"
    else:
        matched = _PLATFORM_ALIASES.get(token.lower())
        player = _find_player(matched) if matched else None
        if player is None:
            return f"没有可用的音源：{token}"
        extra = matched

    keyword = (song_name or "").strip()
    if not keyword:
        return "请提供歌曲名或关键词"

    songs = await _search(player, keyword, limit=1, extra=extra)
    if not songs:
        return f"没有搜到「{keyword}」"

    song = songs[0]
    ok = await _send_song(_ctx.chat_key, player, song, with_comment=False)
    if not ok:
        return f"《{song.label()}》发送失败，请稍后再试"

    return f"已通过{player.platform.display_name}播放《{song.label()}》，如需换版本可让用户发送「/点歌 {keyword}」挑选"


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="查歌词",
    description="用户想要某首歌的歌词时使用：按歌名搜索歌曲并把歌词图片发到当前聊天",
)
async def music_lyrics_tool(_ctx: AgentCtx, song_name: str) -> str:
    """搜索歌曲并把歌词图片发到当前聊天 (use lang: zh-CN)

    **应用场景: 用户要某首歌的歌词时使用**——例如「查一下晴天的歌词」「这首歌歌词是什么」
    「来份 xxx 的歌词」。

    Args:
        song_name (str): 歌曲名或包含歌手的关键词

    Returns:
        str: 查询结果
    """
    keyword = (song_name or "").strip()
    if not keyword:
        return "请提供歌曲名或关键词"

    player, extra = _default_target()
    if player is None:
        return "当前没有可用的音源"

    songs = await _search(player, keyword, limit=1, extra=extra)
    if not songs:
        return f"没有搜到「{keyword}」"

    if not await sender.send_lyrics(_ctx.chat_key, _ctx, player, songs[0]):
        return f"《{songs[0].label()}》没有取到歌词"
    return f"已发送《{songs[0].label()}》的歌词图片"


# ---------- 生命周期 ----------


@plugin.mount_init_method()
async def init() -> None:
    if not FONT_PATH.exists():
        logger.warning(f"[music] 缺少字体文件 {FONT_PATH}，候选图与歌词图可能渲染失败")
    _build_players()
    logger.info(f"[music] 点歌插件已加载，可用平台关键词: {_all_keywords()}")


@plugin.mount_cleanup_method()
async def cleanup() -> None:
    for player in _players:
        await player.close()
    _players.clear()
    _pending.clear()
    await sender.close()
    await downloader.close()
    logger.info("[music] 点歌插件已卸载")
