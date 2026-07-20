"""Provider 注册表 — 模型 → 通道路由映射。

负责 provider 的注册、查找和优先级排序。
单例模式，全局共享一个 ``ProviderRegistry`` 实例。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from multimind.adapters.base import create_adapter
from multimind.core.types import ChannelType, ProviderConfig

if TYPE_CHECKING:
    from multimind.core.interfaces import AIAdapter

__all__ = ["ProviderRegistry", "get_registry", "init_default_providers", "reset_registry"]

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Provider 注册与查找。

    线程安全注意：本类非线程安全，应在单线程或 asyncio 上下文中使用。
    如需多线程访问，应加锁。
    """

    def __init__(self) -> None:
        self._providers: dict[str, ProviderConfig] = {}
        self._adapters: dict[str, AIAdapter] = {}

    def register(self, config: ProviderConfig) -> None:
        """注册一个 provider。

        Args:
            config: Provider 配置。如果同名 provider 已存在则覆盖。
        """
        if config.name in self._providers:
            logger.warning("Overwriting existing provider: %s", config.name)
        self._providers[config.name] = config
        self._adapters[config.name] = create_adapter(config)
        logger.info("Registered provider: %s (channel=%s)", config.name, config.channel.value)

    def get(self, name: str) -> AIAdapter | None:
        """按名称获取适配器。"""
        return self._adapters.get(name)

    def all(self) -> dict[str, AIAdapter]:
        """返回所有已注册适配器的副本。"""
        return dict(self._adapters)

    def by_tag(self, tag: str) -> list[AIAdapter]:
        """按能力标签筛选适配器。"""
        return [
            self._adapters[name]
            for name, cfg in self._providers.items()
            if tag in cfg.tags
        ]

    def sorted_by_priority(self) -> list[AIAdapter]:
        """按优先级排序（priority 值小的优先）。"""
        return sorted(
            self._adapters.values(),
            key=lambda a: a.config.priority,
        )

    def available(self, required_tag: str | None = None) -> list[AIAdapter]:
        """返回有剩余额度的可用适配器。

        Args:
            required_tag: 可选的能力标签过滤。

        Returns:
            按优先级排序的可用适配器列表。
        """
        candidates = self.by_tag(required_tag) if required_tag else list(self._adapters.values())
        return sorted(
            [a for a in candidates if a.remaining_quota > 0],
            key=lambda a: a.config.priority,
        )

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, name: str) -> bool:
        return name in self._adapters


# ── 单例 ────────────────────────────────────────────────────────
_registry = ProviderRegistry()


def get_registry() -> ProviderRegistry:
    """获取全局 ProviderRegistry 单例。"""
    return _registry


def reset_registry() -> None:
    """重置注册表（主要用于测试）。"""
    global _registry  # noqa: PLW0603
    _registry = ProviderRegistry()


def init_default_providers() -> None:
    """初始化默认 provider（框架验证用）。

    实际使用时，provider 配置从 ``~/.multimind/config.toml`` 加载。
    没有配置 API key 的 provider 会被跳过，不注册。
    """
    import os

    configs: list[ProviderConfig] = [
        ProviderConfig(
            name="gemini-cli",
            channel=ChannelType.CLI_REUSE,
            model="gemini-2.5-flash",
            tags=("free", "long-context", "fast"),
            priority=10,
            daily_quota=1000,
            max_tokens=1_000_000,
        ),
        ProviderConfig(
            name="groq",
            channel=ChannelType.API_CLIENT,
            model="llama-3.3-70b",
            api_key=os.environ.get("GROQ_API_KEY", ""),
            tags=("free", "fast"),
            priority=20,
            daily_quota=14_400,
            max_tokens=32_000,
        ),
        ProviderConfig(
            name="opencode-free",
            channel=ChannelType.PUBLIC_ENDPOINT,
            model="glm-5-free",
            tags=("free", "zero-config"),
            priority=30,
            daily_quota=-1,
            max_tokens=128_000,
        ),
        ProviderConfig(
            name="ollama-local",
            channel=ChannelType.LOCAL,
            model="qwen2.5:14b",
            tags=("free", "offline", "private"),
            priority=90,
            daily_quota=-1,
            max_tokens=32_000,
        ),
    ]

    skipped: list[str] = []
    for cfg in configs:
        # API 通道无 key 则跳过
        if cfg.channel == ChannelType.API_CLIENT and not cfg.api_key:
            skipped.append(cfg.name)
            logger.info("Skipping provider '%s' (no API key)", cfg.name)
            continue
        _registry.register(cfg)

    if skipped:
        import sys

        print(
            f"\n[提示] 以下 API provider 未配置密钥，已跳过: {', '.join(skipped)}\n"
            f"  设置环境变量后可用，例如: export GROQ_API_KEY=your_key\n"
            f"  其他 provider 仍可正常使用。\n",
            file=sys.stderr,
        )
