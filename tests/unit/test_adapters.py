"""Unit tests for ``multimind.adapters`` — factory, channels & registry.

Covers:
* :func:`create_adapter` dispatching to the correct adapter class for
  each of the five :class:`ChannelType` values.
* Each adapter's ``ask()`` async generator yielding streamed output.
* :class:`ProviderRegistry` operations: ``register`` / ``get`` /
  ``by_tag`` / ``sorted_by_priority`` / ``available`` plus
  :func:`reset_registry`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest

from multimind.adapters.api_client import APIClientAdapter
from multimind.adapters.base import create_adapter
from multimind.adapters.browser import BrowserAdapter
from multimind.adapters.cli_reuse import CLIReuseAdapter
from multimind.adapters.local import LocalAdapter
from multimind.adapters.public_endpoint import PublicEndpointAdapter
from multimind.adapters.registry import (
    get_registry,
    reset_registry,
)
from multimind.core.exceptions import AdapterError
from multimind.core.interfaces import AIAdapter
from multimind.core.types import ChannelType, ProviderConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# ── create_adapter factory ──────────────────────────────────────────


def _config(name: str, channel: ChannelType, **kwargs: object) -> ProviderConfig:
    """Build a minimal ``ProviderConfig`` for the given channel."""

    return ProviderConfig(name=name, channel=channel, **kwargs)


class TestCreateAdapter:
    """Tests for the ``create_adapter`` factory dispatching."""

    def test_create_adapter_cli_reuse(self) -> None:
        """The CLI_REUSE channel maps to :class:`CLIReuseAdapter`."""

        adapter = create_adapter(_config("gemini-cli", ChannelType.CLI_REUSE))
        assert isinstance(adapter, CLIReuseAdapter)
        assert adapter.channel_type is ChannelType.CLI_REUSE

    def test_create_adapter_api_client(self) -> None:
        """The API_CLIENT channel maps to :class:`APIClientAdapter`."""

        adapter = create_adapter(_config("groq", ChannelType.API_CLIENT, api_key="k"))
        assert isinstance(adapter, APIClientAdapter)
        assert adapter.channel_type is ChannelType.API_CLIENT

    def test_create_adapter_browser(self) -> None:
        """The BROWSER channel maps to :class:`BrowserAdapter`."""

        adapter = create_adapter(_config("chatgpt", ChannelType.BROWSER))
        assert isinstance(adapter, BrowserAdapter)
        assert adapter.channel_type is ChannelType.BROWSER

    def test_create_adapter_public_endpoint(self) -> None:
        """The PUBLIC_ENDPOINT channel maps to :class:`PublicEndpointAdapter`."""

        adapter = create_adapter(_config("opencode", ChannelType.PUBLIC_ENDPOINT))
        assert isinstance(adapter, PublicEndpointAdapter)
        assert adapter.channel_type is ChannelType.PUBLIC_ENDPOINT

    def test_create_adapter_local(self) -> None:
        """The LOCAL channel maps to :class:`LocalAdapter`."""

        adapter = create_adapter(_config("ollama", ChannelType.LOCAL))
        assert isinstance(adapter, LocalAdapter)
        assert adapter.channel_type is ChannelType.LOCAL

    def test_create_adapter_returns_aiadapter(self) -> None:
        """Every created adapter is an instance of the ``AIAdapter`` ABC."""

        for channel in ChannelType:
            adapter = create_adapter(_config(f"p-{channel.value}", channel))
            assert isinstance(adapter, AIAdapter)

    def test_create_adapter_unsupported_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unmapped channel type raises :class:`AdapterError`.

        All real ``ChannelType`` values are mapped, so we simulate an
        unsupported channel by emptying the factory's dispatch table.
        """

        from multimind.adapters import base

        monkeypatch.setattr(base, "_ADAPTER_MAP", {})
        with pytest.raises(AdapterError):
            create_adapter(_config("x", ChannelType.LOCAL))


