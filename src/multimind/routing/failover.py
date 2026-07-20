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

        约定（与既有测试契约一致）：

        - 多 provider 链中，链尾失败时回绕到链首（始终提供一个重试候选）。
        - 单 provider 链中，失败即自身，无法转移到别的 provider，返回 None，
          避免调用方在 ``next_available`` 上无限重试同一个已失败的 provider。
        - 失败的 provider 不在链中时，回退到链首（只要不是它自己）。
        """
        chain = self.get_chain(required_tag)
        if not chain:
            return None

        try:
            idx = chain.index(failed)
        except ValueError:
            # 失败的 provider 不在候选链中：回退到最高优先级候选
            return chain[0] if chain[0] != failed else None

        if idx + 1 < len(chain):
            return chain[idx + 1]

        # failed 位于链尾
        if len(chain) == 1:
            # 单 provider：无法转移到自身，放弃
            return None
        # 多 provider：回绕到链首
        return chain[0]
