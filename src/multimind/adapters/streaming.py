"""流式 HTTP 工具 — OpenAI SSE / Ollama NDJSON 解析与消息转换。

供 ``APIClientAdapter`` / ``PublicEndpointAdapter`` / ``LocalAdapter``
复用的内部工具，集中处理：

- ``Message`` 列表 → OpenAI ``messages`` 数组的角色映射。
- OpenAI 兼容 SSE（``data: {...}`` / ``data: [DONE]``）的增量解析。
- Ollama NDJSON（每行一个 JSON 对象）的增量解析。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import httpx

    from multimind.core.types import Message

__all__ = [
    "iter_ollama_ndjson",
    "iter_openai_sse",
    "messages_from_context",
]

logger = logging.getLogger(__name__)


def messages_from_context(
    context: list[Message] | None,
    prompt: str,
) -> list[dict[str, str]]:
    """把群聊 ``Message`` 列表转换为 OpenAI 风格 ``messages`` 数组。

    角色映射：

    - ``user`` / ``system`` → 原样。
    - ``[...]`` 标记的合成层消息（``[关键帧]`` / ``[事实]`` /
      ``[记忆·mid]`` 等）→ ``system``（信息性上下文）。
    - 其余（各 AI 角色名）→ ``assistant``。

    Args:
        context: 已由 ContextBuilder 组装的上下文。
        prompt: 当前用户提示词（追加为最后一条 user 消息）。

    Returns:
        OpenAI 兼容的 messages 数组。
    """
    messages: list[dict[str, str]] = []
    for msg in context or []:
        if msg.role in ("user", "system"):
            role = msg.role
        elif msg.role.startswith("["):
            role = "system"
        else:
            role = "assistant"
        messages.append({"role": role, "content": msg.content})
    messages.append({"role": "user", "content": prompt})
    return messages


def parse_openai_sse_line(line: str) -> tuple[str, bool]:
    """解析单行 OpenAI SSE，返回 ``(content, done)``。

    非 data 行、空 data、无法解析的 JSON 都返回 ``("", False)``；
    ``data: [DONE]`` 返回 ``("", True)``。
    """
    line = line.strip()
    if not line.startswith("data:"):
        return "", False
    data = line[len("data:") :].strip()
    if not data:
        return "", False
    if data == "[DONE]":
        return "", True
    try:
        obj: dict[str, Any] = json.loads(data)
    except ValueError:
        logger.debug("Skipping unparseable SSE data: %.80s", data)
        return "", False
    for choice in obj.get("choices", []):
        delta = choice.get("delta") or {}
        chunk = delta.get("content") or choice.get("text") or ""
        if chunk:
            return str(chunk), False
    return "", False


async def iter_openai_sse(resp: httpx.Response) -> AsyncIterator[str]:
    """从 OpenAI 兼容 SSE 响应中流式提取文本片段。

    Args:
        resp: 处于流式读取状态的 ``httpx.Response``。

    Yields:
        delta content 片段；遇到 ``[DONE]`` 停止。
    """
    async for line in resp.aiter_lines():
        chunk, done = parse_openai_sse_line(line)
        if done:
            return
        if chunk:
            yield chunk


async def iter_ollama_ndjson(resp: httpx.Response) -> AsyncIterator[str]:
    """从 Ollama NDJSON 响应中流式提取文本片段。

    每行形如 ``{"message": {"role": "assistant", "content": "..."},
    "done": false}``；``done: true`` 时停止。

    Args:
        resp: 处于流式读取状态的 ``httpx.Response``。

    Yields:
        message content 片段。
    """
    async for line in resp.aiter_lines():
        line = line.strip()
        if not line:
            continue
        try:
            obj: dict[str, Any] = json.loads(line)
        except ValueError:
            logger.debug("Skipping unparseable NDJSON line: %.80s", line)
            continue
        message = obj.get("message") or {}
        chunk = message.get("content") or ""
        if chunk:
            yield str(chunk)
        if obj.get("done"):
            return
