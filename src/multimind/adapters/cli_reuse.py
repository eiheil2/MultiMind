"""① 官方 CLI 复用通道。

通过子进程调用官方 CLI（如 ``opencode``、``gemini-cli``），
复用其 OAuth 登录态，无需自行管理鉴权。

职责单一：上层（Orchestrator / ContextBuilder）已完成上下文组装，
adapter 只负责把 prompt 传给 CLI 并流式回读输出，**不再重复拼接上下文**。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shlex
import shutil
from typing import TYPE_CHECKING

from multimind.core.exceptions import AdapterError
from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, Message, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["CLIReuseAdapter"]

logger = logging.getLogger(__name__)

# provider 名 → CLI 命令模板（{prompt} 占位符会被替换为实际提示词）
_CLI_COMMAND_MAP: dict[str, str] = {
    "gemini-cli": "gemini -p {prompt}",
    "opencode": "opencode run {prompt}",
}


class CLIReuseAdapter(AIAdapter):
    """官方 CLI 复用适配器。

    通过 ``asyncio.create_subprocess_exec`` 调用已安装的官方 CLI 工具，
    复用其登录态。适用于已有 OAuth 登录的场景（如 Gemini CLI 1000 req/day）。

    命令模板中含 ``{prompt}`` 占位符时，提示词作为参数传入；
    否则提示词写入子进程 stdin（如 ``cat``、``ollama run`` 风格）。

    Attributes:
        _cli_command: CLI 命令模板（可用 ``config.endpoint`` 覆盖）。
        _timeout: 子进程超时（秒）。
    """

    channel_type = ChannelType.CLI_REUSE

    def __init__(
        self,
        config: ProviderConfig,
        *,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(config)
        self._cli_command: str = config.endpoint or self._detect_cli_command()
        self._timeout = timeout

    def _detect_cli_command(self) -> str:
        """根据 provider 名探测 CLI 命令模板。"""
        return _CLI_COMMAND_MAP.get(self.config.name, self.config.name)

    def _build_argv(self, prompt: str) -> tuple[list[str], bool]:
        """构造子进程参数列表。

        Args:
            prompt: 用户提示词。

        Returns:
            ``(argv, use_stdin)``：命令含 ``{prompt}`` 占位符时替换为
            提示词（按argv元素替换，避免引号转义问题），``use_stdin``
            为 ``False``；否则提示词走 stdin。
        """
        parts = shlex.split(self._cli_command)
        if any("{prompt}" in part for part in parts):
            return [part.replace("{prompt}", prompt) for part in parts], False
        return parts, True

    async def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """通过 CLI 子进程流式输出。

        Args:
            prompt: 用户提示词（上下文已由上层组装进 prompt）。
            context: 群聊历史（已注入 prompt，此处不再重复拼接）。
            **kwargs: 支持 ``timeout`` 覆盖。

        Raises:
            AdapterError: CLI 未安装 / 启动失败 / 非零退出码 / 超时。
        """
        argv, use_stdin = self._build_argv(prompt)
        if not argv:
            raise AdapterError(f"CLI provider '{self.config.name}' has empty command")
        if shutil.which(argv[0]) is None:
            raise AdapterError(
                f"CLI '{argv[0]}' not found. Install it first, "
                f"or set a custom command in the provider endpoint."
            )

        logger.debug("CLIReuse '%s' spawning: %s", self.config.name, argv[0])
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if use_stdin else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            raise AdapterError(f"Failed to start CLI '{argv[0]}': {e}") from e

        raw_timeout = kwargs.get("timeout", self._timeout)
        timeout = (
            float(raw_timeout)
            if isinstance(raw_timeout, (int, float, str))
            else self._timeout
        )
        # 注：兼容 Python 3.10 —— asyncio.timeout() 是 3.11+ API，
        # 这里用 wait_for 对每段读取单独限时。
        if use_stdin and proc.stdin is not None:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()

        try:
            assert proc.stdout is not None
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(256), timeout)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    raise AdapterError(
                        f"CLI '{argv[0]}' timed out after {timeout:.0f}s"
                    ) from None
                if not chunk:
                    break
                yield chunk.decode(errors="replace")

            stderr = await proc.stderr.read() if proc.stderr is not None else b""
            returncode = await proc.wait()
        except AdapterError:
            raise
        except Exception as e:
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            raise AdapterError(f"CLI '{argv[0]}' read failed: {e}") from e

        if returncode != 0:
            detail = stderr.decode(errors="replace").strip()[:200]
            raise AdapterError(f"CLI '{argv[0]}' exited with code {returncode}: {detail}")

        self.record_usage()
        logger.debug("CLIReuse '%s' completed", self.config.name)
