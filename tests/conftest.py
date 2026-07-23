"""Shared pytest fixtures for the MultiMind test suite.

This module provides fixtures that are reused across the unit and
integration test layers:

* ``_reset_registry`` — an autouse fixture that resets the global
  :class:`ProviderRegistry` singleton before (and after) every test, so
  tests stay isolated from each other.
* ``default_providers`` — registers the framework's default providers
  into the freshly reset registry and returns it.
* ``temp_git_repo`` — materialises a real, disposable git repository
  inside a temporary directory (required by :class:`AutoGit`).
* ``temp_memory`` — provides a :class:`MemoryManager` backed by a
  temporary SQLite database file, cleaning up afterwards.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from multimind.adapters.registry import (
    ProviderRegistry,
    get_registry,
    init_default_providers,
    reset_registry,
)
from multimind.memory.manager import MemoryManager

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset the global ``ProviderRegistry`` singleton around every test.

    The registry is a module-level singleton shared across the whole
    process.  Without a reset, providers registered by one test would
    leak into the next.  This autouse fixture wipes the registry before
    the test runs and again on teardown for good measure.

    Also sets a dummy ``GROQ_API_KEY`` so that ``init_default_providers``
    registers the Groq provider during tests.
    """

    monkeypatch.setenv("GROQ_API_KEY", "test-key-for-ci")
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def default_providers(monkeypatch: pytest.MonkeyPatch) -> ProviderRegistry:
    """Provide a registry pre-populated with the default providers.

    The fixture resets the singleton first (defensively, even though the
    autouse fixture already did) and then registers the four built-in
    providers used throughout the codebase.
    """

    monkeypatch.setenv("GROQ_API_KEY", "test-key-for-ci")
    reset_registry()
    init_default_providers()
    return get_registry()


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a real, disposable git repository for ``AutoGit`` tests.

    The repository is initialised, configured with a test identity, and
    seeded with an initial commit so that ``git rev-parse HEAD`` (used
    internally by :class:`AutoGit` to record the pre-commit state) works
    from the very first ``commit()`` call.
    """

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )

    _git("init")
    _git("config", "user.email", "test@multimind.dev")
    _git("config", "user.name", "MultiMind Test")
    # Seed an initial commit so HEAD exists.
    readme = repo_dir / "README.md"
    readme.write_text("# initial\n", encoding="utf-8")
    _git("add", "README.md")
    _git("commit", "-m", "chore: initial commit")

    return repo_dir


@pytest.fixture
def temp_memory(tmp_path: Path) -> Iterator[MemoryManager]:
    """Provide a ``MemoryManager`` backed by a temporary database file.

    The manager is closed on teardown so that the file handle is
    released before pytest removes the temporary directory.
    """

    db_path = tmp_path / "test_memory.db"
    manager = MemoryManager(db_path=db_path)
    try:
        yield manager
    finally:
        manager.close()
