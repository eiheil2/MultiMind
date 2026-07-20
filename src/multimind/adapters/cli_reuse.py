"""① 官方 CLI 复用通道。

通过子进程调用官方 CLI（如 ``gemini``、``opencode``），
复用其 OAuth 登录态，无需自行管理鉴权。

支持的 CLI 及其 headless 调用方式：

- **gemini**（Google Gemini CLI）:
  ``gemini --prompt "..." --output-format json --yolo``
  免费额度：Google OAuth 登录 → 1000 req/天, 60 req/分。

- **opencode**（OpenCode CLI）:
  ``opencode --prompt "..." --output-format json --yolo``
  复用已配置的 provider（如 GitHub Copilot OAuth）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import TYPE_CHECKING

from multimind.core.exceptions import AdapterError
from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, Message, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["CLIReuseAdapter"]

logger = logging.getLogger(__name__)

# CLI 安装指引，用于 CLI 不存在时的优雅降级提示。
_INSTALL_HINTS: dict[str, str] = {
    "gemini": "npm install -g @anthropic-ai/gemini-cli",
    "opencode": "curl -fsSL https://opencode.ai/install | bash",
}


class CLIReuseAdapter(AIAdapter):
    """官方 CLI 复用适配器。

    通过 ``asyncio.create_subprocess_exec`` 调用已安装的官方 CLI 工具
    （headless 模式），复用其 OAuth 登录态。

    适用场景：

    - Gemini CLI: Google OAuth → 1000 req/天免费
    - OpenCode CLI: GitHub Copilot OAuth → 复用 Copilot 订阅的 GPT-4o/Claude
    """

    channel_type = ChannelType.CLI_REUSE

    def __init__(self, config: ProviderConfig, quota: object = None) -> None:
        super().__init__(config, quota=quota)
        self._cli_command: str = config.endpoint or self._detect_cli_command()
        self._cli_path: str | None = shutil.which(self._cli_command)

    def _detect_cli_command(self) -> str:
        """根据 provider 名探测 CLI 命令。"""
        mapping = {
            "gemini-cli": "gemini",
            "opencode": "opencode",
        }
        return mapping.get(self.config.name, self.config.name)

    @property
    def cli_available(self) -> bool:
        """CLI 是否已安装且可调用。"""
        return self._cli_path is not None

    async def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """通过 CLI 子进程 headless 模式获取回复。

        若 CLI 未安装则优雅降级：输出安装指引后退出。

        Args:
            prompt: 用户提示词。
            context: 群聊历史（注入到 CLI stdin，若 CLI 支持 stdin 输入）。
            **kwargs: 预留扩展。
        """
        logger.debug(
            "CLIReuse '%s' (cmd=%s) processing prompt: %s",
            self.config.name, self._cli_command, prompt[:80],
        )

        if self._cli_path is None:
            hint = _INSTALL_HINTS.get(self._cli_command, "请先安装 %s CLI" % self._cli_command)
            yield (
                f"[{self.config.name}] CLI 未安装（{self._cli_command}）。\n"
                f"安装命令: {hint}\n"
                f"安装后需完成 OAuth 登录即可使用。"
            )
            return

        try:
            response_text = await self._invoke_cli(prompt, context)
        except AdapterError as e:
            logger.warning("CLI '%s' failed: %s", self._cli_command, e)
            yield f"[{self.config.name}] 调用失败: {e}"
            return

        # 伪流式输出：按句子逐段 yield，保持与流式通道一致的体验
        if response_text:
            for sentence in _split_sentences(response_text):
                yield sentence
                await asyncio.sleep(0.01)

        self.record_usage()
        logger.debug("CLIReuse '%s' completed", self.config.name)

    async def _invoke_cli(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        """调用 CLI 子进程并返回解析后的响应文本。

        Args:
            prompt: 用户提示词。
            context: 可选的对话历史。

        Returns:
            解析后的响应文本。

        Raises:
            AdapterError: CLI 调用失败、超时或输出解析失败。
        """
        assert self._cli_path is not None  # 调用方已检查

        # 构建上下文注入到 prompt 中（headless 模式不支持 --context 标志）
        full_prompt = prompt
        if context:
            history_lines = []
            for msg in context[-6:]:  # 最近 6 条消息作为上下文
                role_label = "用户" if msg.role == "user" else msg.role
                history_lines.append(f"[{role_label}]: {msg.content[:200]}")
            if history_lines:
                full_prompt = (
                    "以下是对话历史（按时间顺序）:\n"
                    + "\n".join(history_lines)
                    + f"\n\n[当前任务]: {prompt}"
                )

        # gemini 和 opencode 都支持 --prompt / --output-format json / --yolo
        cmd = [
            self._cli_path,
            "--prompt", full_prompt,
            "--output-format", "json",
            "--yolo",  # 自动批准，非交互式必需
        ]

        logger.debug("Running CLI: %s", " ".join(cmd[:3]) + " ...")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120,
            )
        except asyncio.TimeoutError:
            raise AdapterError(
                f"CLI '{self._cli_command}' 超时（120s）。模型可能响应过慢，请重试。"
            ) from None
        except FileNotFoundError:
            raise AdapterError(
                f"CLI '{self._cli_command}' 可执行文件丢失。请重新安装。"
            ) from None
        except OSError as e:
            raise AdapterError(
                f"CLI '{self._cli_command}' 系统错误: {e}"
            ) from e

        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise AdapterError(
                f"CLI '{self._cli_command}' 退出码 {proc.returncode}: {stderr_text[:200]}"
            )

        raw_output = stdout.decode("utf-8", errors="replace").strip()
        if not raw_output:
            if stderr_text:
                raise AdapterError(f"CLI 无输出: {stderr_text[:200]}")
            raise AdapterError("CLI 返回空响应")

        return _parse_cli_output(raw_output, self._cli_command)


def _parse_cli_output(raw: str, cli_name: str) -> str:
    """解析 CLI JSON 输出，提取响应文本。

    兼容 gemini 和 opencode 的 JSON 输出格式。
    解析失败时降级为原始文本。
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("CLI '%s' 返回非 JSON 输出，使用原始文本", cli_name)
        return raw

    if not isinstance(data, dict):
        return raw

    # gemini headless: {"response": "...", "stats": {...}}
    if "response" in data:
        return str(data["response"])

    # opencode: {"text": "..."} 或 {"result": "..."}
    for key in ("text", "result", "content", "message"):
        if key in data:
            val = data[key]
            if isinstance(val, str):
                return val
            if isinstance(val, dict) and "content" in val:
                return str(val["content"])

    # 最后降级：整个 JSON 当字符串
    return raw


def _split_sentences(text: str) -> list[str]:
    """按句子边界分割文本，用于伪流式输出。

    保留标点不丢失，确保输出自然。
    """
    result: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in ".!?。！？\n" and len(buf) > 1:
            result.append(buf)
            buf = ""
    if buf:
        result.append(buf)
    return result or [text]
