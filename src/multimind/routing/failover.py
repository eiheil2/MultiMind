"""故障转移链 — 失败/429/超时自动切下一家。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multimind.adapters.registry import ProviderRegistry

__all__ = ["FailoverChain"]

logger = logging.getLogger(__name__)


class FailoverChain:
    """故障转移链。

    按 provider 优先级维护一个有序的候选列表，
    当当前 provider 失败时自动切换到下一个。
    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def get_chain(self, required_tag: str | None = None) -> list[str]:
        """获取故障转移链。

        Args:
            required_tag: 可选的能力标签过滤。

        Returns:
            按优先级排序的 provider 名称列表。
        """
        candidates = self._registry.available(required_tag)
        return [a.config.name for a in candidates]

    def next_available(self, failed: str, required_tag: str | None = None) -> str | None:
        """获取下一个可用的 provider。

        Args:
            failed: 已失败的 provider 名称。
            required_tag: 可选的能力标签过滤。

        Returns:
            下一个可用 provider 名称，无则返回 None。
        """
        chain = self.get_chain(required_tag)
        try:
            idx = chain.index(failed)
            if idx + 1 < len(chain):
                return chain[idx + 1]
        except ValueError:
            pass
        return chain[0] if chain else None