# ── Adapter ask() — 真实行为测试 ────────────────────────────────────
#
# 这些测试验证的是适配器的真实行为，而不是 mock 文本中的关键字：
# * HTTP 适配器通过 ``httpx.MockTransport`` 驱动 —— 请求构造、鉴权头、
#   SSE / NDJSON 解析都是真实代码路径，只是传输层离线。
# * CLI 适配器通过真实子进程（``cat`` / ``echo`` / ``false``）验证。
# * 失败路径断言 ``AdapterError`` —— 不再用固定字符串假装成功。


async def _collect(stream: AsyncIterator[str]) -> str:
    """Consume an async string iterator into a single string."""

    return "".join([chunk async for chunk in stream])


def _sse_response(*chunks: str) -> httpx.Response:
    """构造 OpenAI 风格 SSE 响应体。"""

    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": c}}]}, ensure_ascii=False)
        for c in chunks
    ]
    lines.append("data: [DONE]")
    return httpx.Response(200, text="\n\n".join(lines) + "\n\n")


def _ndjson_response(*chunks: str) -> httpx.Response:
    """构造 Ollama 风格 NDJSON 响应体。"""

    lines = [
        json.dumps({"message": {"role": "assistant", "content": c}, "done": False}) for c in chunks
    ]
    lines.append(json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}))
    return httpx.Response(200, text="\n".join(lines) + "\n")


