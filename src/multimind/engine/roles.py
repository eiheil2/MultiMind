"""角色定义 — Leader / Dispatcher / Executor。

角色 prompt 模板默认从 ``~/.multimind/prompts/*.md`` 加载，
未加载时使用内置默认模板。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from multimind.core.types import Permission, RoleMode

__all__ = ["RoleTier", "Role", "ROLE_PROMPTS", "default_roles"]

RoleTier = Literal["leader", "dispatcher", "executor"]

# 角色 prompt 模板（实际从 ~/.multimind/prompts/*.md 加载）
ROLE_PROMPTS: dict[RoleTier, str] = {
    "leader": (
        "你是群聊的 Leader。职责：理解用户意图、制定总体方案、把任务拆分给 Dispatcher。"
        "你只做决策和方案，不直接执行代码。发言时简明扼要，给出明确的任务拆分。"
    ),
    "dispatcher": (
        "你是 Dispatcher。职责：接收 Leader 的子任务、分配给合适的 Executor、汇总 Executor 结果。"
        "你可以并行派发多个子任务。汇报时结构化呈现。"
    ),
    "executor": (
        "你是 Executor。职责：执行具体任务（写代码、查资料、跑测试）。"
        "完成后报告结果。遇到问题及时上报，不要卡住。"
    ),
}


@dataclass(slots=True)
class Role:
    """角色定义。

    Attributes:
        name: 角色显示名。
        tier: 角色层级（leader / dispatcher / executor）。
        provider: 绑定的 provider 名称。
        mode: 运行模式（explore / plan / act）。
        permission: 工具调用权限级别。
        prompt: 系统 prompt（空则使用默认模板）。
        max_concurrent: 最大并发子循环数。
    """

    name: str
    tier: RoleTier
    provider: str
    mode: RoleMode = RoleMode.ACT
    permission: Permission = Permission.AUTO
    prompt: str = ""
    max_concurrent: int = 1

    def __post_init__(self) -> None:
        if not self.prompt:
            self.prompt = ROLE_PROMPTS.get(self.tier, "")

    def __repr__(self) -> str:
        return (
            f"<Role {self.name} "
            f"tier={self.tier} "
            f"provider={self.provider} "
            f"mode={self.mode.value}>"
        )


def default_roles() -> list[Role]:
    """默认角色编排：1 Leader + 1 Dispatcher + 2 Executor。"""
    return [
        Role(
            name="指挥官",
            tier="leader",
            provider="gemini-cli",
            mode=RoleMode.PLAN,
            permission=Permission.ASK,
        ),
        Role(
            name="调度员",
            tier="dispatcher",
            provider="groq",
            mode=RoleMode.PLAN,
            permission=Permission.ASK,
        ),
        Role(
            name="执行者A",
            tier="executor",
            provider="opencode-free",
            mode=RoleMode.ACT,
            permission=Permission.AUTO,
        ),
        Role(
            name="执行者B",
            tier="executor",
            provider="ollama-local",
            mode=RoleMode.ACT,
            permission=Permission.AUTO,
        ),
    ]
