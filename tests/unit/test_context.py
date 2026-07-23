"""Unit tests for ``multimind.engine.context`` — layered ContextBuilder.

Covers:

* Turn splitting (:func:`split_turns`) — user opens a turn, system turns
  are always standalone, agent replies join the current turn.
* Token estimation (:func:`estimate_tokens` / :func:`count_char_classes`)
  — CJK per-char, ASCII per-4-chars.
* L1 keyframe detection — task-intent messages such as "请实现登录功能".
* L2 fact extraction — "系统→JWT认证" style relations from arrows and
  relation verbs.
* L2 relevance ranking — character-bigram overlap with the query.
* :meth:`ContextBuilder.build` — layered assembly, strict token budget,
  metadata annotation and diagnostic stats.
"""

from __future__ import annotations

from multimind.core.types import Message
from multimind.engine.context import (
    ContextBuilder,
    count_char_classes,
    estimate_tokens,
    split_turns,
)


def _msg(role: str, content: str) -> Message:
    """Build a minimal ``Message`` for tests."""

    return Message(role=role, content=content)


# ── Turn splitting ────────────────────────────────────────────────


class TestSplitTurns:
    """Tests for message → turn grouping."""

    def test_empty_messages_no_turns(self) -> None:
        assert split_turns([]) == []

    def test_single_user_message_one_turn(self) -> None:
        turns = split_turns([_msg("user", "hi")])
        assert len(turns) == 1
        assert len(turns[0].messages) == 1

    def test_user_then_agent_grouped(self) -> None:
        """An agent reply joins the turn opened by the user."""

        turns = split_turns([_msg("user", "task"), _msg("leader", "ok")])
        assert len(turns) == 1
        assert [m.role for m in turns[0].messages] == ["user", "leader"]

    def test_each_user_starts_new_turn(self) -> None:
        turns = split_turns(
            [
                _msg("user", "one"),
                _msg("leader", "r1"),
                _msg("user", "two"),
                _msg("user", "three"),
            ]
        )
        assert len(turns) == 3

    def test_leading_agent_messages_grouped(self) -> None:
        """system followed by user: system is its own turn, user opens a new one.

        Regression: the original assertion expected a single turn — the
        correct grouping is 2 turns.
        """

        turns = split_turns([_msg("system", "boot"), _msg("user", "go")])
        assert len(turns) == 2
        assert turns[0].messages[0].role == "system"
        assert turns[1].messages[0].role == "user"

    def test_system_message_always_alone(self) -> None:
        """A system turn never absorbs neighbours; the next message opens a turn."""

        turns = split_turns(
            [
                _msg("user", "u1"),
                _msg("system", "notice"),
                _msg("leader", "a1"),
            ]
        )
        assert len(turns) == 3
        assert len(turns[1].messages) == 1
        assert turns[1].messages[0].role == "system"

    def test_agent_without_user_forms_turn(self) -> None:
        """Leading non-user/non-system messages group into a single turn."""

        turns = split_turns([_msg("leader", "a"), _msg("executor", "b")])
        assert len(turns) == 1
        assert len(turns[0].messages) == 2

    def test_turn_index_sequential(self) -> None:
        turns = split_turns(
            [
                _msg("system", "s"),
                _msg("user", "u"),
                _msg("leader", "l"),
                _msg("user", "u2"),
            ]
        )
        assert [t.index for t in turns] == [0, 1, 2]


# ── Token estimation ──────────────────────────────────────────────


class TestTokenEstimation:
    """Tests for CJK-aware token estimation."""

    def test_estimate_tokens_pure_ascii(self) -> None:
        # 11 ASCII chars → ceil(11 / 4) == 3
        assert estimate_tokens("hello world") == 3

    def test_pure_chinese(self) -> None:
        """ "你好世界测试中文_TOKEN" is 8 CJK + 6 ASCII — not 10 CJK.

        Regression: the original assertion counted the whole string as
        10 CJK chars; ``_TOKEN`` is 6 ASCII chars.
        """

        cjk, ascii_count = count_char_classes("你好世界测试中文_TOKEN")
        assert cjk == 8
        assert ascii_count == 6
        assert estimate_tokens("你好世界测试中文_TOKEN") == 8 + 2

    def test_mixed_text(self) -> None:
        # 2 CJK + 5 ASCII → 2 + ceil(5/4) == 4
        assert estimate_tokens("你好world") == 4

    def test_count_char_classes_ascii(self) -> None:
        assert count_char_classes("hello") == (0, 5)

    def test_empty_string_zero_tokens(self) -> None:
        assert count_char_classes("") == (0, 0)
        assert estimate_tokens("") == 0

    def test_estimate_tokens_at_least_one_for_nonempty(self) -> None:
        assert estimate_tokens("a") == 1
        assert estimate_tokens("你") == 1


