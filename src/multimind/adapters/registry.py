"""Provider 注册表 — 模型 → 通道路由映射。

负责 provider 的注册、查找和优先级排序。
单例模式，全局共享一个 ``ProviderRegistry`` 实例。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from multimind.adapters.base import create_adapter
from multimind.core.types import ChannelType, ProviderConfig
from multimind.routing.quota import QuotaTracker

if TYPE_CHECKING:
    from multimind.core.interfaces import AIAdapter

__all__ = ["ProviderRegistry", "get_registry", "init_default_providers", "reset_registry"]

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Provider 注册与查找。

    线程安全注意：本类非线程安全，应在单线程或 asyncio 上下文中使用。
    如需多线程访问，应加锁。
    """

    def __init__(self, quota_db: str | Path = ":memory:") -> None:
        self._providers: dict[str, ProviderConfig] = {}
        self._adapters: dict[str, AIAdapter] = {}
        # 全注册表共享一个额度追踪器：所有适配器的 remaining_quota /
        # record_usage 都读写它，保证额度判断与持久化同源。
        self._quota = QuotaTracker(quota_db)

    @property
    def quota_tracker(self) -> QuotaTracker:
        """共享额度追踪器。"""
        return self._quota

    def register(self, config: ProviderConfig) -> None:
        """注册一个 provider。

        Args:
            config: Provider 配置。如果同名 provider 已存在则覆盖。
        """
        if config.name in self._providers:
            logger.warning("Overwriting existing provider: %s", config.name)
        self._providers[config.name] = config
        self._adapters[config.name] = create_adapter(config, quota=self._quota)
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


def init_default_providers(quota_db: str | Path | None = None) -> None:
    """初始化 provider 注册表（框架默认 + 用户 config.toml 配置）。

    重建全局单例并注入共享额度追踪器；随后注册内置默认 provider，
    再加载 ``~/.multimind/config.toml`` 中用户自定义的 provider。

    Args:
        quota_db: 额度库路径。None 使用内存库（测试/单次进程隔离）；
            真实 CLI 应传入持久化路径以跨进程累计额度。
    """
    global _registry  # noqa: PLW0603
    _registry = ProviderRegistry(quota_db=quota_db or ":memory:")

    import os

    configs: list[ProviderConfig] = [
        ProviderConfig(
            name="gemini-cli",
            channel=ChannelType.CLI_REUSE,
            model="gemini-2.5-flash",
            tags=("free", "long-context", "fast"),
            priority=10,
            daily_quota=1000,
            rpm_limit=60,
            max_tokens=1_000_000,
        ),
        ProviderConfig(
            name="groq",
            channel=ChannelType.API_CLIENT,
            model="llama-3.3-70b",
            api_key=os.environ.get("GROQ_API_KEY", ""),
            tags=("free", "fast"),
            priority=20,
            daily_quota=1_000_000,
            rpm_limit=30,
            max_tokens=32_000,
        ),
        ProviderConfig(
            name="opencode-free",
            channel=ChannelType.PUBLIC_ENDPOINT,
            model="glm-5-free",
            tags=("free", "zero-config"),
            priority=30,
            daily_quota=-1,
            rpm_limit=60,
            max_tokens=128_000,
        ),
        ProviderConfig(
            name="ollama-local",
            channel=ChannelType.LOCAL,
            model="qwen2.5:14b",
            tags=("free", "offline", "private"),
            priority=90,
            daily_quota=-1,
            rpm_limit=-1,
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

    # 加载用户在 config.toml 中定义的 provider
    _register_user_providers(_registry)

    if skipped:
        import sys

        print(
            f"\n[提示] 以下 API provider 未配置密钥，已跳过: {', '.join(skipped)}\n"
            f"  设置环境变量后可用，例如: export GROQ_API_KEY=your_key\n"
            f"  其他 provider 仍可正常使用。\n",
            file=sys.stderr,
        )


def _provider_config_from_dict(data: dict[str, object]) -> ProviderConfig | None:
    """从 config.toml 的 provider 字典构造 ProviderConfig。

    过滤未知键、做基本校验；非法配置返回 None 并告警。
    """
    name = data.get("name")
    channel = data.get("channel")
    if not name or not channel:
        logger.warning("跳过无效 provider 配置（缺少 name/channel）: %s", data)
        return None
    try:
        ch = ChannelType(channel)
    except ValueError:
        logger.warning("跳过未知通道类型: %s", channel)
        return None
    return ProviderConfig(
        name=str(name),
        channel=ch,
        model=str(data.get("model", "")),
        api_key=str(data.get("api_key", "")),
        endpoint=str(data.get("endpoint", "")),
        tags=tuple(str(t) for t in data.get("tags", [])),  # type: ignore[arg-type]
        priority=int(data.get("priority", 100)),  # type: ignore[arg-type]
        daily_quota=int(data.get("daily_quota", -1)),  # type: ignore[arg-type]
        rpm_limit=int(data.get("rpm_limit", 60)),  # type: ignore[arg-type]
        max_tokens=int(data.get("max_tokens", 8192)),  # type: ignore[arg-type]
    )


def _register_user_providers(registry: ProviderRegistry) -> None:
    """把 config.toml 的 ``providers`` 段注册进注册表。

    API 通道若未直接给 key，会尝试从全局 ``api_keys`` 段取；仍无则跳过。
    """
    try:
        from multimind.config.settings import load_config
    except ImportError:
        return

    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 — 配置损坏不应阻断启动
        logger.warning("加载 config.toml 失败，跳过用户 provider", exc_info=True)
        return

    api_keys = cfg.api_keys or {}
    for raw in cfg.providers:
        entry = dict(raw)
        # API 通道无 key 时尝试全局 api_keys 兜底
        if entry.get("channel") == "api_client" and not entry.get("api_key"):
            entry["api_key"] = api_keys.get(str(entry.get("name", "")), "")
        pc = _provider_config_from_dict(entry)
        if pc is None:
            continue
        if pc.channel == ChannelType.API_CLIENT and not pc.api_key:
            logger.info("跳过 provider '%s'（无 API key）", pc.name)
            continue
        registry.register(pc)
