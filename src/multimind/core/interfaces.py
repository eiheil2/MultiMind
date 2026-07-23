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

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._used_today: int = 0

    @abstractmethod
    def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """流式输出回答。

        注意：声明为普通 ``def`` 返回 ``AsyncIterator`` —— 子类以
        ``async def`` + ``yield``（异步生成器）实现此契约。若基类
        也用 ``async def``，类型检查器会把返回值解读为协程。

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
        """剩余每日额度（-1 表示无限）。"""
        if self.config.daily_quota < 0:
            return 999_999
        return max(0, self.config.daily_quota - self._used_today)

    def record_usage(self, tokens: int = 1) -> None:
        """记录用量。"""
        self._used_today += tokens
        logger.debug(
            "Provider %s usage recorded: +%d tokens (total: %d)",
            self.config.name,
            tokens,
            self._used_today,
        )

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
