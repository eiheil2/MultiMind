"""Unit tests for ``multimind.adapters.sites`` — SiteAdapter 层。

测试覆盖：
  - SiteProfile 数据结构 + TOML 加载（5 个站点配置）
  - SafetyGuard 反封号守护（限流/熔断/延迟/退避）
  - SiteAdapter 抽象基类（interact 完整流程）
  - DeepSeekSite 站点特定逻辑（模式激活检测/登录 URL 检测）
  - GenericSiteAdapter 通用实现（发送/流式/完成检测）
  - 四个站点桩（ChatGPT/Qwen/Doubao/KIMI）
  - SiteAdapterRegistry 注册表
  - BrowserAdapter 重构后集成（桩模式降级/站点适配器委托）
  - SiteCapability 能力声明
  - validate_profile 配置校验（12 种错误场景）
  - discover_profiles 多目录搜索 + 用户配置覆盖
  - Registry 插件扩展（GenericSiteAdapter 兜底/unregister/动态注册）
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from multimind.adapters.browser import BrowserAdapter
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
    create_site_adapter,
    get_site_registry,
    reset_site_registry,
)
from multimind.core.exceptions import AdapterError
from multimind.core.types import ChannelType, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / (
    "src/multimind/adapters/sites/profiles"
)


# ═══════════════════════════════════════════════════════════════════════
# Mock 对象 — 模拟 Playwright Page / Element
# ═══════════════════════════════════════════════════════════════════════


class MockElement:
    """Mock DOM 元素。"""

    def __init__(self, text: str = "", visible: bool = True) -> None:
        self._text = text
        self._visible = visible
        self.click_count = 0
        self.fill_value = ""

    async def text_content(self) -> str:
        return self._text

    async def is_visible(self) -> bool:
        return self._visible

    async def click(self) -> None:
        self.click_count += 1

    async def fill(self, value: str) -> None:
        self.fill_value = value

    def set_text(self, text: str) -> None:
        self._text = text

    def set_visible(self, visible: bool) -> None:
        self._visible = visible


class StreamingElement:
    """Mock 元素 — 每次调用 text_content() 返回增长的文本。"""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = list(chunks)
        self._index = 0
        self._visible = True

    async def text_content(self) -> str:
        if self._index < len(self._chunks):
            text = self._chunks[self._index]
            self._index += 1
            return text
        return self._chunks[-1] if self._chunks else ""

    async def is_visible(self) -> bool:
        return self._visible

    async def click(self) -> None:
        pass

    def set_visible(self, visible: bool) -> None:
        self._visible = visible


class MockPage:
    """Mock Playwright Page — 模拟 DOM 交互。"""

    def __init__(self) -> None:
        self._url: str = ""
        self._filled: dict[str, str] = {}
        self._clicked: list[str] = []
        self._elements: dict[str, Any] = {}
        self._eval_results: dict[str, Any] = {}
        self._wait_calls: list[tuple[str, dict[str, Any]]] = []
        self._closed = False

    async def goto(self, url: str) -> None:
        self._url = url

    async def fill(self, selector: str, value: str) -> None:
        self._filled[selector] = value

    async def click(self, selector: str) -> None:
        self._clicked.append(selector)

    async def wait_for_selector(self, selector: str, **kwargs: Any) -> Any:
        self._wait_calls.append((selector, kwargs))
        return self._elements.get(selector, MockElement())

    async def query_selector(self, selector: str) -> Any:
        return self._elements.get(selector)

    async def evaluate(self, expression: str) -> Any:
        return self._eval_results.get(expression)

    async def close(self) -> None:
        self._closed = True

    # ── 辅助方法 ──

    def set_element(self, selector: str, element: Any) -> None:
        self._elements[selector] = element

    def set_eval(self, expression: str, result: Any) -> None:
        self._eval_results[expression] = result

    @property
    def filled(self) -> dict[str, str]:
        return dict(self._filled)

    @property
    def clicked(self) -> list[str]:
        return list(self._clicked)


async def _collect(stream: AsyncIterator[str]) -> str:
    """消费异步迭代器为字符串。"""
    return "".join([chunk async for chunk in stream])


def _fast_safety(**overrides: Any) -> SafetyConfig:
    """创建快速测试安全配置（零延迟）。"""
    defaults: dict[str, Any] = {
        "min_delay": 0.0,
        "max_delay": 0.0,
        "max_requests_per_session": 10,
        "session_timeout": 3600,
        "headed": True,
        "max_consecutive_errors": 3,
    }
    defaults.update(overrides)
    return SafetyConfig(**defaults)


def _fast_completion(**overrides: Any) -> CompletionConfig:
    """创建快速测试完成配置。"""
    defaults: dict[str, Any] = {
        "method": "stop_button_disappear",
        "timeout": 2,
        "stable_duration": 0.05,
        "poll_interval": 0.01,
    }
    defaults.update(overrides)
    return CompletionConfig(**defaults)


def _make_profile(
    name: str = "test",
    url: str = "https://test.example.com",
    safety: SafetyConfig | None = None,
    completion: CompletionConfig | None = None,
    modes: tuple[SiteMode, ...] = (),
    selectors: SiteSelectors | None = None,
) -> SiteProfile:
    """创建测试用站点配置。"""
    return SiteProfile(
        name=name,
        url=url,
        login_url=f"{url}/login",
        selectors=selectors
        or SiteSelectors(
            input_box="textarea.input",
            send_button="button.send",
            response_container="div.response",
            stop_button="button.stop",
            login_redirect="div.login",
        ),
        modes=modes,
        safety=safety or _fast_safety(),
        completion=completion or _fast_completion(),
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. SiteProfile 数据结构
# ═══════════════════════════════════════════════════════════════════════


class TestSiteProfile:
    """SiteProfile 不可变值对象测试。"""

    def test_selectors_defaults(self) -> None:
        """SiteSelectors 有合理的默认值。"""
        sel = SiteSelectors(input_box="input", send_button="btn", response_container="div")
        assert sel.stop_button == ""
        assert sel.login_redirect == ""
        assert sel.mode_container == ""

    def test_safety_defaults(self) -> None:
        """SafetyConfig 默认值合理。"""
        s = SafetyConfig()
        assert s.min_delay == 1.0
        assert s.max_delay == 3.0
        assert s.max_requests_per_session == 50
        assert s.session_timeout == 3600
        assert s.headed is True
        assert s.max_consecutive_errors == 5

    def test_completion_defaults(self) -> None:
        """CompletionConfig 默认值合理。"""
        c = CompletionConfig()
        assert c.method == "stop_button_disappear"
        assert c.timeout == 120
        assert c.stable_duration == 2.0
        assert c.poll_interval == 0.5

    def test_profile_is_frozen(self) -> None:
        """SiteProfile 是不可变的。"""
        profile = _make_profile()
        with pytest.raises(AttributeError):
            profile.name = "other"  # type: ignore[misc]

    def test_profile_with_modes(self) -> None:
        """SiteProfile 可以包含模式列表。"""
        modes = (
            SiteMode(name="mode1", label="Mode 1", selector="btn1"),
            SiteMode(name="mode2", label="Mode 2", selector="btn2"),
        )
        profile = _make_profile(modes=modes)
        assert len(profile.modes) == 2
        assert profile.modes[0].name == "mode1"
        assert profile.modes[1].selector == "btn2"


# ═══════════════════════════════════════════════════════════════════════
# 2. TOML 配置加载
# ═══════════════════════════════════════════════════════════════════════


class TestProfileLoading:
    """TOML 配置文件加载测试。"""

    def test_load_deepseek_profile(self) -> None:
        """DeepSeek 配置文件可正确加载。"""
        profile = load_profile_by_name("deepseek")
        assert profile.name == "deepseek"
        assert "deepseek.com" in profile.url
        assert profile.selectors.input_box != ""
        assert profile.selectors.send_button != ""
        assert len(profile.modes) == 2

    @pytest.mark.parametrize("site_name", ["deepseek", "chatgpt", "qwen", "doubao", "kimi"])
    def test_load_all_profiles(self, site_name: str) -> None:
        """所有 5 个站点配置文件均可加载。"""
        profile = load_profile_by_name(site_name)
        assert profile.name == site_name
        assert profile.url.startswith("https://")
        assert profile.selectors.input_box != ""
        assert profile.selectors.send_button != ""
        assert profile.selectors.response_container != ""
        assert len(profile.modes) > 0
        assert profile.safety.min_delay > 0
        assert profile.safety.max_delay >= profile.safety.min_delay

    def test_load_profile_by_name_not_found(self) -> None:
        """不存在的站点名抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError, match="not found"):
            load_profile_by_name("nonexistent_site")

    def test_load_profile_selectors_populated(self) -> None:
        """加载的选择器字段不为空。"""
        profile = load_profile_by_name("deepseek")
        assert profile.selectors.input_box
        assert profile.selectors.send_button
        assert profile.selectors.response_container
        assert profile.selectors.stop_button

    def test_load_profile_modes_have_labels(self) -> None:
        """加载的模式有 label 和 selector。"""
        profile = load_profile_by_name("qwen")
        for mode in profile.modes:
            assert mode.name
            assert mode.label
            assert mode.selector

    def test_load_profile_safety_headed_default(self) -> None:
        """所有站点默认使用有头模式。"""
        for site_name in ["deepseek", "chatgpt", "qwen", "doubao", "kimi"]:
            profile = load_profile_by_name(site_name)
            assert profile.safety.headed is True, f"{site_name} should default to headed mode"

    def test_load_profile_from_path(self, tmp_path: Path) -> None:
        """从指定路径加载 TOML 配置。"""
        toml_content = b'''
[site]
name = "custom"
url = "https://custom.example.com"

[selectors]
input_box = "input"
send_button = "button"
response_container = "div"

[[modes]]
name = "default"
label = "Default"
selector = "btn"

[safety]
min_delay = 0.5
max_delay = 1.5
'''
        path = tmp_path / "custom.toml"
        path.write_bytes(toml_content)

        profile = load_profile(path)
        assert profile.name == "custom"
        assert profile.safety.min_delay == 0.5
        assert len(profile.modes) == 1


