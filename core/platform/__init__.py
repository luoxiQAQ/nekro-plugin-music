"""平台实现集合"""

from .base import BaseMusicPlayer
from .netease import NetEaseMusic
from .txqq import TXQQMusic

__all__ = ["BaseMusicPlayer", "NetEaseMusic", "TXQQMusic"]
