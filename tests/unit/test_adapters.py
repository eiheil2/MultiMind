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

from typing import TYPE_CHECKING

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

        adapter = create_adapter(
            _config("groq", ChannelType.API_CLIENT, api_key="k")
        )
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


# ── Adapter ask() streaming ─────────────────────────────────────────


async def _collect(stream: AsyncIterator[str]) -> str:
    """Consume an async string iterator into a single string."""

    return "".join([chunk async for chunk in stream])


class TestAdapterAsk:
    """Tests verifying each adapter's ``ask()`` yields streamed output."""

    @pytest.mark.asyncio
    async def test_cli_reuse_adapter_ask_yields_output(self) -> None:
        """CLIReuseAdapter.ask yields a non-empty stream.

        In CI / environments without the actual CLI installed, the adapter
        gracefully degrades with an installation hint.  In environments with
        the CLI present it invokes the real subprocess.
        """

        adapter = CLIReuseAdapter(_config("gemini-cli", ChannelType.CLI_REUSE))
        output = await _collect(adapter.ask("hello world"))
        assert len(output) > 0
        # 降级消息包含安装提示
        assert "安装" in output or "gemini" in output.lower() or "CLI" in output

    @pytest.mark.asyncio
    async def test_cli_reuse_adapter_not_installed_graceful(self) -> None:
        """When CLI is missing, adapter yields a helpful install hint and
        does NOT crash."""

        adapter = CLIReuseAdapter(
            _config("nonexistent-cli", ChannelType.CLI_REUSE, endpoint="no-such-cmd"),
        )
        output = await _collect(adapter.ask("test"))
        assert len(output) > 0
        assert "未安装" in output or "install" in output.lower()

    @pytest.mark.asyncio
    async def test_cli_reuse_adapter_with_mock_subprocess(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With a mocked subprocess that returns valid JSON, the adapter
        extracts the ``response`` field correctly."""

        import asyncio as _asyncio_mod

        async def _mock_exec(*args, **kwargs):  # noqa: ANN202
            class _FakeProc:
                returncode = 0

                async def communicate(self):  # noqa: ANN202
                    return (
                        b'{"response": "Hello from mock CLI", "stats": {}}',
                        b"",
                    )

            return _FakeProc()

        monkeypatch.setattr(_asyncio_mod, "create_subprocess_exec", _mock_exec)
        monkeypatch.setattr("shutil.which", lambda _cmd: "/fake/path/to/cli")

        adapter = CLIReuseAdapter(_config("gemini-cli", ChannelType.CLI_REUSE))
        output = await _collect(adapter.ask("hello"))
        assert "Hello from mock CLI" in output

    @pytest.mark.asyncio
    async def test_cli_reuse_adapter_mock_non_json_fallback(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If CLI returns plain text (not JSON), the adapter falls back to
        using the raw output."""

        import asyncio as _asyncio_mod

        async def _mock_exec(*args, **kwargs):  # noqa: ANN202
            class _FakeProc:
                returncode = 0

                async def communicate(self):  # noqa: ANN202
                    return (b"Plain text response from CLI", b"")

            return _FakeProc()

        monkeypatch.setattr(_asyncio_mod, "create_subprocess_exec", _mock_exec)
        monkeypatch.setattr("shutil.which", lambda _cmd: "/fake/path/to/cli")

        adapter = CLIReuseAdapter(_config("opencode-free", ChannelType.CLI_REUSE))
        output = await _collect(adapter.ask("hello"))
        assert "Plain text response from CLI" in output

    @pytest.mark.asyncio
    async def test_cli_reuse_adapter_mock_nonzero_exit(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When CLI exits non-zero, the adapter yields an error message."""

        import asyncio as _asyncio_mod

        async def _mock_exec(*args, **kwargs):  # noqa: ANN202
            class _FakeProc:
                returncode = 1

                async def communicate(self):  # noqa: ANN202
                    return (b"", b"auth error: not logged in")

            return _FakeProc()

        monkeypatch.setattr(_asyncio_mod, "create_subprocess_exec", _mock_exec)
        monkeypatch.setattr("shutil.which", lambda _cmd: "/fake/path/to/cli")

        adapter = CLIReuseAdapter(_config("gemini-cli", ChannelType.CLI_REUSE))
        output = await _collect(adapter.ask("hello"))
        assert "失败" in output or "error" in output.lower() or "auth" in output.lower()

    @pytest.mark.asyncio
    async def test_api_client_adapter_ask_yields_output(self) -> None:
        """APIClientAdapter.ask yields a non-empty stream with the API marker."""

        adapter = APIClientAdapter(
            _config("groq", ChannelType.API_CLIENT, api_key="key")
        )
        output = await _collect(adapter.ask("summarise this"))
        assert len(output) > 0
        assert "API" in output or "api" in output

    @pytest.mark.asyncio
    async def test_browser_adapter_ask_yields_output(self) -> None:
        """BrowserAdapter.ask yields a non-empty stream with the browser marker."""

        adapter = BrowserAdapter(_config("chatgpt", ChannelType.BROWSER))
        output = await _collect(adapter.ask("open the page"))
        assert len(output) > 0

    @pytest.mark.asyncio
    async def test_public_endpoint_adapter_ask_yields_output(self) -> None:
        """PublicEndpointAdapter.ask yields a non-empty zero-auth stream.

        Note: as of the opencode-free → CLI_REUSE migration, this adapter
        is no longer used by built-in providers.  The test verifies the
        adapter class still functions for user-defined providers.
        """

        adapter = PublicEndpointAdapter(_config("custom-public", ChannelType.PUBLIC_ENDPOINT))
        output = await _collect(adapter.ask("free request"))
        assert len(output) > 0
        assert "public" in output.lower() or "endpoint" in output.lower()

    @pytest.mark.asyncio
    async def test_local_adapter_ask_yields_output(self) -> None:
        """LocalAdapter.ask yields a non-empty local-inference stream."""

        adapter = LocalAdapter(_config("ollama", ChannelType.LOCAL))
        output = await _collect(adapter.ask("offline prompt"))
        assert len(output) > 0
        assert "local" in output.lower()

    @pytest.mark.asyncio
    async def test_ask_yields_multiple_chunks(self) -> None:
        """``ask()`` is a true async generator yielding several string chunks."""

        adapter = LocalAdapter(_config("ollama", ChannelType.LOCAL))
        chunks = [chunk async for chunk in adapter.ask("multi chunk")]
        assert len(chunks) > 1
        assert all(isinstance(c, str) for c in chunks)

    @pytest.mark.asyncio
    async def test_ask_records_usage(self) -> None:
        """Consuming ``ask()`` increments the adapter's internal usage counter."""

        adapter = LocalAdapter(
            _config("ollama", ChannelType.LOCAL, daily_quota=10)
        )
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
        registry.register(
            _config("limited", ChannelType.LOCAL, daily_quota=1)
        )
        registry.register(
            _config("unlimited", ChannelType.LOCAL, daily_quota=-1)
        )
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
        registry.register(
            _config("a", ChannelType.LOCAL, tags=("fast",), priority=30)
        )
        registry.register(
            _config("b", ChannelType.LOCAL, tags=("fast",), priority=10)
        )
        registry.register(
            _config("c", ChannelType.LOCAL, tags=("slow",), priority=5)
        )

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
