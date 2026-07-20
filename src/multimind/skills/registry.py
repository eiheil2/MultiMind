"""Skill 注册表 — 管理 skill 的注册、查找和索引。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multimind.skills.base import Skill, SkillManifest

__all__ = ["SkillRegistry", "get_skill_registry", "reset_skill_registry"]

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Skill 注册表。

    负责管理所有已加载的 skill 实例，提供按名称、标签查找。
    非线程安全，应在单线程或 asyncio 上下文中使用。
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._manifests: dict[str, SkillManifest] = {}

    def register(self, skill: Skill) -> None:
        """注册一个 skill 实例。

        Args:
            skill: Skill 实例。
        """
        name = skill.name
        if name in self._skills:
            logger.warning("Overwriting existing skill: %s", name)
        self._skills[name] = skill
        self._manifests[name] = skill.manifest
        logger.info(
            "Registered skill: %s (source=%s, tags=%s)",
            name,
            skill.manifest.source_type.value,
            skill.manifest.tags,
        )

    def get(self, name: str) -> Skill | None:
        """按名称获取 skill。"""
        return self._skills.get(name)

    def all(self) -> dict[str, Skill]:
        """返回所有已注册 skill 的副本。"""
        return dict(self._skills)

    def by_tag(self, tag: str) -> list[Skill]:
        """按能力标签筛选 skill。"""
        return [
            s for s in self._skills.values()
            if tag in s.manifest.tags
        ]

    def manifests(self) -> list[SkillManifest]:
        """返回所有 skill 的清单（用于索引摘要）。"""
        return list(self._manifests.values())

    def index_summary(self) -> list[str]:
        """返回轻量索引摘要（用于模型自判）。

        每个元素格式：``name: description [tags]``
        """
        return [s.describe() for s in self._skills.values()]

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills


# ── 单例 ────────────────────────────────────────────────────────
_registry = SkillRegistry()


def get_skill_registry() -> SkillRegistry:
    """获取全局 SkillRegistry 单例。"""
    return _registry


def reset_skill_registry() -> None:
    """重置注册表（主要用于测试）。"""
    global _registry  # noqa: PLW0603
    _registry = SkillRegistry()
