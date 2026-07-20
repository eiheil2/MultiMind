"""编排引擎 — while-loop 内核 + 群聊总线 + 动态拓扑。

核心设计（借鉴 Claude Code while-loop + Grok Build Coordinator）：
- 每个角色的单轮交互是一个 ``while not done`` 循环。
- Leader 循环 → Dispatcher 循环 → Executor 循环（可嵌套）。
- 群聊总线串联所有角色循环，共享上下文。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from multimind.adapters.registry import ProviderRegistry, get_registry
from multimind.core.exceptions import AdapterError
from multimind.core.types import Message
from multimind.engine.groupchat import GroupChatBus, TopologyMode
from multimind.engine.roles import Role, default_roles
from multimind.engine.topology import TopologyManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["Orchestrator"]

logger = logging.getLogger(__name__)


class Orchestrator:
    """编排引擎 — 驱动多角色群聊协作。

    Attributes:
        roles: 角色列表。
        registry: Provider 注册表。
        bus: 群聊消息总线。
        topology: 拓扑管理器。
    """

    def __init__(
        self,
        roles: list[Role] | None = None,
        registry: ProviderRegistry | None = None,
        bus: GroupChatBus | None = None,
    ) -> None:
        self.roles = roles or default_roles()
        self.registry = registry or get_registry()
        self.bus = bus or GroupChatBus()
        self.topology = TopologyManager(self.bus)

    @property
    def leaders(self) -> list[Role]:
        """所有 Leader 角色列表。"""
        return [r for r in self.roles if r.tier == "leader"]

    @property
    def dispatchers(self) -> list[Role]:
        """所有 Dispatcher 角色列表。"""
        return [r for r in self.roles if r.tier == "dispatcher"]

    @property
    def executors(self) -> list[Role]:
        """所有 Executor 角色列表。"""
        return [r for r in self.roles if r.tier == "executor"]

    async def run(
        self,
        user_input: str,
        max_rounds: int = 10,
    ) -> AsyncIterator[str]:
        """运行一轮群聊协作，流式输出。

        Args:
            user_input: 用户输入。
            max_rounds: 最大轮次上限。

        Yields:
            流式输出的文本片段。
        """
        # 用户消息入总线
        await self.bus.broadcast("用户", user_input)
        yield f"👤 用户: {user_input}\n"

        for round_num in range(1, max_rounds + 1):
            if self.topology.mode == TopologyMode.LAYERED:
                # 分层模式：只跑 Leader
                async for chunk in self._run_role_loop(self.leaders[0], user_input, round_num):
                    yield chunk
            else:
                # 扁平模式：所有角色依次发言
                for role in self.roles:
                    async for chunk in self._run_role_loop(role, user_input, round_num):
                        yield chunk

            # 简化：2 轮后结束（框架验证）
            if round_num >= 2:
                yield f"\n✅ 群聊协作完成（{round_num} 轮）\n"
                break

    async def _run_role_loop(
        self,
        role: Role,
        task: str,
        round_num: int,
    ) -> AsyncIterator[str]:
        """单角色 while-loop（观察→思考→发言→工具→再观察）。

        Args:
            role: 角色定义。
            task: 当前任务。
            round_num: 当前轮次。

        Yields:
            流式输出的文本片段。
        """
        provider = self.registry.get(role.provider)
        if provider is None:
            yield f"⚠️ {role.name}: provider '{role.provider}' 未注册\n"
            logger.error("Provider '%s' not registered for role '%s'", role.provider, role.name)
            return

        # 组装上下文
        context = self.bus.context_for(role.name)
        prompt = self._build_prompt(role, task, context)

        yield f"\n🔴 [{role.name} · {role.tier} · {role.provider}]"

        collected: list[str] = []
        try:
            async for chunk in provider.ask(prompt, context):
                yield chunk
                collected.append(chunk)
        except AdapterError as e:
            yield f"\n⚠️ 适配器错误: {e}"
            logger.exception("Adapter error for role %s", role.name)
            return

        full_reply = "".join(collected)
        await self.bus.post(Message(
            role=role.name,
            content=full_reply,
            channel=role.provider,
            mode=role.mode,
        ))
        yield "\n"

    def _build_prompt(self, role: Role, task: str, context: list[Message]) -> str:
        """为角色构建完整 prompt。"""
        prompt = f"[{role.prompt}]\n\n任务: {task}\n\n群聊历史:\n"
        for msg in context[-5:]:
            prompt += f"  {msg.role}: {msg.content[:60]}\n"
        prompt += f"\n请以 {role.name} 身份简短发言（1-2句）："
        return prompt