# ── L1 keyframes ──────────────────────────────────────────────────


class TestKeyframes:
    """Tests for task-intent keyframe detection."""

    def test_keyframe_detection_chinese(self) -> None:
        builder = ContextBuilder()
        turn = split_turns([_msg("user", "请实现登录功能")])[0]
        assert builder.is_keyframe(turn)

    def test_keyframe_detection_english(self) -> None:
        builder = ContextBuilder()
        turn = split_turns([_msg("user", "please implement the cache")])[0]
        assert builder.is_keyframe(turn)

    def test_casual_chat_not_keyframe(self) -> None:
        builder = ContextBuilder()
        turn = split_turns([_msg("user", "今天天气真不错")])[0]
        assert not builder.is_keyframe(turn)

    def test_find_keyframes_preserves_order(self) -> None:
        builder = ContextBuilder()
        turns = split_turns(
            [
                _msg("user", "请实现登录功能"),
                _msg("user", "今天天气不错"),
                _msg("user", "再修复一下报错"),
            ]
        )
        keyframes = builder.find_keyframes(turns)
        assert len(keyframes) == 2
        assert "请实现登录功能" in keyframes[0].text
        assert "修复" in keyframes[1].text


# ── L2 fact extraction ────────────────────────────────────────────


class TestFactExtraction:
    """Tests for relation-fact extraction."""

    def test_arrow_fact_extraction(self) -> None:
        builder = ContextBuilder()
        turns = split_turns([_msg("leader", "架构决策: 系统→JWT认证")])
        facts = builder.extract_facts(turns)
        assert any(f.subject == "系统" and f.obj == "JWT认证" for f in facts)

    def test_verb_fact_extraction(self) -> None:
        builder = ContextBuilder()
        turns = split_turns([_msg("leader", "登录需要token验证")])
        facts = builder.extract_facts(turns)
        assert any(f.render() == "登录→token验证" for f in facts)

    def test_fact_dedup(self) -> None:
        builder = ContextBuilder()
        turns = split_turns(
            [
                _msg("user", "系统→JWT认证"),
                _msg("user", "再说一次: 系统→JWT认证"),
            ]
        )
        facts = builder.extract_facts(turns)
        rendered = [f.render() for f in facts]
        assert rendered.count("系统→JWT认证") == 1

    def test_fact_render_format(self) -> None:
        builder = ContextBuilder()
        turns = split_turns([_msg("leader", "系统使用JWT认证")])
        facts = builder.extract_facts(turns)
        assert any(f.render() == "系统→JWT认证" for f in facts)

    def test_no_facts_in_casual_text(self) -> None:
        builder = ContextBuilder()
        turns = split_turns([_msg("user", "今天天气很好适合散步")])
        assert builder.extract_facts(turns) == []


# ── L2 relevance ranking ──────────────────────────────────────────


class TestRelevance:
    """Tests for bigram-overlap relevance ranking."""

    def test_rank_relevant_matches_query(self) -> None:
        builder = ContextBuilder()
        turns = split_turns(
            [
                _msg("user", "请实现登录功能"),
                _msg("user", "今天天气很好"),
            ]
        )
        ranked = builder.rank_relevant(turns, "登录功能")
        assert len(ranked) == 1
        assert "登录" in ranked[0].text

    def test_rank_relevant_filters_zero_overlap(self) -> None:
        builder = ContextBuilder()
        turns = split_turns([_msg("user", "今天天气很好")])
        assert builder.rank_relevant(turns, "数据库索引") == []

    def test_rank_relevant_empty_query(self) -> None:
        builder = ContextBuilder()
        turns = split_turns([_msg("user", "请实现登录功能")])
        assert builder.rank_relevant(turns, "") == []


# ── build() assembly ──────────────────────────────────────────────


