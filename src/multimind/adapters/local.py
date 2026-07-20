"""⑤ 本地兜底通道。

通过 Ollama / LM Studio 调用本地模型，无需网络，完全离线。
作为所有免费额度耗尽后的最终兜底。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, Message, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["LocalAdapter"]

logger = logging.getLogger(__name__)


class LocalAdapter(AIAdapter):
    """本地模型适配器。

    通过 Ollama HTTP API（默认 ``localhost:11434``）调用本地模型。
    完全离线，隐私安全，作为免费额度耗尽后的兜底通道。
    """

    channel_type = ChannelType.LOCAL

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._endpoint: str = config.endpoint or "http://localhost:11434/api/chat"

    async def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """通过本地 Ollama 流式输出。

        Args:
            prompt: 用户提示词。
            context: 群聊历史。
            **kwargs: 透传给 Ollama 的额外参数。
        """
        logger.debug("Local '%s' processing prompt: %s", self.config.name, prompt[:80])

        # TODO: 实际实现 — httpx + Ollama streaming API
        # 框架验证：模拟本地推理流式输出
        await asyncio.sleep(0.08)
        response = f"Received task via local model ({self.config.name}). Offline inference complete."
        for word in response.split():
            yield word + " "
            await asyncio.sleep(0.025)

        self.record_usage()
        logger.debug("Local '%s' completed", self.config.name)
