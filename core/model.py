"""数据模型"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Song:
    """一首歌"""

    id: str
    source: Optional[str] = None
    """来源平台标识，如 netease / qq / kugou"""
    name: Optional[str] = None
    artists: Optional[str] = None
    duration: Optional[int] = None
    """时长（毫秒）"""
    cover_url: Optional[str] = None
    audio_url: Optional[str] = None
    lyrics: Optional[str] = None
    comments: Optional[List[dict]] = None
    note: Optional[str] = None

    def label(self) -> str:
        return f"{self.name or '未知歌曲'} - {self.artists or '未知歌手'}"

    def duration_text(self) -> str:
        if not self.duration:
            return "0:00"
        total = self.duration // 1000
        return f"{total // 60}:{total % 60:02d}"

    def extras(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "name": self.name,
            "artists": self.artists,
            "duration": self.duration,
            "cover_url": self.cover_url,
            "audio_url": self.audio_url,
        }


@dataclass
class Platform:
    """平台信息"""

    name: str
    """内部标识"""
    display_name: str
    """展示名称"""
    keywords: List[str] = field(default_factory=list)
    """触发关键词"""


@dataclass
class PendingSelection:
    """等待用户回复序号的选歌上下文"""

    chat_key: str
    user_id: str
    songs: List[Song]
    player_name: str
    created_at: float
    extra: Optional[str] = None
    """透传给平台搜索的额外参数（如具体音源）"""


__all__ = ["PendingSelection", "Platform", "Song"]
