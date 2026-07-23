"""能力标签匹配 — provider 带 tags，任务也带标签。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multimind.adapters.registry import ProviderRegistry

__all__ = ["TagMatcher"]


class TagMatcher:
    """能力标签匹配器。

    根据任务所需标签筛选可用 provider。
    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def match(self, required_tags: list[str] | None = None) -> list[str]:
        """返回匹配所有所需标签的 provider 名称列表。

        Args:
            required_tags: 任务所需的能力标签。None 表示无要求。

        Returns:
            匹配的 provider 名称列表。
        """
        if not required_tags:
            return list(self._registry.all().keys())

        matched: list[str] = []
        for name, adapter in self._registry.all().items():
            if all(tag in adapter.config.tags for tag in required_tags):
                matched.append(name)
        return matched
