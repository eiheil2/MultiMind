"""站点适配器层 — 封装每个 AI 网站的 DOM 交互差异。

BrowserChannel 通过 SiteAdapter 适配不同网站：
  DeepSeek / ChatGPT / 通义千问 / 豆包 / KIMI / 任意第三方站点

每个 SiteAdapter 封装站点特定的选择器、输入方式、模式选择和流式抓取逻辑。
网站改版时修改 TOML 配置文件即可，无需改代码。

扩展机制：
  - 内置适配器（5 个站点）
  - Entry Points 插件（``multimind.sites`` 组）
  - 运行时注册（``registry.register()``）
  - GenericSiteAdapter 兜底（仅有 TOML 配置即可使用）
  - 用户自定义配置目录（``~/.multimind/sites/`` 或 ``MULTIMIND_SITES_DIR``）
"""

from multimind.adapters.sites.base import (
    LoginExpiredError,
    RateLimitError,
    SafetyGuard,
    SiteAdapter,
)
from multimind.adapters.sites.chatgpt import ChatGPTSite
from multimind.adapters.sites.deepseek import DeepSeekSite
from multimind.adapters.sites.doubao import DoubaoSite
from multimind.adapters.sites.generic import GenericSiteAdapter
from multimind.adapters.sites.kimi import KimiSite
from multimind.adapters.sites.profile import (
    CompletionConfig,
    ProfileValidationError,
    SafetyConfig,
    SiteCapability,
    SiteMode,
    SiteProfile,
    SiteSelectors,
    discover_profiles,
    get_profile_search_dirs,
    load_profile,
    load_profile_by_name,
    validate_profile,
)
from multimind.adapters.sites.qwen import QwenSite
from multimind.adapters.sites.registry import (
    SiteAdapterRegistry,
    create_site_adapter,
    get_site_registry,
    reset_site_registry,
)

__all__ = [
    # 抽象基类
    "SiteAdapter",
    "SafetyGuard",
    "GenericSiteAdapter",
    # 异常
    "LoginExpiredError",
    "RateLimitError",
    "ProfileValidationError",
    # 站点适配器
    "DeepSeekSite",
    "ChatGPTSite",
    "QwenSite",
    "DoubaoSite",
    "KimiSite",
    # 配置
    "SiteProfile",
    "SiteSelectors",
    "SiteMode",
    "SafetyConfig",
    "CompletionConfig",
    "SiteCapability",
    "load_profile",
    "load_profile_by_name",
    "discover_profiles",
    "get_profile_search_dirs",
    "validate_profile",
    # 注册表
    "SiteAdapterRegistry",
    "create_site_adapter",
    "get_site_registry",
    "reset_site_registry",
]
