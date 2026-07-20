"""拓扑管理 — 分层/扁平/动态切换。"""

from __future__ import annotations

import logging

from multimind.engine.groupchat import GroupChatBus, TopologyMode

__all__ = ["TopologyManager"]

logger = logging.getLogger(__name__)


class TopologyManager:
    """拓扑切换管理器。

    封装群聊总线的拓扑状态管理，提供语义化的切换接口。
    """

    def __init__(self, bus: GroupChatBus) -> None:
        self._bus = bus

    @property
    def mode(self) -> TopologyMode:
        """当前拓扑模式。"""
        return self._bus.topology

    async def flatten(self) -> str:
        """拉平：所有角色拉到同层平等对话。

        Returns:
            操作结果描述。
        """
        await self._bus.flatten()
        return "已拉平：所有角色现在同层平等对话"

    async def rebuild(self) -> str:
        """重建：恢复 Leader → Dispatcher → Executor 分层。

        Returns:
            操作结果描述。
        """
        await self._bus.rebuild()
        return "已重建：恢复 Leader → Dispatcher → Executor 分层"

    async def toggle(self) -> str:
        """切换拓扑（分层 ↔ 扁平）。

        Returns:
            操作结果描述。
        """
        if self._bus.topology == TopologyMode.LAYERED:
            return await self.flatten()
        return await self.rebuild()

    def describe(self) -> str:
        """返回当前拓扑的可读描述。"""
        descriptions = {
            TopologyMode.LAYERED: "分层模式：Leader → Dispatcher → Executor",
            TopologyMode.FLAT: "扁平模式：所有角色同层",
            TopologyMode.HYBRID: "混合模式",
        }
        return descriptions.get(self._bus.topology, "未知模式")
