"""角色定义 — Leader / Dispatcher / Executor。

角色 prompt 模板默认从 ``~/.multimind/prompts/*.md`` 加载，
未加载时使用内置默认模板。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from multimind.core.constants import PROMPTS_DIR
from multimind.core.types import Permission, RoleMode

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "RoleTier",
    "Role",
    "ROLE_PROMPTS",
    "default_roles",
    "load_custom_prompt",
    "save_custom_prompt",
    "reset_custom_prompt",
    "get_effective_prompt",
]

logger = logging.getLogger(__name__)

RoleTier = Literal["leader", "dispatcher", "executor"]

# 内置默认提示词（英文，回复语言由 Orchestrator.language 控制）
ROLE_PROMPTS: dict[RoleTier, str] = {
    "leader": (
        "You are the Leader of a group chat. Your role: understand user intent, "
        "formulate an overall plan, and break down tasks for the Dispatcher. "
        "You only make decisions and plans — you do not execute code directly. "
        "Be concise and give clear task breakdowns."
    ),
    "dispatcher": (
        "You are the Dispatcher. Your role: receive subtasks from the Leader, "
        "assign them to suitable Executors, and aggregate Executor results. "
        "You can dispatch multiple subtasks in parallel. "
        "Report in a structured manner."
    ),
    "executor": (
        "You are an Executor. Your role: execute specific tasks "
        "(write code, search information, run tests). "
        "Report results when done. If you encounter problems, report promptly — don't get stuck."
    ),
}

# 角色 tier 的中文标签（用于 UI 显示）
TIER_LABELS: dict[RoleTier, str] = {
    "leader": "指挥官 (Leader)",
    "dispatcher": "调度员 (Dispatcher)",
    "executor": "执行者 (Executor)",
}


def _prompt_file(tier: RoleTier) -> Path:
    """返回指定角色 tier 的提示词文件路径。"""
    return PROMPTS_DIR / f"{tier}.md"


def load_custom_prompt(tier: RoleTier) -> str | None:
    """从文件加载自定义提示词。

    Args:
        tier: 角色 tier (leader / dispatcher / executor)。

    Returns:
        自定义提示词内容，文件不存在则返回 None。
    """
    path = _prompt_file(tier)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as e:
        logger.warning("Failed to read prompt file %s: %s", path, e)
        return None


def save_custom_prompt(tier: RoleTier, content: str) -> Path:
    """保存自定义提示词到文件。

    Args:
        tier: 角色 tier。
        content: 提示词内容。

    Returns:
        保存的文件路径。
    """
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _prompt_file(tier)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    logger.info("Saved custom prompt for %s to %s", tier, path)
    return path


def reset_custom_prompt(tier: RoleTier) -> bool:
    """删除自定义提示词文件，恢复为内置默认。

    Args:
        tier: 角色 tier。

    Returns:
        True 表示已删除文件，False 表示文件本就不存在。
    """
    path = _prompt_file(tier)
    if path.exists():
        path.unlink()
        logger.info("Reset prompt for %s (deleted %s)", tier, path)
        return True
    return False


def get_effective_prompt(tier: RoleTier) -> str:
    """获取生效的提示词：优先自定义文件，回退内置默认。

    Args:
        tier: 角色 tier。

    Returns:
        提示词内容。
    """
    custom = load_custom_prompt(tier)
    if custom:
        return custom
    return ROLE_PROMPTS.get(tier, "")


def is_custom(tier: RoleTier) -> bool:
    """检查指定角色是否使用了自定义提示词。"""
    return _prompt_file(tier).exists()


@dataclass(slots=True)
class Role:
    """角色定义。

    Attributes:
        name: 角色显示名。
        tier: 角色层级（leader / dispatcher / executor）。
        provider: 绑定的 provider 名称。
        mode: 运行模式（explore / plan / act）。
        permission: 工具调用权限级别。
        prompt: 系统 prompt（空则从文件/默认加载）。
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
            # 优先加载自定义提示词文件，回退内置默认
            self.prompt = get_effective_prompt(self.tier)

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
