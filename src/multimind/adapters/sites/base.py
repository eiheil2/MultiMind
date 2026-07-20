"""SiteAdapter 抽象基类 + SafetyGuard 反封号守护。

SiteAdapter 封装每个 AI 网站的 DOM 交互差异：
  - 输入框定位与填充
  - 模式选择（深度思考、联网搜索等）
  - 流式响应抓取
  - 完成检测
  - 登录过期检测

SafetyGuard 提供反封号安全措施：
  - 人类模拟延迟（随机 1-3s）
  - 请求限流（每会话上限）
  - 会话超时检测
  - 连续错误熔断
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from multimind.core.exceptions import AdapterError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from multimind.adapters.sites.profile import SafetyConfig, SiteProfile

__all__ = ["SiteAdapter", "SafetyGuard", "LoginExpiredError", "RateLimitError"]

logger = logging.getLogger(__name__)


class LoginExpiredError(AdapterError):
    """登录态过期异常。"""

    def __init__(self, site_name: str, login_url: str = "") -> None:
        msg = f"Site '{site_name}' login expired"
        if login_url:
            msg += f", please re-login at {login_url}"
        super().__init__(msg)


class RateLimitError(AdapterError):
    """触发限流异常。"""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Rate limit exceeded: {reason}")


class SafetyGuard:
    """反封号安全守护 — 人类模拟延迟 + 限流 + 熔断。

    在每次浏览器操作前后调用，确保行为模式接近真实用户。

    Attributes:
        config: 安全参数配置。
        _request_count: 当前会话已发请求数。
        _session_start: 会话开始时间戳。
        _consecutive_errors: 连续错误计数。
    """

    def __init__(self, config: SafetyConfig) -> None:
        self.config = config
        self._request_count: int = 0
        self._session_start: float = time.time()
        self._consecutive_errors: int = 0

    @property
    def request_count(self) -> int:
        """当前会话已发请求数。"""
        return self._request_count

    @property
    def session_elapsed(self) -> float:
        """会话已持续时间（秒）。"""
        return time.time() - self._session_start

    @property
    def consecutive_errors(self) -> int:
        """连续错误计数。"""
        return self._consecutive_errors

    def check_quota(self) -> None:
        """检查是否超过限流。

        Raises:
            RateLimitError: 超过请求上限或会话超时或连续错误熔断。
        """
        if self._consecutive_errors >= self.config.max_consecutive_errors:
            raise RateLimitError(
                f"circuit breaker triggered "
                f"({self._consecutive_errors} consecutive errors, "
                f"max={self.config.max_consecutive_errors})"
            )

        if self._request_count >= self.config.max_requests_per_session:
            raise RateLimitError(
                f"session request limit reached "
                f"({self._request_count}/{self.config.max_requests_per_session})"
            )

        if self.session_elapsed > self.config.session_timeout:
            raise RateLimitError(
                f"session timeout "
                f"({self.session_elapsed:.0f}s > {self.config.session_timeout}s)"
            )

    def record_request(self) -> None:
        """记录一次请求。"""
        self._request_count += 1
        logger.debug(
            "SafetyGuard: request #%d (session elapsed %.0fs)",
            self._request_count,
            self.session_elapsed,
        )

    def record_success(self) -> None:
        """记录成功 — 重置连续错误计数。"""
        if self._consecutive_errors > 0:
            logger.debug(
                "SafetyGuard: resetting %d consecutive errors after success",
                self._consecutive_errors,
            )
        self._consecutive_errors = 0

    def record_error(self) -> None:
        """记录错误 — 递增连续错误计数。"""
        self._consecutive_errors += 1
        logger.warning(
            "SafetyGuard: error #%d (circuit breaker at %d)",
            self._consecutive_errors,
            self.config.max_consecutive_errors,
        )

    async def human_delay(self, action: str = "action") -> None:
        """人类模拟延迟 — 随机等待 min_delay ~ max_delay 秒。

        Args:
            action: 动作描述（仅用于日志）。
        """
        delay = random.uniform(self.config.min_delay, self.config.max_delay)
        logger.debug("SafetyGuard: human delay %.2fs before '%s'", delay, action)
        await asyncio.sleep(delay)

    async def error_backoff(self) -> float:
        """错误指数退避 — 返回退避时间（秒）。

        退避时间 = base * 2^errors，上限 60s。

        Returns:
            实际等待的秒数。
        """
        backoff = min(2.0 * (2 ** self._consecutive_errors), 60.0)
        logger.warning(
            "SafetyGuard: backing off %.1fs after %d errors",
            backoff,
            self._consecutive_errors,
        )
        await asyncio.sleep(backoff)
        return backoff

    def reset_session(self) -> None:
        """重置会话 — 清零计数器，刷新开始时间。"""
        self._request_count = 0
        self._session_start = time.time()
        self._consecutive_errors = 0
        logger.info("SafetyGuard: session reset")


class SiteAdapter(ABC):
    """站点适配器抽象基类 — 封装每个 AI 网站的 DOM 交互差异。

    子类需实现五个核心方法：
      - ``send_prompt()`` — 定位输入框、填充、点发送
      - ``select_mode()`` — 选择模式（深度思考等）
      - ``extract_stream()`` — 流式抓取 DOM 增量
      - ``wait_for_complete()`` — 等待响应完成
      - ``detect_login_expiry()`` — 检测登录过期

    上层 BrowserAdapter 通过此接口无感调用不同站点。

    Attributes:
        site_name: 站点标识（子类覆盖）。
        profile: 站点配置。
        safety: 安全守护实例。
    """

    site_name: str = ""

    def __init__(self, profile: SiteProfile) -> None:
        self.profile = profile
        self.safety = SafetyGuard(profile.safety)

    def get_mode(self, mode_name: str) -> Any:
        """按名称查找模式配置。

        Args:
            mode_name: 模式标识。

        Returns:
            匹配的 SiteMode 对象。

        Raises:
            ValueError: 模式不存在。
        """
        for mode in self.profile.modes:
            if mode.name == mode_name:
                return mode
        available = [m.name for m in self.profile.modes]
        raise ValueError(
            f"Mode '{mode_name}' not supported by site '{self.site_name}'. "
            f"Available: {', '.join(available) or 'none'}"
        )

    def has_mode(self, mode_name: str) -> bool:
        """检查是否支持指定模式。"""
        return any(m.name == mode_name for m in self.profile.modes)

    @abstractmethod
    async def send_prompt(self, page: Any, prompt: str) -> None:
        """定位输入框、填充文本、点击发送。

        Args:
            page: Playwright Page 对象。
            prompt: 用户提示词。

        Raises:
            AdapterError: 输入框未找到或发送失败。
        """
        ...

    @abstractmethod
    async def select_mode(self, page: Any, mode: str) -> None:
        """选择模式（深度思考、联网搜索等）。

        Args:
            page: Playwright Page 对象。
            mode: 模式标识。

        Note:
            如果站点不支持该模式或模式已是激活状态，应静默跳过。
        """
        ...

    @abstractmethod
    async def extract_stream(self, page: Any) -> AsyncIterator[str]:
        """流式抓取响应 — 通过 DOM MutationObserver 或轮询获取增量文本。

        Args:
            page: Playwright Page 对象。

        Yields:
            流式输出的文本片段。
        """
        ...

    @abstractmethod
    async def wait_for_complete(self, page: Any) -> None:
        """等待响应完成 — 停止按钮消失或响应内容稳定。

        Args:
            page: Playwright Page 对象。

        Raises:
            TimeoutError: 超过完成检测超时时间。
        """
        ...

    @abstractmethod
    async def detect_login_expiry(self, page: Any) -> bool:
        """检测登录态是否过期。

        Args:
            page: Playwright Page 对象。

        Returns:
            True 表示登录已过期，需要重新认证。
        """
        ...

    async def interact(
        self,
        page: Any,
        prompt: str,
        mode: str = "",
    ) -> AsyncIterator[str]:
        """完整交互流程 — 发送提示 → 流式输出 → 等待完成。

        这是 BrowserAdapter 调用的主入口，封装了完整的安全检查和流程编排。

        Args:
            page: Playwright Page 对象。
            prompt: 用户提示词。
            mode: 模式标识（空字符串表示默认模式）。

        Yields:
            流式输出的文本片段。

        Raises:
            LoginExpiredError: 登录过期。
            RateLimitError: 触发限流。
            AdapterError: 其他适配器错误。
        """
        # 1. 安全检查
        self.safety.check_quota()

        try:
            # 2. 检测登录过期
            if await self.detect_login_expiry(page):
                raise LoginExpiredError(
                    self.site_name, self.profile.login_url
                )

            # 3. 选择模式（如有）
            if mode:
                await self.safety.human_delay("select_mode")
                await self.select_mode(page, mode)

            # 4. 发送提示
            await self.safety.human_delay("send_prompt")
            await self.send_prompt(page, prompt)
            self.safety.record_request()

            # 5. 流式抓取
            async for chunk in self.extract_stream(page):
                yield chunk

            # 6. 等待完成
            await self.wait_for_complete(page)

            self.safety.record_success()

        except (LoginExpiredError, RateLimitError):
            raise
        except Exception:
            self.safety.record_error()
            await self.safety.error_backoff()
            raise
