"""通用站点适配器 — 基于 TOML 配置的通用 DOM 交互实现。

GenericSiteAdapter 使用 SiteProfile 中的 CSS 选择器执行所有操作，
无需站点特定代码。适用于 DOM 结构简单的站点。

站点特定适配器（如 DeepSeekSite）继承此类并覆盖需要特殊处理的方法。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from multimind.adapters.sites.base import SiteAdapter
from multimind.core.exceptions import AdapterError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from multimind.adapters.sites.profile import SiteProfile

__all__ = ["GenericSiteAdapter"]

logger = logging.getLogger(__name__)


class GenericSiteAdapter(SiteAdapter):
    """通用站点适配器 — 纯配置驱动，无站点特定代码。

    所有操作通过 SiteProfile.selectors 中的 CSS 选择器执行。
    站点改版时只需更新 TOML 配置文件。

    子类可覆盖以下方法实现站点特定逻辑：
      - ``select_mode()`` — 模式激活状态检测
      - ``detect_login_expiry()`` — 登录过期检测
      - ``_is_generation_complete()`` — 完成检测
    """

    def __init__(self, profile: SiteProfile) -> None:
        super().__init__(profile)
        if profile.name != self.site_name:
            logger.warning(
                "Profile name '%s' does not match site_name '%s'",
                profile.name,
                self.site_name,
            )

    async def send_prompt(self, page: Any, prompt: str) -> None:
        """通用发送流程：等待输入框 → 清空 → 填充 → 点击发送。

        Args:
            page: Playwright Page 对象。
            prompt: 用户提示词。

        Raises:
            AdapterError: 发送失败。
        """
        selectors = self.profile.selectors
        logger.debug("%s: sending prompt (%d chars)", self.site_name, len(prompt))

        try:
            await page.wait_for_selector(selectors.input_box, timeout=10_000)
            await page.fill(selectors.input_box, "")
            await page.fill(selectors.input_box, prompt)
            await page.wait_for_selector(selectors.send_button, timeout=5_000)
            await page.click(selectors.send_button)
            logger.info("%s: prompt sent", self.site_name)
        except Exception as e:
            raise AdapterError(f"{self.site_name} send_prompt failed: {e}") from e

    async def select_mode(self, page: Any, mode: str) -> None:
        """通用模式选择 — 点击模式按钮。

        子类可覆盖此方法实现激活状态检测。

        Args:
            page: Playwright Page 对象。
            mode: 模式标识。
        """
        if not self.has_mode(mode):
            logger.warning("%s: mode '%s' not supported, skipping", self.site_name, mode)
            return

        mode_config = self.get_mode(mode)
        logger.debug("%s: selecting mode '%s'", self.site_name, mode)

        try:
            element = await page.query_selector(mode_config.selector)
            if element is None:
                logger.warning("%s: mode button not found", self.site_name)
                return
            await element.click()
            logger.info("%s: mode '%s' selected", self.site_name, mode)
        except Exception as e:
            logger.warning("%s: mode selection failed (non-fatal): %s", self.site_name, e)

    async def extract_stream(self, page: Any) -> AsyncIterator[str]:
        """通用流式抓取 — 轮询响应容器获取增量文本。

        Args:
            page: Playwright Page 对象。

        Yields:
            流式输出的文本片段。
        """
        selectors = self.profile.selectors
        completion = self.profile.completion

        # 等待响应容器
        try:
            await page.wait_for_selector(
                selectors.response_container,
                timeout=30_000,
            )
        except Exception:
            logger.warning("%s: response container not found", self.site_name)
            return

        # 轮询增量
        last_text = ""
        stable_count = 0
        stable_threshold = max(1, int(completion.stable_duration / completion.poll_interval))
        start_time = time.time()

        while time.time() - start_time < completion.timeout:
            try:
                element = await page.query_selector(selectors.response_container)
                if element is None:
                    await asyncio.sleep(completion.poll_interval)
                    continue

                current_text = await element.text_content() or ""

                if len(current_text) > len(last_text):
                    yield current_text[len(last_text):]
                    last_text = current_text
                    stable_count = 0
                else:
                    stable_count += 1

                # 完成检测
                if completion.method == "stop_button_disappear":
                    if await self._is_generation_complete(page):
                        if len(current_text) > len(last_text):
                            yield current_text[len(last_text):]
                        break
                elif completion.method == "response_stable" and stable_count >= stable_threshold:
                    break

            except Exception as e:
                logger.warning("%s: stream poll error: %s", self.site_name, e)

            await asyncio.sleep(completion.poll_interval)

        logger.info(
            "%s: stream complete (%d chars in %.1fs)",
            self.site_name,
            len(last_text),
            time.time() - start_time,
        )

    async def wait_for_complete(self, page: Any) -> None:
        """通用完成等待 — 确认停止按钮已消失。

        Args:
            page: Playwright Page 对象。
        """
        selectors = self.profile.selectors
        if not selectors.stop_button:
            return

        try:
            await page.wait_for_selector(
                selectors.stop_button,
                state="detached",
                timeout=5_000,
            )
        except Exception:
            logger.debug("%s: stop button already gone", self.site_name)

    async def detect_login_expiry(self, page: Any) -> bool:
        """通用登录过期检测 — 检查登录重定向元素是否存在。

        子类可覆盖此方法实现 URL 跳转检测等站点特定逻辑。

        Args:
            page: Playwright Page 对象。

        Returns:
            True 表示登录已过期。
        """
        selectors = self.profile.selectors
        if not selectors.login_redirect:
            return False

        try:
            element = await page.query_selector(selectors.login_redirect)
            if element is not None:
                logger.warning("%s: login redirect detected", self.site_name)
                return True
        except Exception:
            pass

        return False

    async def _is_generation_complete(self, page: Any) -> bool:
        """通用完成检测 — 检查停止按钮是否不可见。

        Args:
            page: Playwright Page 对象。

        Returns:
            True 表示生成已完成。
        """
        selectors = self.profile.selectors
        if not selectors.stop_button:
            return False

        try:
            element = await page.query_selector(selectors.stop_button)
            if element is None:
                return True
            return not await element.is_visible()
        except Exception:
            return False