# ═══════════════════════════════════════════════════════════════════════
# 3. SafetyGuard 反封号守护
# ═══════════════════════════════════════════════════════════════════════


class TestSafetyGuard:
    """SafetyGuard 限流/熔断/延迟测试。"""

    def test_check_quota_ok(self) -> None:
        """未超限时 check_quota 不抛异常。"""
        guard = SafetyGuard(_fast_safety(max_requests_per_session=10))
        guard.check_quota()  # should not raise

    def test_check_quota_request_limit(self) -> None:
        """超过请求上限时抛出 RateLimitError。"""
        guard = SafetyGuard(_fast_safety(max_requests_per_session=3))
        guard.record_request()
        guard.record_request()
        guard.record_request()
        with pytest.raises(RateLimitError, match="request limit"):
            guard.check_quota()

    def test_check_quota_session_timeout(self) -> None:
        """会话超时时抛出 RateLimitError。"""
        guard = SafetyGuard(_fast_safety(session_timeout=0))
        # session_timeout=0 means immediately expired
        with pytest.raises(RateLimitError, match="session timeout"):
            guard.check_quota()

    def test_check_quota_circuit_breaker(self) -> None:
        """连续错误达到熔断阈值时抛出 RateLimitError。"""
        guard = SafetyGuard(_fast_safety(max_consecutive_errors=3))
        guard.record_error()
        guard.record_error()
        guard.record_error()
        with pytest.raises(RateLimitError, match="circuit breaker"):
            guard.check_quota()

    def test_record_request_increments(self) -> None:
        """record_request 递增计数器。"""
        guard = SafetyGuard(_fast_safety())
        assert guard.request_count == 0
        guard.record_request()
        guard.record_request()
        assert guard.request_count == 2

    def test_record_success_resets_errors(self) -> None:
        """record_success 重置连续错误计数。"""
        guard = SafetyGuard(_fast_safety())
        guard.record_error()
        guard.record_error()
        assert guard.consecutive_errors == 2
        guard.record_success()
        assert guard.consecutive_errors == 0

    def test_record_error_increments(self) -> None:
        """record_error 递增连续错误计数。"""
        guard = SafetyGuard(_fast_safety())
        guard.record_error()
        assert guard.consecutive_errors == 1
        guard.record_error()
        assert guard.consecutive_errors == 2

    @pytest.mark.asyncio
    async def test_human_delay_calls_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """human_delay 调用 asyncio.sleep。"""
        guard = SafetyGuard(SafetyConfig(min_delay=1.0, max_delay=2.0))
        delays: list[float] = []

        async def mock_sleep(seconds: float) -> None:
            delays.append(seconds)

        monkeypatch.setattr(
            "multimind.adapters.sites.base.asyncio.sleep", mock_sleep
        )
        await guard.human_delay("test")
        assert len(delays) == 1
        assert 1.0 <= delays[0] <= 2.0

    @pytest.mark.asyncio
    async def test_error_backoff_returns_delay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """error_backoff 返回退避时间并调用 sleep。"""
        guard = SafetyGuard(_fast_safety())
        guard.record_error()
        guard.record_error()

        actual_delay: list[float] = []

        async def mock_sleep(seconds: float) -> None:
            actual_delay.append(seconds)

        monkeypatch.setattr(
            "multimind.adapters.sites.base.asyncio.sleep", mock_sleep
        )
        result = await guard.error_backoff()
        # 2 errors → backoff = 2.0 * 2^2 = 8.0
        assert result == 8.0
        assert len(actual_delay) == 1

    def test_reset_session(self) -> None:
        """reset_session 清零所有计数器。"""
        guard = SafetyGuard(_fast_safety())
        guard.record_request()
        guard.record_error()
        guard.reset_session()
        assert guard.request_count == 0
        assert guard.consecutive_errors == 0

    def test_session_elapsed_increases(self) -> None:
        """session_elapsed 随时间增长。"""
        import time

        guard = SafetyGuard(_fast_safety())
        elapsed_before = guard.session_elapsed
        time.sleep(0.01)
        assert guard.session_elapsed > elapsed_before


