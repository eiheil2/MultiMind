"""Unit tests for ``multimind.memory`` — three-tier memory manager.

Covers:
* Short-term message storage and ``MicroCompact`` compaction.
* ``assemble_context`` merging short / mid / long tiers and trimming by
  token estimate.
* ``summarize`` with and without ``force=True``.
* Mid-term and long-term entry persistence.
* ``save_checkpoint`` / ``list_checkpoints``.
* ``autodream`` idle consolidation (async, ``idle_seconds=0``).
"""

from __future__ import annotations

import pytest

from multimind.core.types import Message
from multimind.memory.manager import MemoryEntry, MemoryManager, MemoryTier

# ── Short-term memory ───────────────────────────────────────────────


class TestShortTermMemory:
    """Tests for short-term message storage and compaction."""

    def test_add_short_term_stores_message(self, temp_memory: MemoryManager) -> None:
        """Added messages are reflected in ``assemble_context``."""

        manager = temp_memory
        manager.add_short_term(Message(role="user", content="hello"))
        ctx = manager.assemble_context("any")
        assert any(m.content == "hello" for m in ctx)

    def test_add_short_term_preserves_order(self, temp_memory: MemoryManager) -> None:
        """Messages are stored in insertion order."""

        manager = temp_memory
        for i in range(5):
            manager.add_short_term(Message(role="r", content=f"msg-{i}"))
        ctx = manager.assemble_context("any")
        contents = [m.content for m in ctx if m.content.startswith("msg-")]
        assert contents == [f"msg-{i}" for i in range(5)]

    def test_compaction_triggers_on_overflow(self, temp_memory: MemoryManager) -> None:
        """Adding beyond ``SHORT_TERM_WINDOW`` triggers MicroCompact.

        After compaction the buffer is replaced by a summary plus the
        most recent messages, so the size stays bounded.
        """

        manager = temp_memory
        window = MemoryManager.SHORT_TERM_WINDOW
        for i in range(window + 5):
            manager.add_short_term(Message(role="r", content=f"m{i}"))
        # After compaction the buffer must be smaller than the raw input.
        assert len(manager._short_term) < window + 5  # type: ignore[attr-defined]
        # The compaction summary message is present.
        assert any("压缩" in m.content for m in manager._short_term)  # type: ignore[attr-defined]


# ── Context assembly ────────────────────────────────────────────────


class TestAssembleContext:
    """Tests for context assembly and token-aware trimming."""

    def test_assemble_context_includes_mid_and_long(
        self, temp_memory: MemoryManager
    ) -> None:
        """``assemble_context`` merges all three tiers."""

        manager = temp_memory
        manager.add_short_term(Message(role="user", content="short"))
        manager.add_mid_term(MemoryEntry(
            tier=MemoryTier.MID, content="mid note", role="r", tags=["t"]
        ))
        manager.add_long_term(MemoryEntry(
            tier=MemoryTier.LONG, content="long fact", role="r", tags=["t"]
        ))
        ctx = manager.assemble_context("any", max_tokens=100_000)
        contents = " ".join(m.content for m in ctx)
        assert "short" in contents
        assert "mid note" in contents
        assert "long fact" in contents

    def test_assemble_context_trims_to_max_tokens(
        self, temp_memory: MemoryManager
    ) -> None:
        """A small ``max_tokens`` budget trims older messages."""

        manager = temp_memory
        # Each message ~100 chars => ~25 tokens by the /4 estimate.
        for _i in range(20):
            manager.add_short_term(Message(role="r", content="x" * 100))
        ctx = manager.assemble_context("any", max_tokens=50)
        # Trimming keeps at most a handful of messages.
        assert len(ctx) <= 6

    def test_assemble_context_never_empty_floor(
        self, temp_memory: MemoryManager
    ) -> None:
        """Trimming stops once only five messages remain (safety floor)."""

        manager = temp_memory
        for _ in range(20):
            manager.add_short_term(Message(role="r", content="x" * 10_000))
        ctx = manager.assemble_context("any", max_tokens=1)
        assert len(ctx) == 5


# ── Summarize ───────────────────────────────────────────────────────


class TestSummarize:
    """Tests for the ``summarize`` entry point."""

    def test_summarize_force_true_with_few_messages(
        self, temp_memory: MemoryManager
    ) -> None:
        """``force=True`` produces a summary even with < 10 messages."""

        manager = temp_memory
        manager.add_short_term(Message(role="user", content="only one"))
        summary = manager.summarize(force=True)
        assert "总结" in summary
        assert "only one" in summary

    def test_summarize_without_force_skips_when_under_threshold(
        self, temp_memory: MemoryManager
    ) -> None:
        """Without ``force``, < 10 messages returns a skip notice."""

        manager = temp_memory
        manager.add_short_term(Message(role="user", content="one"))
        result = manager.summarize(force=False)
        assert "跳过" in result

    def test_summarize_persists_mid_term_entry(
        self, temp_memory: MemoryManager
    ) -> None:
        """A forced summary is stored as a mid-term memory entry."""

        manager = temp_memory
        manager.add_short_term(Message(role="user", content="note"))
        manager.summarize(force=True)
        # The summary should surface as a mid-term entry in context.
        ctx = manager.assemble_context("any", max_tokens=100_000)
        assert any("[记忆·mid]" in m.role for m in ctx)


