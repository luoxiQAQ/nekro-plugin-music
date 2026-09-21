"""
# 点歌 (Music)

在群里点歌：搜索多平台音源，把候选歌曲渲染成卡片图，选中后以语音、文件或音乐卡片发出。

## 主要功能

- **多平台点歌**: 支持网易云音乐与聚合音源（QQ音乐 / 酷狗 / 酷我 / 百度 / 咪咕 / 荔枝 / 一听 / 蜻蜓），`/点歌 歌名` 走默认音源，在歌名前写平台名即可临时切换，如 `/点歌 QQ 晴天`、`/点歌 酷狗 晴天`。
- **候选卡片选歌**: 搜索结果渲染成带封面、时长与序号的卡片图，回复序号即可播放，超时自动取消。
- **七种发送方式**: `card` 音乐卡片 / `ark_card` 签名卡片 / `record_link` 语音链接 / `record_local` 本地语音 / `file_link` 文件链接 / `file_local` 本地文件 / `text` 文本链接，按配置顺序级联，失败自动降级。
- **歌词与热评**: `/查歌词 歌名` 渲染歌词图片；`/点歌` 发送成功后可选附带一条热门评论，AI 自然语言点歌不会附带。

## 使用方法

- **命令**: 只有一条点歌指令 `/点歌 [平台] 歌名 [序号]`——不写平台走默认音源（`/点歌 晴天`），开头写平台名临时切换（`/点歌 QQ 晴天`、`/点歌 网易云 晴天`），末尾写数字直接播第几首（`/点歌 晴天 2`）。另有歌词指令 `/查歌词 歌名`。
- **AI 自动使用**: 对 AI 说"放首歌"、"我想听晴天"时，AI 会搜索并播放第一首结果。
- **回复序号**: 候选列表发出后，直接回复数字选歌，该消息不会唤醒 AI。

## 配置说明

- **音源**: `NETEASE_API_BASE` 指向网易云 NodeJS API（本部署经隧道映射到宿主 172.19.0.1:3301）；`ENABLE_TXQQ` 控制聚合音源。
- **发送方式**: 在 WebUI 配置里用下拉框从「本地语音 / 语音链接 / 本地文件 / 文件链接 / 音乐卡片 / 签名卡片 / 文本链接」中逐级选择优先级（发送方式 1~4），某级失败自动降级到下一级，选「不使用」即到此结束。
- **本地发送前提**: 本地语音与本地文件依赖 nekro_agent 与 NapCat 都能读到的共享目录（`nbcache`），两者绝对路径一致。
- **显示**: `SELECT_MODE` 可选 `image` 卡片图或 `text` 文本列表，`CARD_COLUMNS` 控制每行卡片数。

## 来源

移植自 AstrBot 插件 [Zhalslar/astrbot_plugin_music](https://github.com/Zhalslar/astrbot_plugin_music)，沿用其平台接入与渲染思路，按 nekro-agent 的插件接口重写。
"""

import sys

# nekro 的热重载只丢弃顶层模块，子模块会留在 sys.modules 里继续跑旧代码；
# 清掉自己名下的子模块，/api/plugins/reload 才能真的加载到最新代码。
for _stale in [name for name in sys.modules if name.startswith(f"{__name__}.")]:
    sys.modules.pop(_stale, None)

from . import handlers
from .plugin import plugin

__all__ = ["plugin"]
