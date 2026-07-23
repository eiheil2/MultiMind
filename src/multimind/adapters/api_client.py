"""② 免费 API 通道。

通过 ``httpx`` 调用 OpenAI 兼容的免费 API（Groq、Cerebras、
SiliconFlow 等），使用 API Key 鉴权，SSE 流式解析响应。
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

__all__ = ["APIClientAdapter"]

logger = logging.getLogger(__name__)


class APIClientAdapter(AIAdapter):
    """免费 API 适配器（OpenAI 兼容协议）。

    通过 HTTP 调用 API 端点，SSE 流式读取。
    适用于有 API Key 的 provider（如 Groq 14400 req/day）。

    Attributes:
        _endpoint: 聊天补全端点 URL。
        _transport: httpx 传输层（测试可注入 ``MockTransport``）。
        _timeout: 请求超时（秒）。
    """

    channel_type = ChannelType.API_CLIENT

    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(config)
        if not config.api_key:
            logger.warning("API provider '%s' has no api_key set", config.name)
        self._endpoint: str = config.endpoint or self._default_endpoint()
        self._transport = transport
        self._timeout = timeout

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
            **kwargs: 支持 ``model`` / ``temperature`` / ``max_tokens`` 覆盖。

        Raises:
            AdapterError: 缺少 api_key / 端点未配置 / HTTP 或网络错误。
        """
        if not self.config.api_key:
            raise AdapterError(
                f"API provider '{self.config.name}' requires an api_key "
                f"(set via: /apikey {self.config.name} <key>)"
            )
        if not self._endpoint:
            raise AdapterError(f"API provider '{self.config.name}' has no endpoint configured")

        payload: dict[str, object] = {
            "model": str(kwargs.get("model") or self.config.model or "default"),
            "messages": messages_from_context(context, prompt),
            "stream": True,
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]
        headers = {"Authorization": f"Bearer {self.config.api_key}"}

        logger.debug("API '%s' POST %s", self.config.name, self._endpoint)
        try:
            async with (
                httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client,
                client.stream("POST", self._endpoint, json=payload, headers=headers) as resp,
            ):
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")[:200]
                    raise AdapterError(f"API '{self.config.name}' HTTP {resp.status_code}: {body}")
                async for chunk in iter_openai_sse(resp):
                    yield chunk
        except httpx.HTTPError as e:
            raise AdapterError(f"API '{self.config.name}' request failed: {e}") from e

        self.record_usage()
        logger.debug("API '%s' completed", self.config.name)
