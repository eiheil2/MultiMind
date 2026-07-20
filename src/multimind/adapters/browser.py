"""③ 网页登录通道。

通过 Playwright 操控浏览器，复用 Cookie / ``storage_state`` 访问
官方网页（DeepSeek、ChatGPT、通义千问、豆包、KIMI 等）。

架构分层：
  BrowserAdapter — 管理 Playwright 生命周期 + 登录态
    └─ SiteAdapter — 封装每站 DOM 交互差异（选择器/模式/流式抓取）

Playwright 为可选依赖（``pip install multimind[browser]``）。
未安装时降级为桩模式，保持框架可运行。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from multimind.adapters.sites import (
    LoginExpiredError,
    RateLimitError,
    SafetyConfig,
    SiteAdapter,
    create_site_adapter,
)
from multimind.core.exceptions import AdapterError
from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, Message, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

__all__ = ["BrowserAdapter"]

logger = logging.getLogger(__name__)

# 站点名映射：provider name → site adapter name
_SITE_NAME_MAP: dict[str, str] = {
    "chatgpt": "chatgpt",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "doubao": "doubao",
    "kimi": "kimi",
    # 兼容旧配置
    "claude": "",
    "gemini-web": "",
}

# 默认 URL（站点适配器不可用时的后备）
_DEFAULT_URLS: dict[str, str] = {
    "chatgpt": "https://chatgpt.com",
    "deepseek": "https://chat.deepseek.com",
    "qwen": "https://qwen.ai",
    "doubao": "https://www.doubao.com/chat",
    "kimi": "https://kimi.moonshot.cn",
    "claude": "https://claude.ai",
    "gemini-web": "https://gemini.google.com",
}


class BrowserAdapter(AIAdapter):
    """网页登录适配器 — 双层架构。

    上层管理 Playwright 浏览器生命周期和登录态复用，
    下层通过 SiteAdapter 适配不同网站的 DOM 结构。

    Attributes:
        _storage_state: Playwright storage_state 文件路径。
        _site_adapter: 站点适配器实例（懒加载）。
        _site_name: 站点标识（从 config.name 推断）。
        _playwright: Playwright 实例（懒加载）。
        _browser: 浏览器实例。
        _page: 页面实例。
    """

    channel_type = ChannelType.BROWSER

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._storage_state: Path | None = None
        self._site_adapter: SiteAdapter | None = None
        self._site_name: str = _SITE_NAME_MAP.get(config.name, "")
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    def _default_url(self) -> str:
        """根据 provider 名推断默认网页 URL。"""
        return _DEFAULT_URLS.get(self.config.name, "")

    def set_storage_state(self, path: Path) -> None:
        """设置 Playwright storage_state 文件路径。

        Args:
            path: storage_state JSON 文件路径。
        """
        self._storage_state = path

    def set_site_adapter(self, adapter: SiteAdapter) -> None:
        """手动设置站点适配器（覆盖自动推断）。

        Args:
            adapter: 站点适配器实例。
        """
        self._site_adapter = adapter
        self._site_name = adapter.site_name
        logger.info("BrowserAdapter: site adapter set to '%s'", adapter.site_name)

    def _ensure_site_adapter(self) -> None:
        """懒加载站点适配器（从 TOML 配置创建）。

        如果站点名未知或配置加载失败，静默跳过（降级为桩模式）。
        """
        if self._site_adapter is not None:
            return
        if not self._site_name:
            return

        try:
            self._site_adapter = create_site_adapter(self._site_name)
            logger.info(
                "BrowserAdapter: loaded site adapter '%s' for provider '%s'",
                self._site_name,
                self.config.name,
            )
        except Exception as e:
            logger.warning(
                "BrowserAdapter: failed to load site adapter '%s': %s — falling back to stub",
                self._site_name,
                e,
            )

    def _get_safety_config(self) -> SafetyConfig:
        """获取安全配置（从站点适配器或默认值）。"""
        if self._site_adapter:
            return self._site_adapter.profile.safety
        return SafetyConfig()

    async def _ensure_browser(self) -> Any:
        """懒初始化 Playwright 浏览器和页面。

        Returns:
            Playwright Page 对象。

        Raises:
            AdapterError: Playwright 未安装或浏览器启动失败。
        """
        if self._page is not None:
            return self._page

        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise AdapterError(
                "Playwright is not installed. "
                "Install with: pip install multimind[browser]"
            ) from e

        safety = self._get_safety_config()

        logger.info(
            "BrowserAdapter: starting Playwright (headless=%s)",
            not safety.headed,
        )

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=not safety.headed,
        )

        # 创建上下文（注入登录态）
        context_args: dict[str, Any] = {}
        if self._storage_state and self._storage_state.exists():
            context_args["storage_state"] = str(self._storage_state)
            logger.debug("BrowserAdapter: using storage_state from %s", self._storage_state)
        else:
            logger.warning(
                "BrowserAdapter: no storage_state — login required manually"
            )

        context = await self._browser.new_context(**context_args)
        self._page = await context.new_page()

        # 导航到站点 URL
        url = self._site_adapter.profile.url if self._site_adapter else self._default_url()
        if url:
            logger.info("BrowserAdapter: navigating to %s", url)
            await self._page.goto(url)

        return self._page

    async def ask(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """通过浏览器操控流式输出。

        流程：
          1. 加载站点适配器（如未加载）
          2. 启动 Playwright 浏览器（如未启动）
          3. 委托 SiteAdapter.interact() 执行完整交互
          4. 降级：无 Playwright 或无站点适配器时使用桩模式

        Args:
            prompt: 用户提示词（输入到网页输入框）。
            context: 群聊历史（可选注入到输入）。
            **kwargs: 浏览器特定参数（``mode`` 指定模式）。

        Yields:
            流式输出的文本片段。
        """
        logger.debug("Browser '%s' processing prompt: %s", self.config.name, prompt[:80])

        # 懒加载站点适配器
        self._ensure_site_adapter()

        # 无站点适配器 → 桩模式
        if self._site_adapter is None:
            yield f"[网页·{self.config.name}] "
            await asyncio.sleep(0.1)
            yield f"未配置站点适配器，桩模式输出：{prompt[:40]}"
            self.record_usage()
            return

        # 尝试启动浏览器
        try:
            page = await self._ensure_browser()
        except AdapterError as e:
            # Playwright 未安装 → 降级桩模式
            yield f"[网页·{self.config.name}] "
            await asyncio.sleep(0.1)
            yield f"Playwright 未安装，桩模式输出：{prompt[:40]}"
            logger.warning("BrowserAdapter: Playwright unavailable — %s", e)
            self.record_usage()
            return

        # 委托站点适配器执行交互
        mode = str(kwargs.get("mode", ""))

        try:
            async for chunk in self._site_adapter.interact(page, prompt, mode):
                yield chunk

            self.record_usage()
            logger.debug("Browser '%s' completed", self.config.name)

        except LoginExpiredError as e:
            yield f"[网页·{self.config.name}] 登录已过期，请重新认证"
            logger.error("BrowserAdapter: login expired — %s", e)
            self.record_usage()

        except RateLimitError as e:
            yield f"[网页·{self.config.name}] 触发限流：{e}"
            logger.error("BrowserAdapter: rate limited — %s", e)
            self.record_usage()

        except Exception as e:
            yield f"[网页·{self.config.name}] 交互失败：{e}"
            logger.exception("BrowserAdapter: interact failed")
            self.record_usage()

    async def close(self) -> None:
        """关闭浏览器并释放资源。

        按顺序关闭 Page → Browser → Playwright。
        """
        logger.debug("BrowserAdapter: closing resources")

        if self._page is not None:
            with contextlib.suppress(Exception):
                await self._page.close()
            self._page = None

        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None

        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

        logger.info("BrowserAdapter: closed")
