"""站点适配器注册表 — 插件式注册 + 动态发现 + GenericSiteAdapter 兜底。

扩展机制：
  1. **内置适配器** — DeepSeek/ChatGPT/Qwen/Doubao/KIMI 随包发布
  2. **Entry Points 插件** — 第三方包通过 ``[project.entry-points."multimind.sites"]``
     注册自定义适配器类
  3. **运行时注册** — 调用 ``registry.register()`` 动态注册
  4. **GenericSiteAdapter 兜底** — 仅有 TOML 配置但无自定义适配器类的站点，
     自动使用 GenericSiteAdapter 并动态设置 site_name

使用方式：
    registry = get_site_registry()
    adapter = registry.create("deepseek")
    # 或注册自定义适配器
    registry.register("my_site", MySiteAdapter)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from multimind.adapters.sites.profile import discover_profiles, load_profile_by_name

if TYPE_CHECKING:
    from multimind.adapters.sites.base import SiteAdapter

__all__ = [
    "SiteAdapterRegistry",
    "create_site_adapter",
    "get_site_registry",
    "reset_site_registry",
]

logger = logging.getLogger(__name__)

# Entry Point 组名 — 第三方包通过此组注册站点适配器
_ENTRY_POINT_GROUP = "multimind.sites"


def _register_builtin(registry: SiteAdapterRegistry) -> None:
    """注册内置站点适配器。"""
    from multimind.adapters.sites.chatgpt import ChatGPTSite
    from multimind.adapters.sites.deepseek import DeepSeekSite
    from multimind.adapters.sites.doubao import DoubaoSite
    from multimind.adapters.sites.kimi import KimiSite
    from multimind.adapters.sites.qwen import QwenSite

    registry.register("deepseek", DeepSeekSite)
    registry.register("chatgpt", ChatGPTSite)
    registry.register("qwen", QwenSite)
    registry.register("doubao", DoubaoSite)
    registry.register("kimi", KimiSite)


def _discover_entry_points(registry: SiteAdapterRegistry) -> None:
    """发现并注册 Entry Points 插件。

    第三方包在 pyproject.toml 中声明：
        [project.entry-points."multimind.sites"]
        my_site = "my_package:MySiteAdapter"
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover
        return

    try:
        eps = entry_points(group=_ENTRY_POINT_GROUP)
    except TypeError:
        # Python 3.9 兼容
        eps = entry_points().get(_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]

    for ep in eps:
        try:
            adapter_cls = ep.load()
            registry.register(ep.name, adapter_cls)
            logger.info("Discovered entry point plugin: %s → %s", ep.name, adapter_cls)
        except Exception as e:
            logger.warning("Failed to load entry point '%s': %s", ep.name, e)


def _create_generic_adapter_cls(site_name: str) -> type[SiteAdapter]:
    """为没有自定义适配器的站点动态创建 GenericSiteAdapter 子类。

    Args:
        site_name: 站点标识。

    Returns:
        动态创建的适配器类，site_name 已设置。
    """
    from multimind.adapters.sites.generic import GenericSiteAdapter

    return type(
        f"Generic_{site_name}_Site",
        (GenericSiteAdapter,),
        {"site_name": site_name},
    )


class SiteAdapterRegistry:
    """站点适配器注册表 — 单例。

    管理站点名 → 适配器类的映射，按需创建适配器实例。
    支持 GenericSiteAdapter 兜底：仅有 TOML 配置的站点也能使用。

    Usage:
        registry = get_site_registry()
        adapter = registry.create("deepseek")
    """

    def __init__(self) -> None:
        self._classes: dict[str, type[SiteAdapter]] = {}
        self._instances: dict[str, SiteAdapter] = {}

    def register(self, site_name: str, adapter_cls: type[SiteAdapter]) -> None:
        """注册站点适配器类。

        Args:
            site_name: 站点标识。
            adapter_cls: 适配器类（SiteAdapter 子类）。
        """
        self._classes[site_name] = adapter_cls
        # 清除缓存的实例（类已变更）
        self._instances.pop(site_name, None)
        logger.debug("Registered site adapter: %s → %s", site_name, adapter_cls.__name__)

    def unregister(self, site_name: str) -> None:
        """取消注册站点适配器。

        Args:
            site_name: 站点标识。
        """
        self._classes.pop(site_name, None)
        self._instances.pop(site_name, None)

    def create(self, site_name: str, force_reload: bool = False) -> SiteAdapter:
        """创建或获取站点适配器实例。

        加载站点 TOML 配置并实例化适配器。实例会被缓存，
        除非 ``force_reload=True``。

        如果站点没有注册自定义适配器类，但存在 TOML 配置，
        自动使用 GenericSiteAdapter 兜底。

        Args:
            site_name: 站点标识。
            force_reload: 是否强制重新加载（忽略缓存）。

        Returns:
            站点适配器实例。

        Raises:
            KeyError: 站点未注册且无 TOML 配置。
            FileNotFoundError: 配置文件不存在。
        """
        if not force_reload and site_name in self._instances:
            return self._instances[site_name]

        adapter_cls = self._classes.get(site_name)

        # 兜底：没有自定义适配器类，尝试 GenericSiteAdapter
        if adapter_cls is None:
            profiles = discover_profiles()
            if site_name not in profiles:
                available = ", ".join(sorted(self._classes.keys() | profiles.keys()))
                raise KeyError(
                    f"Site '{site_name}' not registered and no profile found. "
                    f"Available: {available}"
                )
            adapter_cls = _create_generic_adapter_cls(site_name)
            logger.info(
                "No custom adapter for '%s', using GenericSiteAdapter fallback",
                site_name,
            )

        profile = load_profile_by_name(site_name)
        adapter = adapter_cls(profile)
        self._instances[site_name] = adapter
        logger.info("Created site adapter '%s' (%s)", site_name, adapter_cls.__name__)
        return adapter

    def available_sites(self) -> list[str]:
        """返回所有可用站点名（已注册适配器 + 已发现配置的并集）。"""
        profile_names = set(discover_profiles().keys())
        return sorted(self._classes.keys() | profile_names)

    def registered_adapters(self) -> list[str]:
        """返回已注册适配器类的站点名（不含 GenericSiteAdapter 兜底）。"""
        return sorted(self._classes.keys())

    def has_adapter(self, site_name: str) -> bool:
        """检查站点是否有自定义适配器类（非 GenericSiteAdapter 兜底）。"""
        return site_name in self._classes

    def reset(self) -> None:
        """清除所有缓存的实例。"""
        self._instances.clear()


# ── 单例 ─────────────────────────────────────────────────────────────

_registry: SiteAdapterRegistry | None = None


def get_site_registry() -> SiteAdapterRegistry:
    """获取全局站点适配器注册表单例。

    首次调用时自动注册内置适配器和 Entry Points 插件。
    """
    global _registry
    if _registry is None:
        _registry = SiteAdapterRegistry()
        _register_builtin(_registry)
        _discover_entry_points(_registry)
        logger.info(
            "Site registry initialized with %d adapters: %s",
            len(_registry._classes),
            _registry.registered_adapters(),
        )
    return _registry


def reset_site_registry() -> None:
    """重置全局注册表（测试用）。"""
    global _registry
    _registry = None


def create_site_adapter(site_name: str, force_reload: bool = False) -> SiteAdapter:
    """便捷函数 — 创建站点适配器实例。"""
    return get_site_registry().create(site_name, force_reload=force_reload)
