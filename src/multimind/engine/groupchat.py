"""群聊消息总线 — 所有角色共享上下文。

支持 @mention 定向、广播、按层级流转。
提供 Hooks 生命周期钩子（借鉴 Grok Build）。
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from multimind.core.types import Message

__all__ = ["TopologyMode", "ChatEvent", "GroupChatBus"]

logger = logging.getLogger(__name__)


class TopologyMode(str, Enum):
    """拓扑模式。

    Attributes:
        LAYERED: 分层 — Leader → Dispatcher → Executor。
        FLAT: 扁平 — 所有角色同层平等。
        HYBRID: 混合 — 部分分层部分扁平。
    """

    LAYERED = "layered"
    FLAT = "flat"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """群聊事件（用于 Hooks 和审计）。

    Attributes:
        type: 事件类型（message / mention / broadcast / flatten / rebuild）。
        source: 来源角色名。
        target: @mention 目标（仅 mention 事件）。
        content: 事件内容。
        timestamp: Unix 时间戳。
    """

    type: str
    source: str
    target: str = ""
    content: str = ""
    timestamp: float = field(default_factory=time.time)


# Hook 回调类型
HookCallback = Callable[[Any], None | Coroutine[Any, None, None]]


class GroupChatBus:
    """群聊消息总线 — 单一消息源，所有角色共享。

    职责：
    - 维护群聊消息历史。
    - 支持订阅/取消订阅（观察者模式）。
    - 提供 @mention 定向和广播。
    - 管理 Hooks 生命周期钩子。
    - 管理拓扑模式状态。
    """

    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._listeners: list[Any] = []  # asyncio.Queue[Message]
        self._event_hooks: dict[str, list[HookCallback]] = defaultdict(list)
        self._topology: TopologyMode = TopologyMode.LAYERED

    @property
    def messages(self) -> list[Message]:
        """返回消息历史副本。"""
        return list(self._messages)

    @property
    def topology(self) -> TopologyMode:
        """当前拓扑模式。"""
        return self._topology

    def subscribe(self) -> Any:
        """订阅新消息（返回 asyncio.Queue）。"""
        import asyncio

        q: asyncio.Queue[Message] = asyncio.Queue()
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: Any) -> None:
        """取消订阅。"""
        if q in self._listeners:
            self._listeners.remove(q)

    async def post(self, msg: Message) -> None:
        """发送消息到群聊总线。"""
        self._messages.append(msg)
        await self._fire_hook("post-message", msg)
        for q in self._listeners:
            await q.put(msg)
        logger.debug("Bus posted: %s -> %s", msg.role, msg.content[:50])

    async def mention(self, source: str, target: str, content: str, channel: str = "") -> None:
        """@mention 定向消息。"""
        msg = Message(role=source, content=f"@{target} {content}", channel=channel)
        await self.post(msg)
        await self._fire_hook(
            "mention", ChatEvent("mention", source, target, content)
        )

    async def broadcast(self, source: str, content: str, channel: str = "") -> None:
        """广播消息。"""
        msg = Message(role=source, content=content, channel=channel)
        await self.post(msg)
        await self._fire_hook("broadcast", ChatEvent("broadcast", source, "", content))

    async def flatten(self) -> None:
        """拉平拓扑。"""
        self._topology = TopologyMode.FLAT
        await self._fire_hook("flatten", ChatEvent("flatten", "system"))
        logger.info("Topology flattened")

    async def rebuild(self) -> None:
        """重建层级拓扑。"""
        self._topology = TopologyMode.LAYERED
        await self._fire_hook("rebuild", ChatEvent("rebuild", "system"))
        logger.info("Topology rebuilt")

    def add_hook(self, event: str, callback: HookCallback) -> None:
        """注册 Hook 回调。

        支持的 event:
        - ``post-message``: 消息发送后
        - ``mention``: @mention 事件
        - ``broadcast``: 广播事件
        - ``flatten`` / ``rebuild``: 拓扑切换
        - ``pre-edit`` / ``post-edit``: 文件编辑前后
        - ``pre-command`` / ``post-command``: 命令执行前后
        - ``on-error``: 错误事件
        """
        self._event_hooks[event].append(callback)

    async def _fire_hook(self, event: str, data: Any) -> None:
        for cb in self._event_hooks.get(event, []):
            result = cb(data)
            if asyncio.iscoroutine(result):  # type: ignore[name-defined]
                await result

    def history(self, limit: int = 50) -> list[Message]:
        """获取最近的消息历史。"""
        return self._messages[-limit:]

    def context_for(self, role_name: str) -> list[Message]:
        """为指定角色组装上下文。

        包含 @mention 该角色的消息和所有广播消息。
        """
        return [
            m for m in self._messages
            if f"@{role_name}" in m.content or "@" not in m.content
        ]


# 在模块级别导入 asyncio（避免循环引用问题）
import asyncio  # noqa: E402  # isort: skip
