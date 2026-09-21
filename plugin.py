"""插件定义与配置"""

from pathlib import Path
from typing import Dict, List, Literal

from pydantic import Field

from nekro_agent.api import i18n
from nekro_agent.api.plugin import ConfigBase, ExtraField, NekroPlugin

from .core.platform import NetEaseMusic, TXQQMusic

plugin = NekroPlugin(
    name="点歌",
    module_name="nekro_music",
    description="多平台点歌：搜索选歌、歌词图片、热门评论，支持语音 / 文件 / 音乐卡片多种发送方式自动降级",
    version="1.0.0",
    author="luoxiQAQ",
    url="https://github.com/luoxiQAQ/nekro-plugin-music",
    i18n_name=i18n.i18n_text(
        zh_CN="点歌",
        en_US="Music Request",
    ),
    i18n_description=i18n.i18n_text(
        zh_CN="多平台点歌：搜索选歌、歌词图片、热门评论，支持语音 / 文件 / 音乐卡片多种发送方式自动降级",
        en_US="Multi-platform song requests with search, lyrics, comments and fallback send modes",
    ),
    allow_sleep=True,
    sleep_brief="用于点歌、搜索歌曲、查询歌词，在用户想听歌或要歌词时激活。",
)

ASSETS_DIR: Path = Path(__file__).resolve().parent / "assets"

PLATFORM_KEYWORDS: tuple = tuple(
    dict.fromkeys([*NetEaseMusic.platform.keywords, *TXQQMusic.platform.keywords])
)
"""全部可选平台的指令关键词，WebUI 下拉框与指令注册共用同一份来源"""

SEND_MODE_STOP = "不使用"
"""发送方式下拉框的终止项：选中即结束级联"""

SEND_MODE_MAP: Dict[str, str] = {
    "本地语音": "record_local",
    "语音链接": "record_link",
    "本地文件": "file_local",
    "文件链接": "file_link",
    "音乐卡片": "card",
    "签名卡片": "ark_card",
    "文本链接": "text",
}
"""发送方式下拉框的中文选项 → 内部实现名"""

SEND_MODE_CHOICES: tuple = (SEND_MODE_STOP, *SEND_MODE_MAP)


