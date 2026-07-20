"""路由器 — 组合标签匹配、额度追踪和故障转移。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from multimind.routing.failover import FailoverChain
from multimind.routing.quota import QuotaTracker
from multimind.routing.tags import TagMatcher

if TYPE_CHECKING:
    from multimind.adapters.registry import ProviderRegistry

__all__ = ["Router", "RoutingResult"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RoutingResult:
    """路由结果。

    Attributes:
        provider: 选中的 provider 名称。
        fallbacks: 故障转移候选列表。
    """

    provider: str
    fallbacks: list[str]


class Router:
    """额度感知路由器。

    路由策略：标签匹配 → 按优先级排序 → 按剩余额度打分选最优。
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        quota: QuotaTracker | None = None,
    ) -> None:
        self._registry = registry
        self._quota = quota or QuotaTracker()
        self._tag_matcher = TagMatcher(registry)
        self._failover = FailoverChain(registry)

    def select(self, required_tags: list[str] | None = None) -> RoutingResult | None:
        """选择最优 provider。

        Args:
            required_tags: 任务所需的能力标签。

        Returns:
            路由结果，无可用 provider 时返回 None。
        """
        matched = self._tag_matcher.match(required_tags)
        if not matched:
            logger.warning("No provider matches tags: %s", required_tags)
            return None

        # 按「优先级 → 剩余额度（降序）→ 名称」排序并过滤额度
        candidates: list[tuple[int, int, str]] = []
        for name in matched:
            adapter = self._registry.get(name)
            if adapter and adapter.remaining_quota > 0:
                # 剩余额度取负作为排序键：优先级相同时，剩余越多越优先
                candidates.append((adapter.config.priority, -adapter.remaining_quota, name))

        if not candidates:
            logger.warning("No provider with remaining quota for tags: %s", required_tags)
            return None

        candidates.sort()
        best = candidates[0][2]
        fallbacks = [name for _, _, name in candidates[1:]]

        logger.info("Routed to: %s (fallbacks: %s)", best, fallbacks)
        return RoutingResult(provider=best, fallbacks=fallbacks)

    def failover(self, failed: str, required_tag: str | None = None) -> str | None:
        """获取故障转移候选。"""
        return self._failover.next_available(failed, required_tag)

    @property
    def quota(self) -> QuotaTracker:
        """额度追踪器。"""
        return self._quota
