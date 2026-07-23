"""④ 公共端点通道（零鉴权）。

无需登录或 API Key 的公共端点（OpenAI 兼容协议），如内置的
零配置推理端点。``multimind chat`` 开箱即用，无需任何配置。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from multimind.adapters.streaming import iter_openai_sse, messages_from_context
from multimind.core.exceptions import AdapterError
from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, Message, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["PublicEndpointAdapter"]

logger = logging.getLogger(__name__)


class PublicEndpointAdapter(AIAdapter):
    """公共端点适配器（零鉴权，OpenAI 兼容协议）。

    直接调用无需认证的公共 API 端点，是零配置启动的基础。

    Attributes:
        _endpoint: 聊天补全端点 URL。
        _transport: httpx 传输层（测试可注入 ``MockTransport``）。
        _timeout: 请求超时（秒）。
    """

    channel_type = ChannelType.PUBLIC_ENDPOINT

    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(config)
        self._endpoint: str = config.endpoint or "https://api.opencode.ai/v1/chat/completions"
        self._transport = transport
        self._timeout = timeout

    async def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """通过公共端点流式输出（无鉴权头）。

        Args:
            prompt: 用户提示词。
            context: 群聊历史。
            **kwargs: 支持 ``model`` / ``temperature`` / ``max_tokens`` 覆盖。

        Raises:
            AdapterError: 端点未配置 / HTTP 或网络错误。
        """
        if not self._endpoint:
            raise AdapterError(
                f"Public endpoint provider '{self.config.name}' has no endpoint configured"
            )

        payload: dict[str, object] = {
            "model": str(kwargs.get("model") or self.config.model or "default"),
            "messages": messages_from_context(context, prompt),
            "stream": True,
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]

        logger.debug("Public '%s' POST %s", self.config.name, self._endpoint)
        try:
            async with (
                httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client,
                client.stream("POST", self._endpoint, json=payload) as resp,
            ):
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")[:200]
                    raise AdapterError(
                        f"Public endpoint '{self.config.name}' HTTP {resp.status_code}: {body}"
                    )
                async for chunk in iter_openai_sse(resp):
                    yield chunk
        except httpx.HTTPError as e:
            raise AdapterError(f"Public endpoint '{self.config.name}' request failed: {e}") from e

        self.record_usage()
        logger.debug("Public '%s' completed", self.config.name)