@plugin.mount_config()
class MusicConfig(ConfigBase):
    """点歌配置"""

    DEFAULT_PLATFORM: Literal[PLATFORM_KEYWORDS] = Field(
        default="网易点歌",
        title="默认点歌平台",
        description="《点歌》指令默认使用的平台。想临时换平台，在歌名前写平台名即可，例如「点歌 QQ 晴天」「点歌 网易云 晴天」",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="默认点歌平台", en_US="Default Platform"),
            i18n_description=i18n.i18n_text(
                zh_CN="《点歌》指令默认使用的平台；歌名前写平台名可临时切换，如「点歌 QQ 晴天」",
                en_US="Default platform for the command; prefix the song name to switch, e.g. \"点歌 QQ 晴天\"",
            ),
        ).model_dump(),
    )
    NETEASE_API_BASE: str = Field(
        default="http://172.19.0.1:3301",
        title="网易云 API 地址",
        description="网易云 NodeJS API 根地址。宿主 172.19.0.1:3301 是通向广州服务器已登录实例的隧道；留空则不启用网易平台",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="网易云 API 地址", en_US="NetEase API Base"),
            i18n_description=i18n.i18n_text(
                zh_CN="网易云 NodeJS API 根地址；留空则不启用网易平台",
                en_US="NetEase NodeJS API base URL; leave empty to disable",
            ),
        ).model_dump(),
    )
    ENABLE_TXQQ: bool = Field(
        default=True,
        title="启用聚合音源",
        description="启用 QQ音乐 / 酷狗 / 酷我 / 百度 / 咪咕 / 荔枝 / 一听 / 蜻蜓 等平台（来自 music.txqq.pro 聚合接口）",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="启用聚合音源", en_US="Enable Aggregator"),
            i18n_description=i18n.i18n_text(
                zh_CN="启用 QQ音乐 / 酷狗 / 酷我 / 百度 / 咪咕 等平台",
                en_US="Enable the txqq aggregator platforms",
            ),
        ).model_dump(),
    )
    SONG_LIMIT: int = Field(
        default=5,
        title="候选数量",
        description="搜索返回的候选歌曲数量，范围 1-20",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="候选数量", en_US="Candidate Count"),
            i18n_description=i18n.i18n_text(
                zh_CN="搜索返回的候选歌曲数量，范围 1-20",
                en_US="Number of candidates returned by search",
            ),
        ).model_dump(),
    )
    SELECT_MODE: str = Field(
        default="image",
        title="选歌展示方式",
        description="image = 渲染候选卡片图；text = 纯文本列表。两种方式都回复序号选歌",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="选歌展示方式", en_US="Selection Display"),
            i18n_description=i18n.i18n_text(
                zh_CN="image = 渲染候选卡片图；text = 纯文本列表",
                en_US="image renders candidate cards, text sends a plain list",
            ),
        ).model_dump(),
    )
    CARD_COLUMNS: int = Field(
        default=3,
        title="候选图列数",
        description="候选卡片图每行显示几首歌，范围 1-5",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="候选图列数", en_US="Card Columns"),
            i18n_description=i18n.i18n_text(
                zh_CN="候选卡片图每行显示几首歌",
                en_US="Cards per row in the candidate image",
            ),
        ).model_dump(),
    )
    SEND_MODE_1: Literal[SEND_MODE_CHOICES] = Field(
        default="本地语音",
        title="发送方式 1（首选）",
        description=(
            "首选发送方式，失败自动降级到下一项。实测：QQ 私聊不支持文件上传（本地文件 / 文件链接必失败），"
            "音乐卡片在私聊会卡约 30 秒才超时；私聊建议用本地语音 / 语音链接 / 文本链接，群聊各方式均可。"
            "选「不使用」表示不发送歌曲"
        ),
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="发送方式 1（首选）", en_US="Send Mode 1 (primary)"),
            i18n_description=i18n.i18n_text(
                zh_CN="首选发送方式，失败自动降级；私聊不支持文件上传，音乐卡片会超时",
                en_US="Primary send mode, falls back on failure. File upload and cards do not work in private chats",
            ),
        ).model_dump(),
    )
    SEND_MODE_2: Literal[SEND_MODE_CHOICES] = Field(
        default="本地文件",
        title="发送方式 2",
        description="首选失败时改用这一项；选「不使用」表示不再尝试后面的方式",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="发送方式 2", en_US="Send Mode 2"),
            i18n_description=i18n.i18n_text(
                zh_CN="上一项失败时改用这一项；选「不使用」即结束",
                en_US="Used when the previous mode fails; pick 不使用 to stop",
            ),
        ).model_dump(),
    )
    SEND_MODE_3: Literal[SEND_MODE_CHOICES] = Field(
        default="文本链接",
        title="发送方式 3",
        description="发送方式 2 失败时改用这一项；选「不使用」表示不再尝试后面的方式",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="发送方式 3", en_US="Send Mode 3"),
            i18n_description=i18n.i18n_text(
                zh_CN="上一项失败时改用这一项；选「不使用」即结束",
                en_US="Used when the previous mode fails; pick 不使用 to stop",
            ),
        ).model_dump(),
    )
    SEND_MODE_4: Literal[SEND_MODE_CHOICES] = Field(
        default="不使用",
        title="发送方式 4",
        description="发送方式 3 失败时改用这一项；选「不使用」表示不再尝试后面的方式",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="发送方式 4", en_US="Send Mode 4"),
            i18n_description=i18n.i18n_text(
                zh_CN="上一项失败时改用这一项；选「不使用」即结束",
                en_US="Used when the previous mode fails; pick 不使用 to stop",
            ),
        ).model_dump(),
    )
    ENABLE_COMMENTS: bool = Field(
        default=True,
        title="发送热门评论",
        description="指令点歌（/点歌）发送歌曲后附带一条随机热门评论，仅网易云音源可用；AI 自然语言点歌不会附带",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="发送热门评论", en_US="Attach Hot Comment"),
            i18n_description=i18n.i18n_text(
                zh_CN="指令点歌（/点歌）发送歌曲后附带一条随机热门评论，仅网易云音源可用；AI 自然语言点歌不会附带",
                en_US="Send a random hot comment after the song via the /点歌 command (NetEase only); natural-language requests never attach one",
            ),
        ).model_dump(),
    )
    ENABLE_LYRICS: bool = Field(
        default=False,
        title="发送歌词图片",
        description="发送歌曲后附带一张歌词图片",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="发送歌词图片", en_US="Attach Lyrics Image"),
            i18n_description=i18n.i18n_text(
                zh_CN="发送歌曲后附带一张歌词图片",
                en_US="Send a lyrics image after the song",
            ),
        ).model_dump(),
    )
    SELECT_TIMEOUT: int = Field(
        default=45,
        title="选歌超时（秒）",
        description="展示候选列表后，超过该时间未回复序号则取消点歌",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="选歌超时（秒）", en_US="Selection Timeout"),
            i18n_description=i18n.i18n_text(
                zh_CN="展示候选列表后，超过该时间未回复序号则取消点歌",
                en_US="Seconds to wait for the user to pick a song",
            ),
        ).model_dump(),
    )
    SIGN_API_URL: str = Field(
        default="https://apii.xianyuw.cn/api/v1/qq-musicArk",
        title="签名卡片接口",
        description="ark_card 签名音乐卡片的接口地址，返回 {app, meta, prompt, view} 结构",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="签名卡片接口", en_US="Signed Card API"),
            i18n_description=i18n.i18n_text(
                zh_CN="ark_card 签名音乐卡片的接口地址",
                en_US="Endpoint used by the ark_card send mode",
            ),
        ).model_dump(),
    )
    SIGN_API_KEY: str = Field(
        default="",
        title="签名卡片 API Key",
        description="留空则跳过 ark_card 方式",
        json_schema_extra=ExtraField(
            i18n_title=i18n.i18n_text(zh_CN="签名卡片 API Key", en_US="Signed Card API Key"),
            i18n_description=i18n.i18n_text(
                zh_CN="留空则跳过 ark_card 方式",
                en_US="Leave empty to disable the ark_card mode",
            ),
        ).model_dump(),
    )

    @property
    def send_modes(self) -> List[str]:
        """按优先级解析出的发送方式实现名列表，遇到「不使用」即结束"""
        modes: List[str] = []
        for label in (self.SEND_MODE_1, self.SEND_MODE_2, self.SEND_MODE_3, self.SEND_MODE_4):
            if label == SEND_MODE_STOP:
                break
            key = SEND_MODE_MAP.get(label)
            if key and key not in modes:
                modes.append(key)
        return modes


config = plugin.get_config(MusicConfig)