class TestBuild:
    """Tests for the layered ``ContextBuilder.build`` assembly."""

    def test_build_empty_messages(self) -> None:
        assert ContextBuilder().build([], max_tokens=100) == []

    def test_build_zero_budget_returns_empty(self) -> None:
        """Strict budget: a non-positive budget yields an empty context."""

        builder = ContextBuilder()
        assert builder.build([_msg("user", "hi")], max_tokens=0) == []

    def test_build_tiny_budget_may_return_empty(self) -> None:
        """Honest trimming: nothing fits into a 1-token budget."""

        builder = ContextBuilder()
        msgs = [_msg("user", "x" * 10_000) for _ in range(5)]
        assert builder.build(msgs, max_tokens=1) == []

    def test_build_includes_active_window(self) -> None:
        builder = ContextBuilder()
        ctx = builder.build([_msg("user", "最新消息")], max_tokens=100)
        assert any(m.content == "最新消息" for m in ctx)

    def test_build_l0_prefers_recent(self) -> None:
        """When the budget is tight, the most recent message wins."""

        builder = ContextBuilder()
        msgs = [
            _msg("user", "旧消息" + "x" * 100),  # 3 CJK + 100 ASCII ≈ 28 tokens
            _msg("user", "最新消息"),  # 4 tokens
        ]
        ctx = builder.build(msgs, max_tokens=10)
        contents = [m.content for m in ctx]
        assert "最新消息" in contents
        assert not any(c.startswith("旧消息") for c in contents)

    def test_build_keyframe_layer(self) -> None:
        """Keyframes from history turns surface as an L1 digest message."""

        builder = ContextBuilder(active_turns=1)
        msgs = [
            _msg("user", "请实现登录功能"),  # history turn → keyframe
            _msg("leader", "好的"),
            _msg("user", "今天天气不错"),  # active window
        ]
        ctx = builder.build(msgs, max_tokens=1000)
        assert any(m.role == "[关键帧]" and "请实现登录功能" in m.content for m in ctx)

    def test_build_fact_layer(self) -> None:
        """Facts from history turns surface as an L2 digest message."""

        builder = ContextBuilder(active_turns=1)
        msgs = [
            _msg("leader", "系统使用JWT认证，登录→token验证"),
            _msg("user", "继续"),
        ]
        ctx = builder.build(msgs, max_tokens=1000)
        fact_msgs = [m for m in ctx if m.role == "[事实]"]
        assert fact_msgs
        assert "系统→JWT认证" in fact_msgs[0].content
        assert "登录→token验证" in fact_msgs[0].content

    def test_build_full_scenario(self) -> None:
        """End-to-end: turns split + keyframes + facts + L0 combine correctly.

        Mirrors the smoke scenario: 3 turns, keyframe "请实现登录功能",
        facts "系统→JWT认证" / "登录→token验证", and the active window.
        """

        builder = ContextBuilder(active_turns=1)
        msgs = [
            _msg("user", "请实现登录功能"),
            _msg("leader", "好的，系统使用JWT认证"),
            _msg("user", "登录需要token验证吗"),
            _msg("leader", "是的，登录→token验证"),
            _msg("user", "现在开始写代码"),
        ]
        # Turn splitting: 3 turns
        assert len(builder.split_turns(msgs)) == 3

        ctx = builder.build(msgs, query="登录", max_tokens=2000)
        roles = [m.role for m in ctx]

        # L1 keyframes + L2 facts + L0 active window, in order
        assert "[关键帧]" in roles
        assert "[事实]" in roles
        assert "现在开始写代码" in [m.content for m in ctx]
        assert roles.index("[关键帧]") < roles.index("[事实]") < len(roles) - 1

    def test_build_metadata_annotated(self) -> None:
        """Every emitted message carries ``layer`` / ``tokens`` metadata."""

        builder = ContextBuilder(active_turns=1)
        msgs = [
            _msg("user", "请实现登录功能"),
            _msg("user", "继续"),
        ]
        ctx = builder.build(msgs, max_tokens=1000)
        assert ctx
        for m in ctx:
            assert m.metadata.get("layer") in {"L0", "L1", "L2"}
            assert isinstance(m.metadata.get("tokens"), int)
        l0 = [m for m in ctx if m.metadata["layer"] == "L0"]
        assert l0[0].metadata["tokens"] == estimate_tokens(l0[0].content)

    def test_build_stats(self) -> None:
        """``last_stats`` reflects the most recent build."""

        builder = ContextBuilder(active_turns=1)
        msgs = [
            _msg("user", "请实现登录功能"),
            _msg("leader", "系统→JWT认证"),
            _msg("user", "继续"),
        ]
        builder.build(msgs, query="登录", max_tokens=1000)
        stats = builder.last_stats
        assert stats.total_turns == 2  # [user+leader] + [user]
        assert stats.l1_keyframes >= 1
        assert stats.l2_facts >= 1
        assert stats.l0_messages == 1
        assert 0 < stats.tokens_used <= 1000
        assert stats.token_budget == 1000