# ═══════════════════════════════════════════════════════════════════════
# 4. SiteAdapter 抽象基类
# ═══════════════════════════════════════════════════════════════════════


class _ConcreteSiteAdapter(SiteAdapter):
    """测试用具体 SiteAdapter 实现。"""

    site_name = "concrete"

    def __init__(self, profile: SiteProfile | None = None) -> None:
        super().__init__(profile or _make_profile("concrete"))
        self.send_prompt_called = False
        self.select_mode_called = False
        self.wait_for_complete_called = False

    async def send_prompt(self, page: Any, prompt: str) -> None:
        self.send_prompt_called = True
        self.last_prompt = prompt

    async def select_mode(self, page: Any, mode: str) -> None:
        self.select_mode_called = True
        self.last_mode = mode

    async def extract_stream(self, page: Any) -> AsyncIterator[str]:
        yield "chunk1"
        yield "chunk2"
        yield "chunk3"

    async def wait_for_complete(self, page: Any) -> None:
        self.wait_for_complete_called = True

    async def detect_login_expiry(self, page: Any) -> bool:
        return self._login_expired

    def set_login_expired(self, expired: bool) -> None:
        self._login_expired = expired


class TestSiteAdapterBase:
    """SiteAdapter 抽象基类测试。"""

    def test_get_mode_found(self) -> None:
        """get_mode 返回匹配的模式配置。"""
        modes = (SiteMode(name="mode1", label="Mode 1", selector="btn1"),)
        adapter = _ConcreteSiteAdapter(_make_profile(modes=modes))
        mode = adapter.get_mode("mode1")
        assert mode.name == "mode1"

    def test_get_mode_not_found(self) -> None:
        """get_mode 模式不存在时抛出 ValueError。"""
        adapter = _ConcreteSiteAdapter()
        with pytest.raises(ValueError, match="not supported"):
            adapter.get_mode("nonexistent")

    def test_has_mode(self) -> None:
        """has_mode 返回正确的布尔值。"""
        modes = (SiteMode(name="mode1", label="Mode 1", selector="btn1"),)
        adapter = _ConcreteSiteAdapter(_make_profile(modes=modes))
        assert adapter.has_mode("mode1") is True
        assert adapter.has_mode("mode2") is False

    @pytest.mark.asyncio
    async def test_interact_success(self) -> None:
        """interact 完整流程：检查配额 → 检测登录 → 发送 → 流式 → 完成。"""
        adapter = _ConcreteSiteAdapter()
        adapter.set_login_expired(False)
        page = MockPage()

        chunks = await _collect(adapter.interact(page, "hello", mode=""))

        assert chunks == "chunk1chunk2chunk3"
        assert adapter.send_prompt_called
        assert adapter.wait_for_complete_called
        assert adapter.safety.request_count == 1
        assert adapter.safety.consecutive_errors == 0

    @pytest.mark.asyncio
    async def test_interact_login_expired(self) -> None:
        """interact 检测到登录过期时抛出 LoginExpiredError。"""
        adapter = _ConcreteSiteAdapter()
        adapter.set_login_expired(True)
        page = MockPage()

        with pytest.raises(LoginExpiredError):
            await _collect(adapter.interact(page, "hello"))

    @pytest.mark.asyncio
    async def test_interact_rate_limit(self) -> None:
        """interact 触发限流时抛出 RateLimitError。"""
        adapter = _ConcreteSiteAdapter(
            _make_profile(safety=_fast_safety(max_requests_per_session=1))
        )
        adapter.safety.record_request()
        adapter.set_login_expired(False)
        page = MockPage()

        with pytest.raises(RateLimitError):
            await _collect(adapter.interact(page, "hello"))

    @pytest.mark.asyncio
    async def test_interact_error_records_and_backs_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """interact 发生错误时记录错误并执行退避。"""
        adapter = _ConcreteSiteAdapter()
        adapter.set_login_expired(False)
        page = MockPage()

        # 让 send_prompt 抛出异常
        async def fail_send(pg: Any, prompt: str) -> None:
            raise RuntimeError(" simulated error")

        adapter.send_prompt = fail_send  # type: ignore[method-assign]

        backoff_called: list[float] = []

        async def mock_sleep(seconds: float) -> None:
            backoff_called.append(seconds)

        monkeypatch.setattr(
            "multimind.adapters.sites.base.asyncio.sleep", mock_sleep
        )

        with pytest.raises(RuntimeError):
            await _collect(adapter.interact(page, "hello"))

        assert adapter.safety.consecutive_errors == 1
        assert len(backoff_called) > 0  # backoff was called


# ═══════════════════════════════════════════════════════════════════════
# 5. DeepSeekSite 站点特定逻辑
# ═══════════════════════════════════════════════════════════════════════


