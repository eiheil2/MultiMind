"""抽象接口定义（协议层）。

使用 ``Protocol`` 定义接口，实现松耦合的依赖注入。
具体实现在 ``adapters`` / ``memory`` / ``tools`` 等子系统中。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from multimind.core.types import Message, ProviderConfig

__all__ = ["AIAdapter", "MemoryStore", "ToolProvider"]

logger = logging.getLogger(__name__)


class AIAdapter(ABC):
    """AI 适配器抽象基类 — 所有通道实现此接口。

    子类需实现 ``ask()`` 方法，提供流式输出。上层通过此接口
    无感调用不同通道的 AI。

    Attributes:
        channel_type: 通道类型（子类覆盖）。
        config: Provider 配置。
    """

    channel_type: ChannelType  # type: ignore[name-defined]  # noqa: F821

    def __init__(self, config: ProviderConfig, quota: object = None) -> None:
        self.config = config
        # 额度交给统一的 QuotaTracker 管理（单一数据源），避免各适配器
        # 各算各的、与 SQLite 额度库脱钩。注册表会注入共享实例；
        # 单独构造时延迟创建一个内存实例作为兜底。
        if quota is not None:
            self._quota = quota
        else:
            self._quota = _default_quota_tracker()

    @abstractmethod
    async def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """流式输出回答。

        Args:
            prompt: 用户提示词。
            context: 群聊历史消息（用于上下文注入）。
            **kwargs: 通道特定参数。

        Yields:
            流式输出的文本片段。
        """
        ...

    @property
    def remaining_quota(self) -> int:
        """剩余每日额度（委托 QuotaTracker；-1 表示无限）。"""
        return self._quota.remaining(self.config.name, self.config.daily_quota)

    def record_usage(self, tokens: int = 1) -> None:
        """记录用量（写入共享 QuotaTracker，可跨进程持久化）。"""
        self._quota.record(self.config.name, tokens)
        logger.debug(
            "Provider %s usage recorded: +%d tokens (remaining: %d)",
            self.config.name,
            tokens,
            self.remaining_quota,
        )

    @property
    def _used_today(self) -> int:
        """今日已用量（视图，统一取自共享 QuotaTracker，单一数据源）。

        保留该只读属性以兼容既有调用方/测试对用量计数的观察，
        避免适配器各自维护一份与额度库脱钩的计数。
        """
        return self._quota.get_used(self.config.name)

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"name={self.config.name} "
            f"ch={self.channel_type.value} "
            f"remaining={self.remaining_quota}>"
        )


@runtime_checkable
class MemoryStore(Protocol):
    """记忆存储接口（协议）。

    任何实现了此协议的对象都可作为记忆后端。
    """

    def add_short_term(self, msg: Message) -> None:
        """添加短期记忆。"""
        ...

    def assemble_context(self, role_name: str, max_tokens: int) -> list[Message]:
        """为角色组装上下文。"""
        ...


@runtime_checkable
class ToolProvider(Protocol):
    """工具提供者接口（协议）。

    用于 MCP 工具协议和沙箱工具的统一抽象。
    """

    async def execute(self, tool_name: str, arguments: dict[str, object]) -> str:
        """执行工具调用。"""
        ...


def _default_quota_tracker() -> object:
    """延迟创建一个内存版 QuotaTracker，作为独立构造适配器的兜底。

    延迟导入以避免 ``core.interfaces`` 与 ``routing.quota`` 之间的顶层
    循环依赖；注册表注入共享实例时不会走到这里。
    """
    from multimind.routing.quota import QuotaTracker

    return QuotaTracker()
