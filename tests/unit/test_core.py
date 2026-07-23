"""Unit tests for ``multimind.core`` — domain types & exceptions.

Covers:
* Immutability (``frozen=True``) of :class:`Message` and
  :class:`ProviderConfig`.
* Enum value contracts for :class:`ChannelType`, :class:`RoleMode` and
  :class:`Permission`.
* The custom exception hierarchy rooted at :class:`MultiMindError`.
"""

from __future__ import annotations

import dataclasses

import pytest

from multimind.core.exceptions import (
    AdapterError,
    ConfigurationError,
    GitError,
    MemoryError,
    MultiMindError,
    RoutingError,
    SessionError,
)
from multimind.core.types import (
    ChannelType,
    Message,
    Permission,
    ProviderConfig,
    RoleMode,
)

# ── Message immutability ────────────────────────────────────────────


class TestMessage:
    """Tests for the :class:`Message` value object."""

    def test_message_is_frozen(self) -> None:
        """Assigning to a Message field raises ``FrozenInstanceError``.

        ``Message`` is a ``frozen=True`` dataclass so that messages
        flowing through the group-chat bus can never be mutated in
        place — every transformation must produce a new instance.
        """

        msg = Message(role="user", content="hello")
        with pytest.raises(dataclasses.FrozenInstanceError):
            msg.content = "changed"  # type: ignore[misc]

    def test_message_cannot_add_new_attribute(self) -> None:
        """Frozen + slots dataclasses reject new attribute creation.

        On CPython 3.10 the ``frozen=True, slots=True`` combination
        surfaces this as a ``TypeError`` from the generated
        ``__setattr__``; on later versions it is an ``AttributeError``.
        Both are acceptable evidence of immutability.
        """

        msg = Message(role="user", content="hello")
        with pytest.raises(
            (AttributeError, TypeError, dataclasses.FrozenInstanceError)
        ):
            msg.extra = "forbidden"  # type: ignore[attr-defined]

    def test_message_default_values(self) -> None:
        """Message defaults: empty channel, ``ACT`` mode, empty metadata."""

        msg = Message(role="leader", content="plan")
        assert msg.channel == ""
        assert msg.mode is RoleMode.ACT
        assert msg.metadata == {}
        # Each instance gets its own metadata dict (default_factory).
        assert msg.metadata is not Message(role="r", content="c").metadata

    def test_message_metadata_is_mutable_container(self) -> None:
        """The ``metadata`` dict itself is mutable even though the field
        is frozen — the immutability contract only protects field
        reassignment, not the container contents."""

        msg = Message(role="user", content="hi", metadata={"tokens": 5})
        assert msg.metadata["tokens"] == 5


# ── ProviderConfig immutability ─────────────────────────────────────


class TestProviderConfig:
    """Tests for the :class:`ProviderConfig` value object."""

    def test_provider_config_is_frozen(self) -> None:
        """Assigning to a ProviderConfig field raises ``FrozenInstanceError``."""

        cfg = ProviderConfig(name="p", channel=ChannelType.LOCAL)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.name = "other"  # type: ignore[misc]

    def test_provider_config_tags_default_is_empty_tuple(self) -> None:
        """``tags`` defaults to an empty tuple (not a list)."""

        cfg = ProviderConfig(name="p", channel=ChannelType.LOCAL)
        assert cfg.tags == ()
        assert isinstance(cfg.tags, tuple)

    def test_provider_config_accepts_tuple_tags(self) -> None:
        """Tags are provided as a tuple per the project convention."""

        cfg = ProviderConfig(
            name="p",
            channel=ChannelType.API_CLIENT,
            tags=("free", "fast"),
        )
        assert cfg.tags == ("free", "fast")
        assert isinstance(cfg.tags, tuple)

    def test_provider_config_default_priority_and_quota(self) -> None:
        """Defaults: priority 100, unlimited daily quota (-1)."""

        cfg = ProviderConfig(name="p", channel=ChannelType.LOCAL)
        assert cfg.priority == 100
        assert cfg.daily_quota == -1
        assert cfg.rpm_limit == 60
        assert cfg.max_tokens == 8192


# ── Enum contracts ──────────────────────────────────────────────────


class TestEnums:
    """Tests for the core enum value contracts."""

    def test_channel_type_enum_values(self) -> None:
        """All five channel types map to their documented string values."""

        assert ChannelType.CLI_REUSE.value == "cli_reuse"
        assert ChannelType.API_CLIENT.value == "api_client"
        assert ChannelType.BROWSER.value == "browser"
        assert ChannelType.PUBLIC_ENDPOINT.value == "public"
        assert ChannelType.LOCAL.value == "local"

    def test_channel_type_has_five_members(self) -> None:
        """Exactly five channel types are defined."""

        assert len(list(ChannelType)) == 5

    def test_channel_type_is_str_enum(self) -> None:
        """ChannelType subclasses ``str`` so values are usable as strings."""

        assert isinstance(ChannelType.LOCAL, str)
        assert ChannelType.LOCAL == "local"

    def test_role_mode_enum_values(self) -> None:
        """RoleMode exposes explore / plan / act modes."""

        assert RoleMode.EXPLORE.value == "explore"
        assert RoleMode.PLAN.value == "plan"
        assert RoleMode.ACT.value == "act"

    def test_permission_enum_values(self) -> None:
        """Permission exposes none / ask / auto / all levels."""

        assert Permission.NONE.value == "none"
        assert Permission.ASK.value == "ask"
        assert Permission.AUTO.value == "auto"
        assert Permission.ALL.value == "all"


# ── Exception hierarchy ─────────────────────────────────────────────


class TestExceptionHierarchy:
    """Tests for the custom exception hierarchy."""

    @pytest.mark.parametrize(
        "exc_class",
        [
            AdapterError,
            ConfigurationError,
            GitError,
            MemoryError,
            RoutingError,
            SessionError,
        ],
    )
    def test_subclass_of_multimind_error(self, exc_class: type[Exception]) -> None:
        """Every domain exception inherits from ``MultiMindError``."""

        assert issubclass(exc_class, MultiMindError)

    def test_all_subclasses_are_distinct(self) -> None:
        """The six domain exceptions are distinct classes."""

        classes = [
            AdapterError,
            ConfigurationError,
            GitError,
            MemoryError,
            RoutingError,
            SessionError,
        ]
        assert len(set(classes)) == len(classes)

    def test_subclass_catchable_via_base(self) -> None:
        """A subclass can be caught through the ``MultiMindError`` base."""

        with pytest.raises(MultiMindError):
            raise GitError("commit failed")

    def test_base_is_exception(self) -> None:
        """``MultiMindError`` itself is a standard ``Exception``."""

        assert issubclass(MultiMindError, Exception)

    def test_exception_carries_message(self) -> None:
        """Raised exceptions preserve their message for diagnostics."""

        err = RoutingError("no provider")
        assert str(err) == "no provider"