# ── Mid-term & long-term persistence ────────────────────────────────


class TestMidAndLongTerm:
    """Tests for mid-term and long-term entry storage."""

    def test_add_mid_term_persists(self, temp_memory: MemoryManager) -> None:
        """Mid-term entries are stored and retrievable via context."""

        manager = temp_memory
        manager.add_mid_term(MemoryEntry(
            tier=MemoryTier.MID, content="stage summary", role="dispatcher"
        ))
        ctx = manager.assemble_context("any", max_tokens=100_000)
        assert any(m.content == "stage summary" for m in ctx)

    def test_add_long_term_persists(self, temp_memory: MemoryManager) -> None:
        """Long-term entries are stored and retrievable via context."""

        manager = temp_memory
        manager.add_long_term(MemoryEntry(
            tier=MemoryTier.LONG, content="project archive", role="leader"
        ))
        ctx = manager.assemble_context("any", max_tokens=100_000)
        assert any(m.content == "project archive" for m in ctx)

    def test_add_mid_term_writes_to_database(self, temp_memory: MemoryManager) -> None:
        """Mid-term entries are persisted to the SQLite ``memories`` table."""

        manager = temp_memory
        manager.add_mid_term(MemoryEntry(
            tier=MemoryTier.MID, content="db-check", role="r", tags=["x"]
        ))
        rows = manager._conn.execute(  # type: ignore[attr-defined]
            "SELECT content FROM memories WHERE tier=?",
            (MemoryTier.MID.value,),
        ).fetchall()
        assert any("db-check" in r[0] for r in rows)


# ── Checkpoints ─────────────────────────────────────────────────────


class TestCheckpoints:
    """Tests for checkpoint save/list used by the AutoGit linkage."""

    def test_save_checkpoint_returns_id(self, temp_memory: MemoryManager) -> None:
        """``save_checkpoint`` returns a positive checkpoint id."""

        manager = temp_memory
        cp_id = manager.save_checkpoint(commit_hash="abc123", role="executor")
        assert isinstance(cp_id, int)
        assert cp_id > 0

    def test_list_checkpoints_returns_saved_entries(
        self, temp_memory: MemoryManager
    ) -> None:
        """Saved checkpoints appear in ``list_checkpoints``."""

        manager = temp_memory
        manager.save_checkpoint(commit_hash="hash1", role="leader")
        manager.save_checkpoint(commit_hash="hash2", role="executor")
        checkpoints = manager.list_checkpoints()
        assert len(checkpoints) == 2
        hashes = {cp["commit_hash"] for cp in checkpoints}
        assert hashes == {"hash1", "hash2"}

    def test_list_checkpoints_ordered_newest_first(
        self, temp_memory: MemoryManager
    ) -> None:
        """Checkpoints are returned newest-first by timestamp."""

        manager = temp_memory
        first = manager.save_checkpoint(commit_hash="old", role="r")
        second = manager.save_checkpoint(commit_hash="new", role="r")
        cps = manager.list_checkpoints()
        assert cps[0]["id"] == second
        assert cps[1]["id"] == first


# ── AutoDream ───────────────────────────────────────────────────────


class TestAutoDream:
    """Tests for the async ``autodream`` consolidation."""

    @pytest.mark.asyncio
    async def test_autodream_extracts_facts(
        self, temp_memory: MemoryManager
    ) -> None:
        """``autodream`` promotes fact-tagged mid-term entries to long-term.

        With ``idle_seconds=0`` the dream runs immediately; any mid-term
        entry tagged ``fact`` is consolidated into a long-term archive
        entry.
        """

        manager = temp_memory
        manager.add_mid_term(MemoryEntry(
            tier=MemoryTier.MID,
            content="important fact",
            role="researcher",
            tags=["fact"],
        ))
        await manager.autodream(idle_seconds=0)
        ctx = manager.assemble_context("any", max_tokens=100_000)
        long_entries = [m for m in ctx if m.role == "[档案·long]"]
        assert long_entries
        assert "AutoDream" in long_entries[0].content

    @pytest.mark.asyncio
    async def test_autodream_without_facts_is_noop(
        self, temp_memory: MemoryManager
    ) -> None:
        """With no fact-tagged entries autodream adds nothing."""

        manager = temp_memory
        manager.add_mid_term(MemoryEntry(
            tier=MemoryTier.MID,
            content="just a note",
            role="r",
            tags=["note"],
        ))
        await manager.autodream(idle_seconds=0)
        ctx = manager.assemble_context("any", max_tokens=100_000)
        assert not [m for m in ctx if m.role == "[档案·long]"]

    @pytest.mark.asyncio
    async def test_autodream_reentrant_guard(
        self, temp_memory: MemoryManager
    ) -> None:
        """A second concurrent ``autodream`` call returns immediately."""

        manager = temp_memory
        manager._autodream_running = True  # type: ignore[attr-defined]
        # Should return without sleeping or raising.
        await manager.autodream(idle_seconds=0)
