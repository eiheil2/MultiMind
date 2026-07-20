"""② 免费 API 通道。

通过 ``httpx`` 调用免费 API（Groq、Cerebras、SiliconFlow 等），
使用 API Key 鉴权。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, Message, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["APIClientAdapter"]

logger = logging.getLogger(__name__)


class APIClientAdapter(AIAdapter):
    """免费 API 适配器。

    通过 HTTP 调用免费 API 端点，支持流式 SSE 响应。
    适用于有 API Key 的免费 provider（如 Groq 14400 req/day）。
    """

    channel_type = ChannelType.API_CLIENT

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.api_key:
            logger.warning("API provider '%s' has no api_key set", config.name)
        self._endpoint: str = config.endpoint or self._default_endpoint()

    def _default_endpoint(self) -> str:
        """根据 provider 名推断默认 API 端点。"""
        defaults = {
            "groq": "https://api.groq.com/openai/v1/chat/completions",
            "cerebras": "https://api.cerebras.ai/v1/chat/completions",
            "siliconflow": "https://api.siliconflow.cn/v1/chat/completions",
        }
        return defaults.get(self.config.name, "")

    async def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """通过 HTTP API 流式输出。

        Args:
            prompt: 用户提示词。
            context: 群聊历史（转换为 messages 数组）。
            **kwargs: 透传给 API 的额外参数。

        Raises:
            AdapterError: API 调用失败。
        """
        logger.debug("API '%s' processing prompt: %s", self.config.name, prompt[:80])

        # TODO: 实际实现 — httpx.AsyncClient + SSE 流式解析
        # 框架验证：模拟 API 流式输出
        yield f"[API·{self.config.name}] "
        await asyncio.sleep(0.03)
        response = f"收到指令：{prompt[:40]}。通过API密钥调用中..."
        for word in response.split():
            yield word + " "
            await asyncio.sleep(0.015)

        self.record_usage()
        logger.debug("API '%s' completed", self.config.name)
