"""Unit tests for ``multimind.routing`` — quota, tags, failover & router.

Covers:
* :class:`QuotaTracker` record / remaining / unlimited semantics.
* :class:`TagMatcher` matching with and without required tags.
* :class:`FailoverChain` chain ordering and next-available selection.
* :class:`Router.select` picking the best provider with fallbacks and
  skipping quota-exhausted providers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from multimind.routing.failover import FailoverChain
from multimind.routing.quota import QuotaTracker
from multimind.routing.router import Router, RoutingResult
from multimind.routing.tags import TagMatcher

if TYPE_CHECKING:
    from multimind.adapters.registry import ProviderRegistry

# ── QuotaTracker ────────────────────────────────────────────────────


class TestQuotaTracker:
    """Tests for :class:`QuotaTracker` usage recording."""

    def test_record_increments_used(self) -> None:
        """``record`` accumulates the daily usage for a provider."""

        tracker = QuotaTracker()
        tracker.record("groq", 10)
        tracker.record("groq", 5)
        assert tracker.get_used("groq") == 15

    def test_remaining_subtracts_from_quota(self) -> None:
        """``remaining`` is the quota minus what was used today."""

        tracker = QuotaTracker()
        tracker.record("groq", 100)
        assert tracker.remaining("groq", daily_quota=1000) == 900

    def test_remaining_unlimited_for_negative_quota(self) -> None:
        """A negative ``daily_quota`` is treated as unlimited (999_999)."""

        tracker = QuotaTracker()
        tracker.record("ollama", 1_000_000)
        assert tracker.remaining("ollama", daily_quota=-1) == 999_999

    def test_remaining_clamps_to_zero(self) -> None:
        """``remaining`` never goes below zero."""

        tracker = QuotaTracker()
        tracker.record("groq", 2000)
        assert tracker.remaining("groq", daily_quota=1000) == 0

    def test_get_used_unknown_provider_is_zero(self) -> None:
        """A provider with no recorded usage reports zero used."""

        tracker = QuotaTracker()
        assert tracker.get_used("never-seen") == 0

    def test_record_is_idempotent_per_day(self) -> None:
        """Repeated records on the same day keep accumulating."""

        tracker = QuotaTracker()
        for _ in range(5):
            tracker.record("p", 1)
        assert tracker.get_used("p") == 5


# ── TagMatcher ──────────────────────────────────────────────────────


class TestTagMatcher:
    """Tests for :class:`TagMatcher` provider filtering."""

    def test_match_without_required_tags_returns_all(
        self, default_providers: ProviderRegistry
    ) -> None:
        """No required tags means every provider matches."""

        matcher = TagMatcher(default_providers)
        matched = matcher.match(None)
        assert len(matched) == 4

    def test_match_with_empty_list_returns_all(
        self, default_providers: ProviderRegistry
    ) -> None:
        """An empty required-tags list also matches everything."""

        matcher = TagMatcher(default_providers)
        assert len(matcher.match([])) == 4

    def test_match_with_single_tag(
        self, default_providers: ProviderRegistry
    ) -> None:
        """A single required tag returns only providers carrying it."""

        matcher = TagMatcher(default_providers)
        matched = matcher.match(["fast"])
        assert set(matched) == {"gemini-cli", "groq"}

    def test_match_with_multiple_tags_requires_all(
        self, default_providers: ProviderRegistry
    ) -> None:
        """Multiple required tags must all be present on the provider."""

        matcher = TagMatcher(default_providers)
        matched = matcher.match(["free", "fast"])
        assert set(matched) == {"gemini-cli", "groq"}
        matched_strict = matcher.match(["free", "long-context"])
        assert matched_strict == ["gemini-cli"]

    def test_match_no_provider_matches(
        self, default_providers: ProviderRegistry
    ) -> None:
        """An unmatched tag set returns an empty list."""

        matcher = TagMatcher(default_providers)
        assert matcher.match(["does-not-exist"]) == []


# ── FailoverChain ───────────────────────────────────────────────────


class TestFailoverChain:
    """Tests for :class:`FailoverChain` ordering and failover."""

    def test_get_chain_orders_by_priority(
        self, default_providers: ProviderRegistry
    ) -> None:
        """The chain is ordered ascending by provider priority."""

        chain = FailoverChain(default_providers).get_chain()
        assert chain == ["gemini-cli", "groq", "opencode-free", "ollama-local"]

    def test_get_chain_with_tag_filter(
        self, default_providers: ProviderRegistry
    ) -> None:
        """A required tag restricts the chain to matching providers."""

        chain = FailoverChain(default_providers).get_chain(required_tag="fast")
        assert chain == ["gemini-cli", "groq"]

    def test_next_available_returns_next_in_chain(
        self, default_providers: ProviderRegistry
    ) -> None:
        """After the first provider fails, the next one is returned."""

        fc = FailoverChain(default_providers)
        assert fc.next_available("gemini-cli") == "groq"
        assert fc.next_available("groq") == "opencode-free"

    def test_next_available_at_end_wraps_to_first(
        self, default_providers: ProviderRegistry
    ) -> None:
        """When the last provider fails, failover wraps back to the first.

        The implementation returns ``chain[0]`` when the failed provider
        is the last entry (or absent), so a retry of the highest-priority
        provider is always offered rather than giving up.
        """

        fc = FailoverChain(default_providers)
        assert fc.next_available("ollama-local") == "gemini-cli"

    def test_next_available_unknown_provider_returns_first(
        self, default_providers: ProviderRegistry
    ) -> None:
        """A failed provider not in the chain falls back to the first."""

        fc = FailoverChain(default_providers)
        assert fc.next_available("not-in-chain") == "gemini-cli"

    def test_next_available_with_tag_filter(
        self, default_providers: ProviderRegistry
    ) -> None:
        """Failover respects the tag filter.

        Within the ``fast``-tagged sub-chain ``[gemini-cli, groq]``:
        failing gemini-cli yields groq; failing groq (the sub-chain's
        last entry) wraps back to gemini-cli.
        """

        fc = FailoverChain(default_providers)
        assert fc.next_available("gemini-cli", required_tag="fast") == "groq"
        assert fc.next_available("groq", required_tag="fast") == "gemini-cli"

    def test_next_available_returns_none_for_empty_chain(
        self, default_providers: ProviderRegistry
    ) -> None:
        """When no provider matches the tag filter, failover returns None.

        ``next_available`` only yields ``None`` when the candidate chain
        itself is empty.
        """

        fc = FailoverChain(default_providers)
        assert fc.next_available("anyone", required_tag="nonexistent") is None


# ── Router ──────────────────────────────────────────────────────────


class TestRouter:
    """Tests for the :class:`Router` selection logic."""

    def test_select_returns_best_with_fallbacks(
        self, default_providers: ProviderRegistry
    ) -> None:
        """``select`` returns the highest-priority provider and its fallbacks."""

        router = Router(default_providers)
        result = router.select(["free", "fast"])
        assert result is not None
        assert isinstance(result, RoutingResult)
        assert result.provider == "gemini-cli"
        assert "groq" in result.fallbacks

    def test_select_no_required_tags_picks_lowest_priority(
        self, default_providers: ProviderRegistry
    ) -> None:
        """Without required tags the lowest-priority provider wins."""

        router = Router(default_providers)
        result = router.select(None)
        assert result is not None
        assert result.provider == "gemini-cli"

    def test_select_no_match_returns_none(
        self, default_providers: ProviderRegistry
    ) -> None:
        """When no provider matches the tags, ``select`` returns None."""

        router = Router(default_providers)
        assert router.select(["nonexistent-tag"]) is None

    def test_select_skips_exhausted_provider(
        self, default_providers: ProviderRegistry
    ) -> None:
        """A provider with zero remaining quota is skipped in favour of fallbacks."""

        router = Router(default_providers)
        # Exhaust gemini-cli (daily_quota=1000).
        gemini = default_providers.get("gemini-cli")
        assert gemini is not None
        gemini.record_usage(1000)
        assert gemini.remaining_quota == 0

        result = router.select(["free", "fast"])
        assert result is not None
        assert result.provider == "groq"
        assert "gemini-cli" not in result.fallbacks

    def test_select_all_exhausted_returns_none(
        self, default_providers: ProviderRegistry
    ) -> None:
        """When every matching provider is exhausted, ``select`` returns None."""

        router = Router(default_providers)
        for name in ("gemini-cli", "groq"):
            adapter = default_providers.get(name)
            assert adapter is not None
            adapter.record_usage(adapter.config.daily_quota)

        result = router.select(["free", "fast"])
        assert result is None

    def test_router_failover_delegates_to_chain(
        self, default_providers: ProviderRegistry
    ) -> None:
        """``Router.failover`` delegates to the underlying FailoverChain."""

        router = Router(default_providers)
        assert router.failover("gemini-cli") == "groq"

    def test_router_exposes_quota_tracker(
        self, default_providers: ProviderRegistry
    ) -> None:
        """The router exposes its :class:`QuotaTracker` via the ``quota`` property."""

        router = Router(default_providers)
        assert isinstance(router.quota, QuotaTracker)