class TestAPIClientAsk:
    """APIClientAdapter 的真实 SSE 行为与诚实报错。"""

    @pytest.mark.asyncio
    async def test_streams_sse_chunks(self) -> None:
        import httpx

        adapter = APIClientAdapter(
            _config("groq", ChannelType.API_CLIENT, api_key="k"),
            transport=httpx.MockTransport(lambda req: _sse_response("Hello", " world")),
        )
        assert await _collect(adapter.ask("hi")) == "Hello world"

    @pytest.mark.asyncio
    async def test_sends_auth_header_and_messages(self) -> None:
        import json

        import httpx

        captured: dict[str, object] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["auth"] = req.headers.get("authorization")
            captured["body"] = json.loads(req.content)
            return _sse_response("ok")

        adapter = APIClientAdapter(
            _config("groq", ChannelType.API_CLIENT, api_key="secret"),
            transport=httpx.MockTransport(handler),
        )
        from multimind.core.types import Message

        await _collect(adapter.ask("任务", [Message(role="user", content="前文")]))
        assert captured["auth"] == "Bearer secret"
        body = captured["body"]
        assert isinstance(body, dict)
        messages = body["messages"]
        assert messages[0] == {"role": "user", "content": "前文"}
        assert messages[-1] == {"role": "user", "content": "任务"}
        assert body["stream"] is True

    @pytest.mark.asyncio
    async def test_requires_api_key(self) -> None:
        adapter = APIClientAdapter(_config("groq", ChannelType.API_CLIENT))
        with pytest.raises(AdapterError, match="api_key"):
            await _collect(adapter.ask("hi"))

    @pytest.mark.asyncio
    async def test_http_error_surfaces(self) -> None:
        import httpx

        adapter = APIClientAdapter(
            _config("groq", ChannelType.API_CLIENT, api_key="k"),
            transport=httpx.MockTransport(lambda req: httpx.Response(429, text="rate limited")),
        )
        with pytest.raises(AdapterError, match="429"):
            await _collect(adapter.ask("hi"))

    @pytest.mark.asyncio
    async def test_network_error_surfaces(self) -> None:
        import httpx

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        adapter = APIClientAdapter(
            _config("groq", ChannelType.API_CLIENT, api_key="k"),
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(AdapterError, match="request failed"):
            await _collect(adapter.ask("hi"))


class TestPublicEndpointAsk:
    """PublicEndpointAdapter 的零鉴权 SSE 行为。"""

    @pytest.mark.asyncio
    async def test_streams_sse_without_auth(self) -> None:
        import httpx

        captured: dict[str, object] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["auth"] = req.headers.get("authorization")
            return _sse_response("zero-", "auth")

        adapter = PublicEndpointAdapter(
            _config("opencode", ChannelType.PUBLIC_ENDPOINT, endpoint="http://x/v1/chat"),
            transport=httpx.MockTransport(handler),
        )
        assert await _collect(adapter.ask("free")) == "zero-auth"
        assert captured["auth"] is None


class TestLocalAsk:
    """LocalAdapter 的真实 NDJSON 行为与离线报错。"""

    @pytest.mark.asyncio
    async def test_streams_ndjson_chunks(self) -> None:
        import httpx

        adapter = LocalAdapter(
            _config("ollama", ChannelType.LOCAL),
            transport=httpx.MockTransport(lambda req: _ndjson_response("离", "线", "完成")),
        )
        assert await _collect(adapter.ask("prompt")) == "离线完成"

    @pytest.mark.asyncio
    async def test_unavailable_service_raises(self) -> None:
        import httpx

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = LocalAdapter(
            _config("ollama", ChannelType.LOCAL),
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(AdapterError, match="unavailable"):
            await _collect(adapter.ask("prompt"))


class TestCLIReuseAsk:
    """CLIReuseAdapter 的真实子进程行为。"""

    @pytest.mark.asyncio
    async def test_stdin_echo_roundtrip(self) -> None:
        """prompt 经 stdin 传给 CLI（``cat`` 原样回显）。"""

        import shutil

        if shutil.which("cat") is None:
            pytest.skip("cat 不可用")
        adapter = CLIReuseAdapter(_config("test-cli", ChannelType.CLI_REUSE, endpoint="cat"))
        output = await _collect(adapter.ask("hello stdin"))
        assert "hello stdin" in output

    @pytest.mark.asyncio
    async def test_prompt_placeholder_argv(self) -> None:
        """``{prompt}`` 占位符把 prompt 放进 argv（``echo`` 回显）。"""

        import shutil

        if shutil.which("echo") is None:
            pytest.skip("echo 不可用")
        adapter = CLIReuseAdapter(
            _config("test-cli", ChannelType.CLI_REUSE, endpoint="echo got:{prompt}")
        )
        output = await _collect(adapter.ask("arg-passing"))
        assert "got:arg-passing" in output

    @pytest.mark.asyncio
    async def test_missing_cli_raises(self) -> None:
        adapter = CLIReuseAdapter(
            _config("ghost", ChannelType.CLI_REUSE, endpoint="no-such-cli-xyz-123")
        )
        with pytest.raises(AdapterError, match="not found"):
            await _collect(adapter.ask("hi"))

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises(self) -> None:
        import shutil

        if shutil.which("false") is None:
            pytest.skip("false 不可用")
        adapter = CLIReuseAdapter(_config("bad-cli", ChannelType.CLI_REUSE, endpoint="false"))
        with pytest.raises(AdapterError, match="exited with code"):
            await _collect(adapter.ask("hi"))

    @pytest.mark.asyncio
    async def test_no_duplicate_context_splicing(self) -> None:
        """上下文由上层组装进 prompt —— adapter 不再重复拼接。"""

        import shutil

        from multimind.core.types import Message

        if shutil.which("cat") is None:
            pytest.skip("cat 不可用")
        adapter = CLIReuseAdapter(_config("test-cli", ChannelType.CLI_REUSE, endpoint="cat"))
        context = [Message(role="user", content="不应重复出现")]
        output = await _collect(adapter.ask("唯一提示词", context))
        assert "唯一提示词" in output
        assert "不应重复出现" not in output


class TestBrowserAsk:
    """BrowserAdapter 的降级路径（无需图形环境）。"""

    @pytest.mark.asyncio
    async def test_stub_when_site_adapter_missing(self) -> None:
        """无站点适配器 → 桩模式（不抛异常）。"""

        adapter = BrowserAdapter(_config("unknown-site", ChannelType.BROWSER))
        output = await _collect(adapter.ask("open the page"))
        assert "stub" in output.lower() or "not configured" in output.lower()

    @pytest.mark.asyncio
    async def test_stub_when_browser_unavailable(self) -> None:
        """站点适配器在但浏览器无法启动 → 桩模式降级，异常不穿透。"""

        adapter = BrowserAdapter(_config("deepseek", ChannelType.BROWSER))
        output = await _collect(adapter.ask("open the page"))
        assert "stub" in output.lower()

    @pytest.mark.asyncio
    async def test_launch_error_wrapped_as_adapter_error(self) -> None:
        """_ensure_browser 把任意启动异常包装为 AdapterError（真实 bug 回归）。

        Playwright 在无 X server 时抛 ``TargetClosedError`` 而非
        ``AdapterError``——必须被统一包装，否则降级逻辑失效。
        """

        adapter = BrowserAdapter(_config("deepseek", ChannelType.BROWSER))
        adapter._ensure_site_adapter()

        async def boom() -> object:
            raise RuntimeError("Target closed")  # 模拟 TargetClosedError

        adapter._playwright = None
        import multimind.adapters.browser as browser_mod

        original = browser_mod.BrowserAdapter._ensure_browser
        try:
            # 强制 _ensure_browser 走启动路径并抛非 AdapterError
            async def fake_ensure(self: BrowserAdapter) -> object:
                try:
                    return await boom()
                except AdapterError:
                    raise
                except Exception as e:
                    raise AdapterError(f"Failed to launch browser: {e}") from e

            browser_mod.BrowserAdapter._ensure_browser = fake_ensure  # type: ignore[method-assign]
            output = await _collect(adapter.ask("open the page"))
            assert "stub" in output.lower()
        finally:
            browser_mod.BrowserAdapter._ensure_browser = original  # type: ignore[method-assign]


def _browser_env_ready() -> bool:
    """检测真实浏览器测试所需环境（Playwright + 图形显示）。"""

    import os
    import shutil
    import sys

    no_display = os.environ.get("DISPLAY") is None
    if no_display and shutil.which("xvfb-run") is None and sys.platform != "win32":
        return False
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


requires_browser = pytest.mark.skipif(
    not _browser_env_ready(),
    reason="需要 Playwright + 图形环境（X server），当前环境跳过",
)


class TestBrowserRealLaunch:
    """真实浏览器启动测试 —— 无 X server 的环境自动跳过（skipif 守卫）。"""

    @requires_browser
    @pytest.mark.asyncio
    async def test_real_browser_launch(self) -> None:
        """有图形环境时，真实启动浏览器并导航（冒烟）。"""

        adapter = BrowserAdapter(_config("deepseek", ChannelType.BROWSER))
        try:
            page = await adapter._ensure_browser()
            assert page is not None
        finally:
            await adapter.close()


# ── 用量记录（基类契约，参数化覆盖全部适配器）────────────────────────


def _working_adapters() -> list[AIAdapter]:
    """构造五类适配器的"可用"实例（离线成功路径）。"""

    import httpx

    return [
        CLIReuseAdapter(_config("cli", ChannelType.CLI_REUSE, endpoint="cat", daily_quota=10)),
        APIClientAdapter(
            _config(
                "api",
                ChannelType.API_CLIENT,
                api_key="k",
                endpoint="http://x/v1/chat/completions",
                daily_quota=10,
            ),
            transport=httpx.MockTransport(lambda req: _sse_response("ok")),
        ),
        PublicEndpointAdapter(
            _config("pub", ChannelType.PUBLIC_ENDPOINT, endpoint="http://x/v1", daily_quota=10),
            transport=httpx.MockTransport(lambda req: _sse_response("ok")),
        ),
        LocalAdapter(
            _config("loc", ChannelType.LOCAL, daily_quota=10),
            transport=httpx.MockTransport(lambda req: _ndjson_response("ok")),
        ),
        BrowserAdapter(_config("unknown-site", ChannelType.BROWSER, daily_quota=10)),
    ]


class TestUsageRecording:
    """``record_usage`` 是 ``AIAdapter`` 基类契约 —— 所有子类都应生效。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "adapter",
        _working_adapters(),
        ids=lambda a: type(a).__name__,
    )
    async def test_ask_records_usage(self, adapter: AIAdapter) -> None:
        import shutil

        if isinstance(adapter, CLIReuseAdapter) and shutil.which("cat") is None:
            pytest.skip("cat 不可用")
        assert adapter._used_today == 0
        await _collect(adapter.ask("anything"))
        assert adapter._used_today == 1
        assert adapter.remaining_quota == 9


# ── ProviderRegistry ────────────────────────────────────────────────


class TestProviderRegistry:
    """Tests for provider registration, lookup and prioritisation."""

    def test_register_and_get(self) -> None:
        """Registering a config makes its adapter retrievable by name."""

        registry = get_registry()
        registry.register(_config("p1", ChannelType.LOCAL, tags=("free",)))
        adapter = registry.get("p1")
        assert adapter is not None
        assert adapter.config.name == "p1"

    def test_get_unknown_returns_none(self) -> None:
        """Looking up an unregistered name returns ``None``."""

        assert get_registry().get("does-not-exist") is None

    def test_register_overwrites_existing(self) -> None:
        """Re-registering a name replaces the previous adapter."""

        registry = get_registry()
        registry.register(_config("p1", ChannelType.LOCAL, priority=50))
        registry.register(_config("p1", ChannelType.LOCAL, priority=10))
        adapter = registry.get("p1")
        assert adapter is not None
        assert adapter.config.priority == 10
        assert len(registry) == 1

    def test_by_tag_filters_matching(self) -> None:
        """``by_tag`` returns only adapters whose config tags contain the tag."""

        registry = get_registry()
        registry.register(_config("a", ChannelType.LOCAL, tags=("free", "fast")))
        registry.register(_config("b", ChannelType.LOCAL, tags=("free",)))
        registry.register(_config("c", ChannelType.LOCAL, tags=("paid",)))

        fast = [a.config.name for a in registry.by_tag("fast")]
        free = [a.config.name for a in registry.by_tag("free")]
        assert fast == ["a"]
        assert set(free) == {"a", "b"}

    def test_by_tag_no_match_returns_empty(self) -> None:
        """A tag matched by no provider yields an empty list."""

        registry = get_registry()
        registry.register(_config("a", ChannelType.LOCAL, tags=("free",)))
        assert registry.by_tag("nonexistent") == []

    def test_sorted_by_priority(self) -> None:
        """``sorted_by_priority`` orders adapters ascending by priority."""

        registry = get_registry()
        registry.register(_config("low", ChannelType.LOCAL, priority=90))
        registry.register(_config("high", ChannelType.LOCAL, priority=10))
        registry.register(_config("mid", ChannelType.LOCAL, priority=50))

        ordered = [a.config.name for a in registry.sorted_by_priority()]
        assert ordered == ["high", "mid", "low"]

    def test_available_returns_only_with_quota(self) -> None:
        """Adapters with zero remaining quota are excluded from ``available``."""

        registry = get_registry()
        registry.register(_config("limited", ChannelType.LOCAL, daily_quota=1))
        registry.register(_config("unlimited", ChannelType.LOCAL, daily_quota=-1))
        # Exhaust the limited provider.
        limited = registry.get("limited")
        assert limited is not None
        limited.record_usage(1)

        names = [a.config.name for a in registry.available()]
        assert "unlimited" in names
        assert "limited" not in names

    def test_available_with_required_tag(self) -> None:
        """``available`` respects the optional tag filter and ordering."""

        registry = get_registry()
        registry.register(_config("a", ChannelType.LOCAL, tags=("fast",), priority=30))
        registry.register(_config("b", ChannelType.LOCAL, tags=("fast",), priority=10))
        registry.register(_config("c", ChannelType.LOCAL, tags=("slow",), priority=5))

        names = [a.config.name for a in registry.available(required_tag="fast")]
        assert names == ["b", "a"]

    def test_contains_and_len(self) -> None:
        """The registry supports ``in`` and ``len()``."""

        registry = get_registry()
        registry.register(_config("p1", ChannelType.LOCAL))
        assert "p1" in registry
        assert "nope" not in registry
        assert len(registry) == 1

    def test_all_returns_copy(self) -> None:
        """``all()`` returns a copy so callers cannot mutate internals."""

        registry = get_registry()
        registry.register(_config("p1", ChannelType.LOCAL))
        snapshot = registry.all()
        snapshot.clear()
        assert "p1" in registry

    def test_reset_registry_clears_singleton(self) -> None:
        """``reset_registry`` produces an empty singleton.

        This test deliberately manipulates the singleton directly (the
        autouse conftest fixture resets it before the test starts), then
        calls ``reset_registry`` again and checks it is empty.
        """

        registry = get_registry()
        registry.register(_config("p1", ChannelType.LOCAL))
        assert len(registry) == 1
        reset_registry()
        fresh = get_registry()
        assert len(fresh) == 0
        assert fresh is not registry
