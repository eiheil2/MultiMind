"""DeepSeek 站点适配器 — chat.deepseek.com。

DeepSeek 网页特征：
  - 输入框：底部圆角文本框
  - 模式：深度思考、联网搜索（底部切换按钮）
  - 响应：Markdown 渲染容器
  - 完成检测：停止按钮消失

继承 GenericSiteAdapter，覆盖模式激活检测和登录 URL 检测。
"""

from __future__ import annotations

import logging
from typing import Any

from multimind.adapters.sites.generic import GenericSiteAdapter

__all__ = ["DeepSeekSite"]

logger = logging.getLogger(__name__)


class DeepSeekSite(GenericSiteAdapter):
    """DeepSeek 站点适配器。

    继承通用适配器的所有功能，覆盖以下站点特定逻辑：
      - ``select_mode()``: 检测 ``aria-pressed`` 属性判断模式是否已激活
      - ``detect_login_expiry()``: 额外检查 URL 是否包含 ``sign_in``
    """

    site_name = "deepseek"

    async def select_mode(self, page: Any, mode: str) -> None:
        """选择模式 — DeepSeek 特有的激活状态检测。

        DeepSeek 模式按钮通过 ``aria-pressed`` 属性或 ``active`` 类
        标识激活状态。如果已激活则跳过点击。

        Args:
            page: Playwright Page 对象。
            mode: 模式标识（``deep_thinking`` / ``web_search``）。
        """
        if not self.has_mode(mode):
            logger.warning("DeepSeek: mode '%s' not supported, skipping", mode)
            return

        mode_config = self.get_mode(mode)
        logger.debug("DeepSeek: selecting mode '%s' (%s)", mode, mode_config.label)

        try:
            # 通过 evaluate 检查模式是否已激活
            is_pressed = await page.evaluate(
                f"""() => {{
                    const el = document.querySelector("{mode_config.selector}");
                    if (!el) return false;
                    return el.getAttribute("aria-pressed") === "true" ||
                           el.classList.contains("active");
                }}"""
            )

            if is_pressed:
                logger.debug("DeepSeek: mode '%s' already active", mode)
                return

            # 点击切换
            await page.click(mode_config.selector)
            logger.info("DeepSeek: mode '%s' selected", mode)

        except Exception as e:
            logger.warning("DeepSeek: mode selection failed (non-fatal): %s", e)

    async def detect_login_expiry(self, page: Any) -> bool:
        """检测登录过期 — DeepSeek 特有的 URL 跳转检测。

        除了检查登录重定向元素外，还检查 URL 是否包含 ``sign_in``。

        Args:
            page: Playwright Page 对象。

        Returns:
            True 表示登录已过期。
        """
        # 先调用父类检查（登录重定向元素）
        if await super().detect_login_expiry(page):
            return True

        # DeepSeek 特有：检查 URL 是否跳转到登录页
        if self.profile.login_url:
            try:
                current_url = await page.evaluate("() => window.location.href")
                if current_url and "sign_in" in str(current_url):
                    logger.warning("DeepSeek: URL redirected to login page")
                    return True
            except Exception:
                pass

        return False
