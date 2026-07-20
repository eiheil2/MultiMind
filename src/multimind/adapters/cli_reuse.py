"""① 官方 CLI 复用通道。

通过子进程调用官方 CLI（如 ``opencode``、``gemini-cli``），
复用其 OAuth 登录态，无需自行管理鉴权。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, Message, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["CLIReuseAdapter"]

logger = logging.getLogger(__name__)


class CLIReuseAdapter(AIAdapter):
    """官方 CLI 复用适配器。

    通过 ``subprocess`` 调用已安装的官方 CLI 工具，复用其登录态。
    适用于已有 OAuth 登录的场景（如 Gemini CLI 1000 req/day）。
    """

    channel_type = ChannelType.CLI_REUSE

    def __init__(self, config: ProviderConfig, quota: object = None) -> None:
        super().__init__(config, quota=quota)
        self._cli_command: str = config.endpoint or self._detect_cli_command()

    def _detect_cli_command(self) -> str:
        """根据 provider 名探测 CLI 命令。"""
        mapping = {
            "gemini-cli": "gemini",
            "opencode": "opencode",
        }
        return mapping.get(self.config.name, self.config.name)

    async def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """通过 CLI 子进程流式输出。

        Args:
            prompt: 用户提示词。
            context: 群聊历史（注入到 CLI stdin）。
            **kwargs: 透传给 CLI 的额外参数。
        """
        logger.debug("CLIReuse '%s' processing prompt: %s", self.config.name, prompt[:80])

        # TODO: 实际实现 — subprocess + stdin/stdout 流式
        # 框架验证：模拟 CLI 流式输出
        await asyncio.sleep(0.05)
        response = f"Received task via CLI channel ({self.config.name}). Processing with official CLI tool... Acknowledged."
        for word in response.split():
            yield word + " "
            await asyncio.sleep(0.02)

        self.record_usage()
        logger.debug("CLIReuse '%s' completed", self.config.name)
