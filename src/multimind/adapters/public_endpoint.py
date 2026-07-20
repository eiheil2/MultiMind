"""④ 公共端点通道（零鉴权）。

无需登录或 API Key 的公共端点，如 OpenCode 内置的零配置模型。
``multimind chat`` 开箱即用，无需任何配置。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, Message, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["PublicEndpointAdapter"]

logger = logging.getLogger(__name__)


class PublicEndpointAdapter(AIAdapter):
    """公共端点适配器（零鉴权）。

    直接调用无需认证的公共 API 端点，是零配置启动的基础。
    适用于 OpenCode 内置免费模型等场景。
    """

    channel_type = ChannelType.PUBLIC_ENDPOINT

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._endpoint: str = config.endpoint or "https://api.opencode.ai/v1/chat/completions"

    async def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """通过公共端点流式输出。

        Args:
            prompt: 用户提示词。
            context: 群聊历史。
            **kwargs: 透传给端点的额外参数。
        """
        logger.debug("Public '%s' processing prompt: %s", self.config.name, prompt[:80])

        # TODO: 实际实现 — httpx + 无 Authorization header
        # 框架验证：模拟公共端点流式输出
        await asyncio.sleep(0.02)
        response = f"Received task via public endpoint ({self.config.name}). Zero-auth processing complete."
        for word in response.split():
            yield word + " "
            await asyncio.sleep(0.01)

        self.record_usage()
        logger.debug("Public '%s' completed", self.config.name)
