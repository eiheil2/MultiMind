"""⑤ 本地兜底通道。

通过 Ollama / LM Studio 调用本地模型，无需网络，完全离线。
作为所有免费额度耗尽后的最终兜底。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from multimind.adapters.streaming import iter_ollama_ndjson, messages_from_context
from multimind.core.exceptions import AdapterError
from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, Message, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["LocalAdapter"]

logger = logging.getLogger(__name__)


class LocalAdapter(AIAdapter):
    """本地模型适配器（Ollama 协议）。

    通过 Ollama HTTP API（默认 ``localhost:11434``）调用本地模型，
    NDJSON 流式读取。完全离线，隐私安全，作为免费额度耗尽后的兜底通道。

    Attributes:
        _endpoint: Ollama 聊天端点 URL。
        _transport: httpx 传输层（测试可注入 ``MockTransport``）。
        _timeout: 请求超时（秒；本地首 token 可能较慢，默认较长）。
    """

    channel_type = ChannelType.LOCAL

    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(config)
        self._endpoint: str = config.endpoint or "http://localhost:11434/api/chat"
        self._transport = transport
        self._timeout = timeout

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
            **kwargs: 支持 ``model`` / ``temperature`` 覆盖。

        Raises:
            AdapterError: 本地服务不可达 / HTTP 错误。
        """
        payload: dict[str, object] = {
            "model": str(kwargs.get("model") or self.config.model or "llama3.2"),
            "messages": messages_from_context(context, prompt),
            "stream": True,
        }
        if "temperature" in kwargs:
            payload["options"] = {"temperature": kwargs["temperature"]}

        logger.debug("Local '%s' POST %s", self.config.name, self._endpoint)
        try:
            async with (
                httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client,
                client.stream("POST", self._endpoint, json=payload) as resp,
            ):
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")[:200]
                    raise AdapterError(
                        f"Local model '{self.config.name}' HTTP {resp.status_code}: {body}"
                    )
                async for chunk in iter_ollama_ndjson(resp):
                    yield chunk
        except httpx.HTTPError as e:
            raise AdapterError(
                f"Local model '{self.config.name}' unavailable at "
                f"{self._endpoint} (is Ollama running?): {e}"
            ) from e

        self.record_usage()
        logger.debug("Local '%s' completed", self.config.name)
