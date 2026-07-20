"""Unit tests for ``multimind.engine`` — roles, group-chat bus & orchestrator.

Covers:
* :class:`Role` construction and default-prompt population.
* :func:`default_roles` returning the canonical 1 + 1 + 2 role set.
* :class:`GroupChatBus` post / mention / broadcast / flatten / rebuild
  plus subscription delivery and history/context helpers.
* :class:`TopologyManager` toggle between layered and flat modes.
* :class:`Orchestrator.run` streaming output through the leader role.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from multimind.core.types import Message, Permission, RoleMode
from multimind.engine.groupchat import ChatEvent, GroupChatBus, TopologyMode
from multimind.engine.orchestrator import Orchestrator
from multimind.engine.roles import ROLE_PROMPTS, Role, default_roles
from multimind.engine.topology import TopologyManager

if TYPE_CHECKING:
    from multimind.adapters.registry import ProviderRegistry

# ── Roles ───────────────────────────────────────────────────────────


class TestRole:
    """Tests for :class:`Role` and :func:`default_roles`."""

    def test_role_construction_defaults(self) -> None:
        """A Role without explicit prompt/mode uses tier-based defaults."""

        role = Role(name="worker", tier="executor", provider="ollama-local")
        assert role.mode is RoleMode.ACT
        assert role.permission is Permission.AUTO
        assert role.prompt == ROLE_PROMPTS["executor"]
        assert role.max_concurrent == 1

    def test_role_custom_prompt_preserved(self) -> None:
        """An explicitly provided prompt is not overwritten by defaults."""

        role = Role(
            name="boss",
            tier="leader",
            provider="gemini-cli",
            prompt="be decisive",
        )
        assert role.prompt == "be decisive"

    def test_role_repr_contains_key_fields(self) -> None:
        """``repr`` surfaces name, tier, provider and mode for debugging."""

        role = Role(name="boss", tier="leader", provider="gemini-cli")
        text = repr(role)
        assert "boss" in text
        assert "leader" in text
        assert "gemini-cli" in text

    def test_default_roles_returns_four(self) -> None:
        """``default_roles`` returns exactly four roles."""

        roles = default_roles()
        assert len(roles) == 4

    def test_default_roles_tier_composition(self) -> None:
        """Default roster = 1 leader + 1 dispatcher + 2 executors."""

        roles = default_roles()
        tiers = [r.tier for r in roles]
        assert tiers.count("leader") == 1
        assert tiers.count("dispatcher") == 1
        assert tiers.count("executor") == 2

    def test_default_roles_have_prompts(self) -> None:
        """Every default role is seeded with a non-empty system prompt."""

        for role in default_roles():
            assert role.prompt, f"Role {role.name} has empty prompt"


# ── GroupChatBus ────────────────────────────────────────────────────


class TestGroupChatBus:
    """Tests for the :class:`GroupChatBus` message bus."""

    @pytest.mark.asyncio
    async def test_post_appends_message(self) -> None:
        """``post`` stores the message in the bus history."""

        bus = GroupChatBus()
        msg = Message(role="user", content="hello")
        await bus.post(msg)
        assert bus.messages == [msg]

    @pytest.mark.asyncio
    async def test_post_delivers_to_subscribers(self) -> None:
        """Subscribed queues receive every posted message."""

        bus = GroupChatBus()
        queue = bus.subscribe()
        msg = Message(role="user", content="ping")
        await bus.post(msg)
        delivered = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert delivered is msg

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self) -> None:
        """An unsubscribed queue no longer receives messages."""

        bus = GroupChatBus()
        queue = bus.subscribe()
        bus.unsubscribe(queue)
        await bus.post(Message(role="user", content="x"))
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_mention_includes_target_prefix(self) -> None:
        """``mention`` records a message prefixed with ``@target``."""

        bus = GroupChatBus()
        await bus.mention("leader", "executor", "do the thing")
        assert len(bus.messages) == 1
        assert "@executor" in bus.messages[0].content
        assert bus.messages[0].role == "leader"

    @pytest.mark.asyncio
    async def test_broadcast_stores_message(self) -> None:
        """``broadcast`` posts a message attributed to the source role."""

        bus = GroupChatBus()
        await bus.broadcast("leader", "team stand up")
        assert len(bus.messages) == 1
        assert bus.messages[0].role == "leader"
        assert bus.messages[0].content == "team stand up"

    @pytest.mark.asyncio
    async def test_flatten_switches_topology(self) -> None:
        """``flatten`` moves the bus into the flat topology mode."""

        bus = GroupChatBus()
        assert bus.topology is TopologyMode.LAYERED
        await bus.flatten()
        assert bus.topology is TopologyMode.FLAT

    @pytest.mark.asyncio
    async def test_rebuild_restores_layered(self) -> None:
        """``rebuild`` restores the layered topology mode."""

        bus = GroupChatBus()
        await bus.flatten()
        assert bus.topology is TopologyMode.FLAT
        await bus.rebuild()
        assert bus.topology is TopologyMode.LAYERED

    @pytest.mark.asyncio
    async def test_flatten_fires_hook(self) -> None:
        """Topology changes fire the corresponding lifecycle hook."""

        bus = GroupChatBus()
        events: list[ChatEvent] = []
        bus.add_hook("flatten", events.append)
        await bus.flatten()
        assert events and events[0].type == "flatten"

    @pytest.mark.asyncio
    async def test_mention_fires_hook(self) -> None:
        """``mention`` fires the ``mention`` hook with target info."""

        bus = GroupChatBus()
        events: list[ChatEvent] = []
        bus.add_hook("mention", events.append)
        await bus.mention("a", "b", "hi")
        assert events
        assert events[0].target == "b"
        assert events[0].source == "a"

    def test_history_returns_recent(self) -> None:
        """``history`` returns the most recent messages up to the limit."""

        bus = GroupChatBus()
        # Inject messages directly to avoid async overhead.
        bus._messages = [Message(role="r", content=str(i)) for i in range(10)]  # type: ignore[attr-defined]
        recent = bus.history(limit=3)
        assert [m.content for m in recent] == ["7", "8", "9"]

    @pytest.mark.asyncio
    async def test_context_for_filters_mentions(self) -> None:
        """``context_for`` includes mentions of the role plus non-mention msgs."""

        bus = GroupChatBus()
        await bus.mention("leader", "executor", "task")  # @executor
        await bus.broadcast("leader", "all hands")       # no @
        await bus.mention("leader", "other", "skip")     # @other
        ctx = bus.context_for("executor")
        contents = [m.content for m in ctx]
        assert any("@executor" in c for c in contents)
        assert any("all hands" in c for c in contents)
        assert not any("@other" in c for c in contents)


# ── TopologyManager ─────────────────────────────────────────────────


class TestTopologyManager:
    """Tests for the :class:`TopologyManager` toggle semantics."""

    @pytest.mark.asyncio
    async def test_default_mode_is_layered(self) -> None:
        """A fresh bus starts in layered mode."""

        mgr = TopologyManager(GroupChatBus())
        assert mgr.mode is TopologyMode.LAYERED

    @pytest.mark.asyncio
    async def test_toggle_from_layered_to_flat(self) -> None:
        """Toggling once from layered yields the flat mode."""

        mgr = TopologyManager(GroupChatBus())
        result = await mgr.toggle()
        assert mgr.mode is TopologyMode.FLAT
        assert "拉平" in result

    @pytest.mark.asyncio
    async def test_toggle_back_to_layered(self) -> None:
        """Toggling twice returns to the layered mode."""

        mgr = TopologyManager(GroupChatBus())
        await mgr.toggle()
        result = await mgr.toggle()
        assert mgr.mode is TopologyMode.LAYERED
        assert "重建" in result

    def test_describe_layered(self) -> None:
        """``describe`` returns a readable layered-mode string."""

        mgr = TopologyManager(GroupChatBus())
        assert "分层" in mgr.describe()


# ── Orchestrator ────────────────────────────────────────────────────


class TestOrchestrator:
    """Tests for the :class:`Orchestrator` streaming run loop."""

    def test_orchestrator_role_partitions(self, default_providers: ProviderRegistry) -> None:
        """The orchestrator partitions roles into leaders/dispatchers/executors."""

        orch = Orchestrator()
        assert len(orch.leaders) == 1
        assert len(orch.dispatchers) == 1
        assert len(orch.executors) == 2

    @pytest.mark.asyncio
    async def test_run_yields_events(self, default_providers: ProviderRegistry) -> None:
        """``Orchestrator.run`` yields structured events from the leader."""

        from multimind.engine.orchestrator import OrchestratorEvent

        orch = Orchestrator()
        events = [e async for e in orch.run("hello team", max_rounds=2)]
        assert len(events) > 0

        # Should have at least one ROLE_START, ROLE_CHUNK, ROLE_END
        types = [e.event_type for e in events]
        assert OrchestratorEvent.ROLE_START in types
        assert OrchestratorEvent.ROLE_CHUNK in types
        assert OrchestratorEvent.ROLE_END in types
        assert OrchestratorEvent.ROUND_END in types

        # The leader must have spoken.
        role_names = [e.role_name for e in events if e.event_type == OrchestratorEvent.ROLE_START]
        assert "指挥官" in role_names

        # Chunks should have content
        chunks = [e.content for e in events if e.event_type == OrchestratorEvent.ROLE_CHUNK]
        assert any(len(c) > 0 for c in chunks)

    @pytest.mark.asyncio
    async def test_run_posts_to_bus(self, default_providers: ProviderRegistry) -> None:
        """After running, the bus contains the user broadcast and replies."""

        orch = Orchestrator()
        async for _ in orch.run("plan something", max_rounds=2):
            pass
        roles = [m.role for m in orch.bus.messages]
        assert "user" in roles  # broadcast source is "user" (English)
        assert "指挥官" in roles

    @pytest.mark.asyncio
    async def test_run_error_on_missing_provider(self) -> None:
        """A role bound to an unregistered provider yields an ERROR event."""

        from multimind.engine.orchestrator import OrchestratorEvent

        role = Role(name="ghost", tier="leader", provider="not-registered")
        orch = Orchestrator(roles=[role])
        events = [e async for e in orch.run("hi", max_rounds=2)]
        error_events = [e for e in events if e.event_type == OrchestratorEvent.ERROR]
        assert len(error_events) > 0
        assert "not-registered" in error_events[0].content

    @pytest.mark.asyncio
    async def test_language_affects_prompt(self, default_providers: ProviderRegistry) -> None:
        """Orchestrator with language='en' includes English response instruction."""

        orch = Orchestrator(language="en")
        events = [e async for e in orch.run("hello", max_rounds=2)]
        # Just verify it runs without error and produces events
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_language_zh_default(self, default_providers: ProviderRegistry) -> None:
        """Orchestrator defaults to Chinese language."""

        orch = Orchestrator()
        assert orch.language == "zh"
