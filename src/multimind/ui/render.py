"""纯文本渲染（非 TUI 场景用）— 赛博科技感配色。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multimind.core.types import Message

__all__ = ["render_message", "TIER_COLORS", "TIER_ICONS"]

# 角色颜色（霓虹系 Rich markup）
TIER_COLORS: dict[str, str] = {
    "leader": "#ff2a6d",  # 霓虹红
    "dispatcher": "#ffd300",  # 霓虹黄
    "executor": "#00ff9d",  # 霓虹绿
    "user": "#00e5ff",  # 霓虹青
    "system": "#5c6773",  # 冷灰
}

# 角色图标
TIER_ICONS: dict[str, str] = {
    "leader": "◆",
    "dispatcher": "▸",
    "executor": "⚙",
    "user": "❯",
    "system": "·",
}


def render_message(msg: Message, tier: str = "system") -> str:
    """渲染单条消息为 Rich markup 字符串。

    Args:
        msg: 群聊消息。
        tier: 角色层级（用于配色与图标）。

    Returns:
        Rich markup 格式的字符串。
    """
    color = TIER_COLORS.get(tier, "#e0e0e0")
    icon = TIER_ICONS.get(tier, "·")
    channel = f" [dim #5c6773]({msg.channel})[/]" if msg.channel else ""
    return f"[{color}]{icon} [bold]{msg.role}[/][/{color}]{channel}: {msg.content}"
