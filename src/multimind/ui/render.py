"""纯文本渲染（非 TUI 场景用）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multimind.core.types import Message

__all__ = ["render_message"]

# 角色颜色（Rich markup）
TIER_COLORS: dict[str, str] = {
    "leader": "red",
    "dispatcher": "yellow",
    "executor": "green",
    "user": "cyan",
    "system": "dim",
}


def render_message(msg: Message, tier: str = "system") -> str:
    """渲染单条消息为 Rich markup 字符串。

    Args:
        msg: 群聊消息。
        tier: 角色层级（用于配色）。

    Returns:
        Rich markup 格式的字符串。
    """
    color = TIER_COLORS.get(tier, "white")
    channel = f" [dim]({msg.channel})[/]" if msg.channel else ""
    return f"[{color} bold]{msg.role}[/]{channel}: {msg.content}"