class TestDeepSeekSite:
    """DeepSeek 站点适配器测试。"""

    def test_site_name(self) -> None:
        """DeepSeekSite 的 site_name 是 'deepseek'。"""
        adapter = DeepSeekSite(_make_profile("deepseek"))
        assert adapter.site_name == "deepseek"

    @pytest.mark.asyncio
    async def test_send_prompt(self) -> None:
        """send_prompt 填充输入框并点击发送。"""
        adapter = DeepSeekSite(_make_profile("deepseek"))
        page = MockPage()

        await adapter.send_prompt(page, "test prompt")

        assert "textarea.input" in page.filled
        assert page.filled["textarea.input"] == "test prompt"
        assert "button.send" in page.clicked

    @pytest.mark.asyncio
    async def test_send_prompt_error(self) -> None:
        """send_prompt 失败时抛出 AdapterError。"""
        adapter = DeepSeekSite(_make_profile("deepseek"))
        page = MockPage()

        # 让 wait_for_selector 抛出异常
        async def fail_wait(selector: str, **kw: Any) -> Any:
            raise RuntimeError("timeout")

        page.wait_for_selector = fail_wait  # type: ignore[method-assign]

        with pytest.raises(AdapterError, match="send_prompt failed"):
            await adapter.send_prompt(page, "test")

    @pytest.mark.asyncio
    async def test_select_mode_already_active(self) -> None:
        """模式已激活时跳过点击。"""
        modes = (SiteMode(name="deep_thinking", label="深度思考", selector="btn.deep"),)
        adapter = DeepSeekSite(_make_profile("deepseek", modes=modes))
        page = MockPage()

        # 设置 evaluate 返回 True（已激活）
        page.set_eval(
            '() => {\n                    const el = document.querySelector("btn.deep");\n'
            '                    if (!el) return false;\n                    return '
            'el.getAttribute("aria-pressed") === "true" ||\n                           '
            'el.classList.contains("active");\n                }',
            True,
        )

        await adapter.select_mode(page, "deep_thinking")

        assert "btn.deep" not in page.clicked

    @pytest.mark.asyncio
    async def test_select_mode_not_active(self) -> None:
        """模式未激活时点击切换。"""
        modes = (SiteMode(name="deep_thinking", label="深度思考", selector="btn.deep"),)
        adapter = DeepSeekSite(_make_profile("deepseek", modes=modes))
        page = MockPage()

        # 设置 evaluate 返回 False（未激活）
        page.set_eval(
            '() => {\n                    const el = document.querySelector("btn.deep");\n'
            '                    if (!el) return false;\n                    return '
            'el.getAttribute("aria-pressed") === "true" ||\n                           '
            'el.classList.contains("active");\n                }',
            False,
        )

        await adapter.select_mode(page, "deep_thinking")

        assert "btn.deep" in page.clicked

    @pytest.mark.asyncio
    async def test_select_mode_unsupported(self) -> None:
        """不支持的模式静默跳过。"""
        adapter = DeepSeekSite(_make_profile("deepseek"))
        page = MockPage()

        await adapter.select_mode(page, "nonexistent")
        assert len(page.clicked) == 0

    @pytest.mark.asyncio
    async def test_detect_login_expiry_by_url(self) -> None:
        """通过 URL 检测登录过期。"""
        adapter = DeepSeekSite(_make_profile("deepseek"))
        page = MockPage()

        page.set_eval("() => window.location.href", "https://chat.deepseek.com/sign_in")

        result = await adapter.detect_login_expiry(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_login_expiry_by_element(self) -> None:
        """通过登录重定向元素检测登录过期。"""
        adapter = DeepSeekSite(_make_profile("deepseek"))
        page = MockPage()
        page.set_element("div.login", MockElement())

        # URL 不含 sign_in
        page.set_eval("() => window.location.href", "https://chat.deepseek.com/chat")

        result = await adapter.detect_login_expiry(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_login_expiry_ok(self) -> None:
        """正常状态返回 False。"""
        adapter = DeepSeekSite(_make_profile("deepseek"))
        page = MockPage()

        page.set_eval("() => window.location.href", "https://chat.deepseek.com/chat")

        result = await adapter.detect_login_expiry(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_extract_stream_yields_deltas(self) -> None:
        """extract_stream 正确输出增量文本。"""
        profile = _make_profile(
            "deepseek",
            completion=_fast_completion(method="response_stable", stable_duration=0.02),
        )
        adapter = DeepSeekSite(profile)
        page = MockPage()

        # 响应容器返回增长的文本
        page.set_element(
            "div.response",
            StreamingElement(["Hello", "Hello world", "Hello world!"]),
        )

        result = await _collect(adapter.extract_stream(page))
        assert "Hello" in result
        assert "world" in result
        assert "!" in result

    @pytest.mark.asyncio
    async def test_extract_stream_no_container(self) -> None:
        """响应容器不存在时返回空。"""
        adapter = DeepSeekSite(
            _make_profile("deepseek", completion=_fast_completion(timeout=0))
        )
        page = MockPage()

        # 不设置响应容器元素
        async def fail_wait(selector: str, **kw: Any) -> Any:
            raise RuntimeError("not found")

        page.wait_for_selector = fail_wait  # type: ignore[method-assign]

        result = await _collect(adapter.extract_stream(page))
        assert result == ""


# ═══════════════════════════════════════════════════════════════════════
# 6. GenericSiteAdapter 通用实现
# ═══════════════════════════════════════════════════════════════════════


class TestGenericSiteAdapter:
    """GenericSiteAdapter 通用适配器测试。"""

    def test_inherits_site_adapter(self) -> None:
        """GenericSiteAdapter 继承 SiteAdapter。"""
        adapter = GenericSiteAdapter(_make_profile("generic"))
        assert isinstance(adapter, SiteAdapter)

    @pytest.mark.asyncio
    async def test_send_prompt_fills_and_clicks(self) -> None:
        """send_prompt 填充输入框并点击发送按钮。"""
        adapter = GenericSiteAdapter(_make_profile("generic"))
        page = MockPage()

        await adapter.send_prompt(page, "hello world")

        assert page.filled.get("textarea.input") == "hello world"
        assert "button.send" in page.clicked

    @pytest.mark.asyncio
    async def test_send_prompt_error_raises(self) -> None:
        """send_prompt 失败时抛出 AdapterError。"""
        adapter = GenericSiteAdapter(_make_profile("generic"))
        page = MockPage()

        async def fail_wait(selector: str, **kw: Any) -> Any:
            raise RuntimeError("timeout")

        page.wait_for_selector = fail_wait  # type: ignore[method-assign]

        with pytest.raises(AdapterError):
            await adapter.send_prompt(page, "test")

    @pytest.mark.asyncio
    async def test_select_mode_clicks_button(self) -> None:
        """select_mode 点击模式按钮。"""
        modes = (SiteMode(name="mode1", label="Mode 1", selector="btn.mode1"),)
        adapter = GenericSiteAdapter(_make_profile("generic", modes=modes))
        page = MockPage()
        element = MockElement()
        page.set_element("btn.mode1", element)

        await adapter.select_mode(page, "mode1")

        assert element.click_count > 0

    @pytest.mark.asyncio
    async def test_select_mode_button_not_found(self) -> None:
        """模式按钮不存在时静默跳过。"""
        modes = (SiteMode(name="mode1", label="Mode 1", selector="btn.mode1"),)
        adapter = GenericSiteAdapter(_make_profile("generic", modes=modes))
        page = MockPage()

        await adapter.select_mode(page, "mode1")
        # 不应抛出异常

    @pytest.mark.asyncio
    async def test_select_mode_unsupported(self) -> None:
        """不支持的模式静默跳过。"""
        adapter = GenericSiteAdapter(_make_profile("generic"))
        page = MockPage()

        await adapter.select_mode(page, "nonexistent")
        assert len(page.clicked) == 0

    @pytest.mark.asyncio
    async def test_detect_login_expiry_with_element(self) -> None:
        """存在登录重定向元素时返回 True。"""
        adapter = GenericSiteAdapter(_make_profile("generic"))
        page = MockPage()
        page.set_element("div.login", MockElement())

        result = await adapter.detect_login_expiry(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_detect_login_expiry_without_element(self) -> None:
        """不存在登录重定向元素时返回 False。"""
        adapter = GenericSiteAdapter(_make_profile("generic"))
        page = MockPage()

        result = await adapter.detect_login_expiry(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_login_expiry_no_selector(self) -> None:
        """未配置 login_redirect 选择器时返回 False。"""
        profile = _make_profile(
            "generic",
            selectors=SiteSelectors(
                input_box="input", send_button="btn", response_container="div"
            ),
        )
        adapter = GenericSiteAdapter(profile)
        page = MockPage()

        result = await adapter.detect_login_expiry(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_extract_stream_stable_completion(self) -> None:
        """response_stable 完成检测正确结束流。"""
        profile = _make_profile(
            "generic",
            completion=_fast_completion(
                method="response_stable", stable_duration=0.02, poll_interval=0.01
            ),
        )
        adapter = GenericSiteAdapter(profile)
        page = MockPage()

        page.set_element(
            "div.response",
            StreamingElement(["A", "AB", "ABC"]),
        )

        result = await _collect(adapter.extract_stream(page))
        assert result == "ABC"

    @pytest.mark.asyncio
    async def test_is_generation_complete_no_stop_button(self) -> None:
        """未配置停止按钮时返回 False。"""
        profile = _make_profile(
            "generic",
            selectors=SiteSelectors(
                input_box="input", send_button="btn", response_container="div"
            ),
        )
        adapter = GenericSiteAdapter(profile)
        page = MockPage()

        result = await adapter._is_generation_complete(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_generation_complete_button_gone(self) -> None:
        """停止按钮不存在时返回 True。"""
        adapter = GenericSiteAdapter(_make_profile("generic"))
        page = MockPage()
        # 不设置停止按钮元素 → query_selector 返回 None

        result = await adapter._is_generation_complete(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_generation_complete_button_invisible(self) -> None:
        """停止按钮不可见时返回 True。"""
        adapter = GenericSiteAdapter(_make_profile("generic"))
        page = MockPage()
        page.set_element("button.stop", MockElement(visible=False))

        result = await adapter._is_generation_complete(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_complete_no_stop_button(self) -> None:
        """未配置停止按钮时 wait_for_complete 静默返回。"""
        profile = _make_profile(
            "generic",
            selectors=SiteSelectors(
                input_box="input", send_button="btn", response_container="div"
            ),
        )
        adapter = GenericSiteAdapter(profile)
        page = MockPage()

        await adapter.wait_for_complete(page)  # should not raise


# ═══════════════════════════════════════════════════════════════════════
# 7. 站点桩（ChatGPT / Qwen / Doubao / KIMI）
# ═══════════════════════════════════════════════════════════════════════


class TestSiteStubs:
    """四个站点桩适配器测试。"""

    def test_chatgpt_site_name(self) -> None:
        """ChatGPTSite 的 site_name 是 'chatgpt'。"""
        adapter = ChatGPTSite(_make_profile("chatgpt"))
        assert adapter.site_name == "chatgpt"

    def test_qwen_site_name(self) -> None:
        """QwenSite 的 site_name 是 'qwen'。"""
        adapter = QwenSite(_make_profile("qwen"))
        assert adapter.site_name == "qwen"

    def test_doubao_site_name(self) -> None:
        """DoubaoSite 的 site_name 是 'doubao'。"""
        adapter = DoubaoSite(_make_profile("doubao"))
        assert adapter.site_name == "doubao"

    def test_kimi_site_name(self) -> None:
        """KimiSite 的 site_name 是 'kimi'。"""
        adapter = KimiSite(_make_profile("kimi"))
        assert adapter.site_name == "kimi"

    def test_all_stubs_inherit_generic(self) -> None:
        """所有站点桩继承 GenericSiteAdapter。"""
        for cls in [ChatGPTSite, QwenSite, DoubaoSite, KimiSite]:
            assert issubclass(cls, GenericSiteAdapter)

    def test_all_stubs_inherit_site_adapter(self) -> None:
        """所有站点桩继承 SiteAdapter。"""
        for cls in [ChatGPTSite, QwenSite, DoubaoSite, KimiSite]:
            assert issubclass(cls, SiteAdapter)

    def test_all_stubs_have_safety_guard(self) -> None:
        """所有站点桩都有 SafetyGuard 实例。"""
        for cls, name in [
            (ChatGPTSite, "chatgpt"),
            (QwenSite, "qwen"),
            (DoubaoSite, "doubao"),
            (KimiSite, "kimi"),
        ]:
            adapter = cls(_make_profile(name))
            assert isinstance(adapter.safety, SafetyGuard)

    @pytest.mark.asyncio
    async def test_chatgpt_send_prompt(self) -> None:
        """ChatGPTSite 可以发送提示。"""
        adapter = ChatGPTSite(_make_profile("chatgpt"))
        page = MockPage()

        await adapter.send_prompt(page, "test")

        assert page.filled.get("textarea.input") == "test"
        assert "button.send" in page.clicked


# ═══════════════════════════════════════════════════════════════════════
# 8. SiteAdapterRegistry 注册表
# ═══════════════════════════════════════════════════════════════════════


class TestSiteAdapterRegistry:
    """站点适配器注册表测试。"""

    def setup_method(self) -> None:
        """每个测试前重置注册表。"""
        reset_site_registry()

    def teardown_method(self) -> None:
        """每个测试后重置注册表。"""
        reset_site_registry()

    def test_create_deepseek(self) -> None:
        """create 返回 DeepSeekSite 实例。"""
        registry = get_site_registry()
        adapter = registry.create("deepseek")
        assert isinstance(adapter, DeepSeekSite)
        assert adapter.site_name == "deepseek"

    def test_create_all_sites(self) -> None:
        """所有 5 个站点均可创建。"""
        registry = get_site_registry()
        for site_name in ["deepseek", "chatgpt", "qwen", "doubao", "kimi"]:
            adapter = registry.create(site_name)
            assert adapter is not None
            assert adapter.site_name == site_name

    def test_create_unknown_site(self) -> None:
        """未知站点抛出 KeyError。"""
        registry = get_site_registry()
        with pytest.raises(KeyError, match="not registered"):
            registry.create("nonexistent")

    def test_create_cached(self) -> None:
        """重复 create 返回缓存的实例。"""
        registry = get_site_registry()
        adapter1 = registry.create("deepseek")
        adapter2 = registry.create("deepseek")
        assert adapter1 is adapter2

    def test_create_force_reload(self) -> None:
        """force_reload=True 返回新实例。"""
        registry = get_site_registry()
        adapter1 = registry.create("deepseek")
        adapter2 = registry.create("deepseek", force_reload=True)
        assert adapter1 is not adapter2

    def test_available_sites(self) -> None:
        """available_sites 返回所有注册的站点名。"""
        registry = get_site_registry()
        sites = registry.available_sites()
        assert "deepseek" in sites
        assert "chatgpt" in sites
        assert "qwen" in sites
        assert "doubao" in sites
        assert "kimi" in sites

    def test_register_custom(self) -> None:
        """register 注册自定义适配器。"""
        registry = get_site_registry()
        registry.register("custom", GenericSiteAdapter)
        assert "custom" in registry.available_sites()

    def test_reset_clears_instances(self) -> None:
        """reset 清除缓存的实例。"""
        registry = get_site_registry()
        registry.create("deepseek")
        assert len(registry._instances) > 0
        registry.reset()
        assert len(registry._instances) == 0

    def test_singleton(self) -> None:
        """get_site_registry 返回单例。"""
        r1 = get_site_registry()
        r2 = get_site_registry()
        assert r1 is r2

    def test_create_site_adapter_convenience(self) -> None:
        """create_site_adapter 便捷函数正常工作。"""
        reset_site_registry()
        adapter = create_site_adapter("deepseek")
        assert isinstance(adapter, DeepSeekSite)


# ═══════════════════════════════════════════════════════════════════════
# 9. BrowserAdapter 重构后集成
# ═══════════════════════════════════════════════════════════════════════


class TestBrowserAdapterRefactored:
    """BrowserAdapter 重构后测试。"""

    def _config(self, name: str = "deepseek") -> ProviderConfig:
        return ProviderConfig(name=name, channel=ChannelType.BROWSER)

    def test_site_name_inference(self) -> None:
        """从 config.name 正确推断站点名。"""
        for name, expected in [
            ("deepseek", "deepseek"),
            ("chatgpt", "chatgpt"),
            ("qwen", "qwen"),
            ("doubao", "doubao"),
            ("kimi", "kimi"),
        ]:
            adapter = BrowserAdapter(self._config(name))
            assert adapter._site_name == expected

    def test_site_name_inference_unknown(self) -> None:
        """未知 provider 名的站点名为空。"""
        adapter = BrowserAdapter(self._config("unknown_provider"))
        assert adapter._site_name == ""

    def test_set_site_adapter(self) -> None:
        """set_site_adapter 手动设置适配器。"""
        adapter = BrowserAdapter(self._config("deepseek"))
        site_adapter = DeepSeekSite(_make_profile("deepseek"))
        adapter.set_site_adapter(site_adapter)
        assert adapter._site_adapter is site_adapter

    def test_set_storage_state(self, tmp_path: Path) -> None:
        """set_storage_state 设置路径。"""
        adapter = BrowserAdapter(self._config("deepseek"))
        path = tmp_path / "state.json"
        adapter.set_storage_state(path)
        assert adapter._storage_state == path

    @pytest.mark.asyncio
    async def test_ask_stub_no_site_adapter(self) -> None:
        """无站点适配器时降级桩模式。"""
        adapter = BrowserAdapter(self._config("unknown_provider"))
        output = await _collect(adapter.ask("test prompt"))
        assert "stub" in output.lower() or "not configured" in output.lower()

    @pytest.mark.asyncio
    async def test_ask_stub_no_playwright(self) -> None:
        """站点适配器已加载但 Playwright 未安装时降级桩模式。"""
        adapter = BrowserAdapter(self._config("deepseek"))
        output = await _collect(adapter.ask("test prompt"))
        assert "stub" in output.lower() or "not installed" in output.lower()

    @pytest.mark.asyncio
    async def test_ask_with_mock_site_adapter(self) -> None:
        """使用 mock 站点适配器测试完整流程。"""
        adapter = BrowserAdapter(self._config("deepseek"))

        # 创建 mock 站点适配器
        mock_site = MagicMock(spec=SiteAdapter)
        mock_site.site_name = "deepseek"
        mock_site.profile = _make_profile("deepseek")

        async def mock_interact(page: Any, prompt: str, mode: str) -> AsyncIterator[str]:
            yield "response_chunk_1"
            yield "response_chunk_2"

        mock_site.interact = mock_interact
        mock_site.safety = SafetyGuard(_fast_safety())

        adapter.set_site_adapter(mock_site)

        # 设置 page 以跳过 Playwright 初始化
        adapter._page = MockPage()

        output = await _collect(adapter.ask("test prompt"))

        assert "response_chunk_1" in output
        assert "response_chunk_2" in output
        assert adapter._used_today == 1

    @pytest.mark.asyncio
    async def test_ask_login_expired_handling(self) -> None:
        """登录过期时输出友好提示。"""
        adapter = BrowserAdapter(self._config("deepseek"))

        mock_site = MagicMock(spec=SiteAdapter)
        mock_site.site_name = "deepseek"
        mock_site.profile = _make_profile("deepseek")
        mock_site.safety = SafetyGuard(_fast_safety())

        async def mock_interact(page: Any, prompt: str, mode: str) -> AsyncIterator[str]:
            raise LoginExpiredError("deepseek", "https://example.com/login")
            yield  # type: ignore[unreachable]

        mock_site.interact = mock_interact
        adapter.set_site_adapter(mock_site)
        adapter._page = MockPage()

        output = await _collect(adapter.ask("test prompt"))
        assert "登录已过期" in output

    @pytest.mark.asyncio
    async def test_ask_rate_limit_handling(self) -> None:
        """触发限流时输出友好提示。"""
        adapter = BrowserAdapter(self._config("deepseek"))

        mock_site = MagicMock(spec=SiteAdapter)
        mock_site.site_name = "deepseek"
        mock_site.profile = _make_profile("deepseek")
        mock_site.safety = SafetyGuard(_fast_safety())

        async def mock_interact(page: Any, prompt: str, mode: str) -> AsyncIterator[str]:
            raise RateLimitError("too many requests")
            yield  # type: ignore[unreachable]

        mock_site.interact = mock_interact
        adapter.set_site_adapter(mock_site)
        adapter._page = MockPage()

        output = await _collect(adapter.ask("test prompt"))
        assert "限流" in output

    @pytest.mark.asyncio
    async def test_ask_generic_error_handling(self) -> None:
        """通用异常时输出错误信息。"""
        adapter = BrowserAdapter(self._config("deepseek"))

        mock_site = MagicMock(spec=SiteAdapter)
        mock_site.site_name = "deepseek"
        mock_site.profile = _make_profile("deepseek")
        mock_site.safety = SafetyGuard(_fast_safety())

        async def mock_interact(page: Any, prompt: str, mode: str) -> AsyncIterator[str]:
            raise RuntimeError("something went wrong")
            yield  # type: ignore[unreachable]

        mock_site.interact = mock_interact
        adapter.set_site_adapter(mock_site)
        adapter._page = MockPage()

        output = await _collect(adapter.ask("test prompt"))
        assert "交互失败" in output

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        """close 关闭所有资源。"""
        adapter = BrowserAdapter(self._config("deepseek"))

        mock_page = AsyncMock()
        mock_browser = AsyncMock()
        mock_playwright = AsyncMock()

        adapter._page = mock_page
        adapter._browser = mock_browser
        adapter._playwright = mock_playwright

        await adapter.close()

        mock_page.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()
        assert adapter._page is None
        assert adapter._browser is None
        assert adapter._playwright is None

    @pytest.mark.asyncio
    async def test_close_with_no_resources(self) -> None:
        """close 在无资源时不抛异常。"""
        adapter = BrowserAdapter(self._config("deepseek"))
        await adapter.close()  # should not raise

    @pytest.mark.asyncio
    async def test_default_url(self) -> None:
        """_default_url 返回正确的 URL。"""
        adapter = BrowserAdapter(self._config("deepseek"))
        assert "deepseek.com" in adapter._default_url()
        adapter2 = BrowserAdapter(self._config("chatgpt"))
        assert "chatgpt.com" in adapter2._default_url()


# ═══════════════════════════════════════════════════════════════════════
# 10. SiteCapability 能力声明
# ═══════════════════════════════════════════════════════════════════════


class TestSiteCapability:
    """SiteCapability 能力声明测试。"""

    def test_defaults(self) -> None:
        """SiteCapability 默认值合理。"""
        cap = SiteCapability()
        assert cap.streaming is True
        assert cap.file_upload is False
        assert cap.multi_turn is True
        assert cap.mode_switching is False
        assert cap.max_input_length == 10000
        assert cap.custom == ()

    def test_frozen(self) -> None:
        """SiteCapability 是不可变的。"""
        cap = SiteCapability()
        with pytest.raises(AttributeError):
            cap.streaming = False  # type: ignore[misc]

    def test_custom_tuple(self) -> None:
        """custom 字段支持元组。"""
        cap = SiteCapability(custom=("image_gen", "code_exec"))
        assert "image_gen" in cap.custom
        assert len(cap.custom) == 2

    def test_profile_includes_capabilities(self) -> None:
        """SiteProfile 包含 capabilities 字段。"""
        profile = _make_profile()
        assert profile.capabilities is not None
        assert isinstance(profile.capabilities, SiteCapability)

    def test_loaded_profiles_have_capabilities(self) -> None:
        """从 TOML 加载的配置包含能力声明。"""
        profile = load_profile_by_name("deepseek")
        assert profile.capabilities.streaming is True
        assert profile.capabilities.mode_switching is True
        assert profile.capabilities.max_input_length == 32000

    def test_qwen_has_custom_capabilities(self) -> None:
        """Qwen 配置包含自定义能力标签。"""
        profile = load_profile_by_name("qwen")
        assert "image_generation" in profile.capabilities.custom
        assert "video_generation" in profile.capabilities.custom

    def test_kimi_long_context(self) -> None:
        """KIMI 声明长上下文能力。"""
        profile = load_profile_by_name("kimi")
        assert profile.capabilities.max_input_length == 200000
        assert "long_context" in profile.capabilities.custom


# ═══════════════════════════════════════════════════════════════════════
# 11. 配置校验
# ═══════════════════════════════════════════════════════════════════════


class TestProfileValidation:
    """validate_profile 配置校验测试。"""

    def test_valid_profile_no_errors(self) -> None:
        """有效配置返回空错误列表。"""
        profile = load_profile_by_name("deepseek")
        errors = validate_profile(profile)
        assert errors == []

    def test_all_builtin_profiles_valid(self) -> None:
        """所有内置配置通过校验。"""
        for site_name in ["deepseek", "chatgpt", "qwen", "doubao", "kimi"]:
            profile = load_profile_by_name(site_name)
            errors = validate_profile(profile)
            assert errors == [], f"{site_name} has validation errors: {errors}"

    def test_missing_name(self) -> None:
        """缺少 name 报错。"""
        profile = SiteProfile(
            name="",
            url="https://example.com",
            selectors=SiteSelectors(input_box="in", send_button="btn", response_container="div"),
        )
        errors = validate_profile(profile)
        assert any("name is required" in e for e in errors)

    def test_missing_url(self) -> None:
        """缺少 url 报错。"""
        profile = SiteProfile(
            name="test",
            url="",
            selectors=SiteSelectors(input_box="in", send_button="btn", response_container="div"),
        )
        errors = validate_profile(profile)
        assert any("url is required" in e for e in errors)

    def test_invalid_url_scheme(self) -> None:
        """URL 不以 http(s) 开头报错。"""
        profile = SiteProfile(
            name="test",
            url="ftp://example.com",
            selectors=SiteSelectors(input_box="in", send_button="btn", response_container="div"),
        )
        errors = validate_profile(profile)
        assert any("http(s)://" in e for e in errors)

    def test_missing_required_selectors(self) -> None:
        """缺少必填选择器报错。"""
        profile = SiteProfile(
            name="test",
            url="https://example.com",
            selectors=SiteSelectors(input_box="", send_button="", response_container=""),
        )
        errors = validate_profile(profile)
        assert any("input_box is required" in e for e in errors)
        assert any("send_button is required" in e for e in errors)
        assert any("response_container is required" in e for e in errors)

    def test_safety_min_gt_max(self) -> None:
        """min_delay > max_delay 报错。"""
        profile = SiteProfile(
            name="test",
            url="https://example.com",
            selectors=SiteSelectors(input_box="in", send_button="btn", response_container="div"),
            safety=SafetyConfig(min_delay=5.0, max_delay=2.0),
        )
        errors = validate_profile(profile)
        assert any("max_delay" in e and "min_delay" in e for e in errors)

    def test_invalid_completion_method(self) -> None:
        """无效的 completion method 报错。"""
        profile = SiteProfile(
            name="test",
            url="https://example.com",
            selectors=SiteSelectors(input_box="in", send_button="btn", response_container="div"),
            completion=CompletionConfig(method="invalid_method"),
        )
        errors = validate_profile(profile)
        assert any("method must be" in e for e in errors)

    def test_stop_button_disappear_requires_stop_button(self) -> None:
        """stop_button_disappear 方法要求 stop_button 选择器。"""
        profile = SiteProfile(
            name="test",
            url="https://example.com",
            selectors=SiteSelectors(
                input_box="in", send_button="btn", response_container="div", stop_button=""
            ),
            completion=CompletionConfig(method="stop_button_disappear"),
        )
        errors = validate_profile(profile)
        assert any("stop_button" in e for e in errors)

    def test_mode_switching_without_modes(self) -> None:
        """声明 mode_switching=true 但无模式报错。"""
        profile = SiteProfile(
            name="test",
            url="https://example.com",
            selectors=SiteSelectors(input_box="in", send_button="btn", response_container="div"),
            modes=(),
            capabilities=SiteCapability(mode_switching=True),
        )
        errors = validate_profile(profile)
        assert any("mode_switching" in e and "no modes" in e for e in errors)

    def test_duplicate_mode_names(self) -> None:
        """重复模式名报错。"""
        profile = SiteProfile(
            name="test",
            url="https://example.com",
            selectors=SiteSelectors(input_box="in", send_button="btn", response_container="div"),
            modes=(
                SiteMode(name="dup", label="A", selector="btn1"),
                SiteMode(name="dup", label="B", selector="btn2"),
            ),
            capabilities=SiteCapability(mode_switching=True),
        )
        errors = validate_profile(profile)
        assert any("duplicate mode names" in e for e in errors)

    def test_profile_validation_error_exception(self) -> None:
        """ProfileValidationError 异常包含站点名和错误列表。"""
        err = ProfileValidationError("mysite", ["error1", "error2"])
        assert err.site_name == "mysite"
        assert err.errors == ["error1", "error2"]
        assert "mysite" in str(err)
        assert "error1" in str(err)


# ═══════════════════════════════════════════════════════════════════════
# 12. 配置发现 + 多目录搜索
# ═══════════════════════════════════════════════════════════════════════


class TestProfileDiscovery:
    """discover_profiles + get_profile_search_dirs 多目录搜索测试。"""

    def test_discover_builtin_profiles(self) -> None:
        """discover_profiles 发现所有内置配置。"""
        profiles = discover_profiles()
        for site in ["deepseek", "chatgpt", "qwen", "doubao", "kimi"]:
            assert site in profiles
            assert profiles[site].exists()

    def test_get_search_dirs_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认搜索目录包含用户目录和内置目录。"""
        monkeypatch.delenv("MULTIMIND_SITES_DIR", raising=False)
        dirs = get_profile_search_dirs()
        # 内置目录一定在列表中
        assert any("profiles" in str(d) for d in dirs)
        # 用户目录一定在列表中
        assert any(".multimind" in str(d) for d in dirs)

    def test_get_search_dirs_with_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """环境变量设置的目录出现在搜索列表中。"""
        monkeypatch.setenv("MULTIMIND_SITES_DIR", str(tmp_path))
        dirs = get_profile_search_dirs()
        assert tmp_path in dirs

    def test_get_search_dirs_multi_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """环境变量支持冒号分隔多目录。"""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        monkeypatch.setenv("MULTIMIND_SITES_DIR", f"{dir1}:{dir2}")
        dirs = get_profile_search_dirs()
        assert dir1 in dirs
        assert dir2 in dirs

    def test_discover_user_profiles_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """用户目录配置覆盖内置配置。"""
        # 创建用户配置目录
        user_dir = tmp_path / "sites"
        user_dir.mkdir()
        # 写入一个自定义 deepseek.toml（覆盖内置）
        custom_toml = b'''
[site]
name = "deepseek"
url = "https://custom.deepseek.com"

[selectors]
input_box = "textarea.custom"
send_button = "button.custom"
response_container = "div.custom"
stop_button = "button.stop"

[modes]

[safety]
min_delay = 0.5
max_delay = 1.0
'''
        (user_dir / "deepseek.toml").write_bytes(custom_toml)
        # 设置环境变量
        monkeypatch.setenv("MULTIMIND_SITES_DIR", str(user_dir))
        # 发现配置
        profiles = discover_profiles()
        # 用户目录的配置应覆盖内置
        assert profiles["deepseek"] == user_dir / "deepseek.toml"

    def test_load_profile_from_user_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """从用户目录加载自定义站点配置。"""
        user_dir = tmp_path / "sites"
        user_dir.mkdir()
        custom_toml = b'''
[site]
name = "mysite"
url = "https://mysite.example.com"

[selectors]
input_box = "input"
send_button = "button"
response_container = "div"

[modes]

[safety]
min_delay = 1.0
max_delay = 2.0
'''
        (user_dir / "mysite.toml").write_bytes(custom_toml)
        monkeypatch.setenv("MULTIMIND_SITES_DIR", str(user_dir))

        profile = load_profile_by_name("mysite")
        assert profile.name == "mysite"
        assert profile.url == "https://mysite.example.com"

    def test_load_profile_not_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """配置不存在时抛出 FileNotFoundError。"""
        monkeypatch.setenv("MULTIMIND_SITES_DIR", str(tmp_path))
        with pytest.raises(FileNotFoundError, match="not found"):
            load_profile_by_name("totally_nonexistent_site")


# ═══════════════════════════════════════════════════════════════════════
# 13. Registry 插件扩展
# ═══════════════════════════════════════════════════════════════════════


class TestRegistryExtensibility:
    """Registry 插件系统测试 — GenericSiteAdapter 兜底、动态注册、unregister。"""

    def setup_method(self) -> None:
        reset_site_registry()

    def teardown_method(self) -> None:
        reset_site_registry()

    def test_generic_fallback_with_profile_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """仅有 TOML 配置的站点使用 GenericSiteAdapter 兜底。"""
        user_dir = tmp_path / "sites"
        user_dir.mkdir()
        custom_toml = b'''
[site]
name = "newai"
url = "https://newai.example.com"

[selectors]
input_box = "input"
send_button = "button"
response_container = "div"
stop_button = "button.stop"

[modes]

[safety]
min_delay = 1.0
max_delay = 2.0
'''
        (user_dir / "newai.toml").write_bytes(custom_toml)
        monkeypatch.setenv("MULTIMIND_SITES_DIR", str(user_dir))

        registry = get_site_registry()
        # newai 没有注册自定义适配器类
        assert not registry.has_adapter("newai")
        # 但有 TOML 配置，应使用 GenericSiteAdapter 兜底
        adapter = registry.create("newai")
        assert adapter.site_name == "newai"
        assert isinstance(adapter, GenericSiteAdapter)

    def test_unregister(self) -> None:
        """unregister 移除适配器注册。"""
        registry = get_site_registry()
        assert registry.has_adapter("deepseek")
        registry.unregister("deepseek")
        assert not registry.has_adapter("deepseek")

    def test_has_adapter_true_for_builtin(self) -> None:
        """内置站点 has_adapter 返回 True。"""
        registry = get_site_registry()
        for site in ["deepseek", "chatgpt", "qwen", "doubao", "kimi"]:
            assert registry.has_adapter(site), f"{site} should have adapter"

    def test_has_adapter_false_for_profile_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """仅有配置的站点 has_adapter 返回 False。"""
        user_dir = tmp_path / "sites"
        user_dir.mkdir()
        (user_dir / "newsite.toml").write_bytes(
            b'[site]\nname = "newsite"\nurl = "https://new.example"\n'
            b'[selectors]\ninput_box = "i"\nsend_button = "b"\nresponse_container = "d"\n'
        )
        monkeypatch.setenv("MULTIMIND_SITES_DIR", str(user_dir))

        registry = get_site_registry()
        assert not registry.has_adapter("newsite")
        assert "newsite" in registry.available_sites()

    def test_registered_adapters(self) -> None:
        """registered_adapters 返回已注册的适配器列表。"""
        registry = get_site_registry()
        adapters = registry.registered_adapters()
        assert "deepseek" in adapters
        assert "chatgpt" in adapters
        assert len(adapters) == 5

    def test_available_sites_includes_profiles(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """available_sites 包含仅有配置的站点。"""
        user_dir = tmp_path / "sites"
        user_dir.mkdir()
        (user_dir / "extraml.toml").write_bytes(
            b'[site]\nname = "extraml"\nurl = "https://extra.example"\n'
            b'[selectors]\ninput_box = "i"\nsend_button = "b"\nresponse_container = "d"\n'
        )
        monkeypatch.setenv("MULTIMIND_SITES_DIR", str(user_dir))

        registry = get_site_registry()
        sites = registry.available_sites()
        assert "deepseek" in sites  # 内置适配器
        assert "extraml" in sites  # 仅有配置

    def test_create_unknown_no_profile_raises(self) -> None:
        """未注册且无配置的站点抛出 KeyError。"""
        registry = get_site_registry()
        with pytest.raises(KeyError, match="not registered"):
            registry.create("totally_unknown_site")

    def test_dynamic_generic_has_site_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """动态创建的 GenericSiteAdapter 有正确的 site_name。"""
        user_dir = tmp_path / "sites"
        user_dir.mkdir()
        (user_dir / "aitest.toml").write_bytes(
            b'[site]\nname = "aitest"\nurl = "https://aitest.example"\n'
            b'[selectors]\ninput_box = "i"\nsend_button = "b"\nresponse_container = "d"\n'
            b'[safety]\nmin_delay = 0.0\nmax_delay = 0.0\n'
        )
        monkeypatch.setenv("MULTIMIND_SITES_DIR", str(user_dir))

        registry = get_site_registry()
        adapter = registry.create("aitest")
        assert adapter.site_name == "aitest"
        # 类名应包含站点名
        assert "aitest" in type(adapter).__name__

    def test_register_then_create_custom(self) -> None:
        """注册自定义适配器后可创建实例。"""
        registry = get_site_registry()
        registry.register("custom_site", GenericSiteAdapter)
        assert registry.has_adapter("custom_site")
        # 创建需要配置文件存在，这里只验证注册成功
        assert "custom_site" in registry.registered_adapters()

    def test_registry_is_singleton(self) -> None:
        """get_site_registry 返回单例。"""
        r1 = get_site_registry()
        r2 = get_site_registry()
        assert r1 is r2
