"""Unit tests for ``multimind.git.auto_commit`` — AutoGit engine.

Covers:
* Successful auto-commit on a real temporary git repository.
* Sensitive-file interception (``.env`` and friends are blocked).
* Audit-log recording of every commit attempt.
* Checkpoint linkage with :class:`MemoryManager`.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from multimind.git.auto_commit import (
    AutoGit,
    CommitTrigger,
    GitConfig,
)

if TYPE_CHECKING:
    from pathlib import Path

    from multimind.memory.manager import MemoryManager


def _write(repo: Path, name: str, content: str = "data\n") -> Path:
    """Write a file inside ``repo`` and return its path."""

    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _last_commit_message(repo: Path) -> str:
    """Return the message of the most recent commit in ``repo``."""

    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ── Successful commit ───────────────────────────────────────────────


class TestAutoGitCommit:
    """Tests for the happy-path commit flow."""

    def test_commit_success(self, temp_git_repo: Path) -> None:
        """A normal file is staged and committed successfully."""

        _write(temp_git_repo, "feature.py", "print('hi')\n")
        ag = AutoGit(repo_path=temp_git_repo, config=GitConfig(fast_mode=True))
        result = ag.commit(files=["feature.py"], role="executor")

        assert result.success
        assert result.commit_hash
        assert result.rolled_back is False
        assert "feature.py" in result.message or "executor" in result.message

    def test_commit_advances_head(self, temp_git_repo: Path) -> None:
        """A successful commit creates a new git commit object."""

        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _write(temp_git_repo, "a.txt", "a\n")
        ag = AutoGit(repo_path=temp_git_repo, config=GitConfig(fast_mode=True))
        result = ag.commit(files=["a.txt"])

        assert result.success
        assert result.commit_hash != head_before
        assert _last_commit_message(temp_git_repo) == result.message

    def test_commit_with_custom_message(self, temp_git_repo: Path) -> None:
        """A user-supplied commit message is used verbatim."""

        _write(temp_git_repo, "b.txt", "b\n")
        ag = AutoGit(repo_path=temp_git_repo, config=GitConfig(fast_mode=True))
        result = ag.commit(
            files=["b.txt"], message="custom: did the thing"
        )
        assert result.success
        assert result.message == "custom: did the thing"
        assert _last_commit_message(temp_git_repo) == "custom: did the thing"

    def test_commit_trigger_manual_overrides_disabled_auto(
        self, temp_git_repo: Path
    ) -> None:
        """``MANUAL`` trigger commits even when ``auto_commit`` is off."""

        _write(temp_git_repo, "c.txt", "c\n")
        ag = AutoGit(
            repo_path=temp_git_repo,
            config=GitConfig(auto_commit=False, fast_mode=True),
        )
        result = ag.commit(files=["c.txt"], trigger=CommitTrigger.MANUAL)
        assert result.success

    def test_commit_blocked_when_auto_disabled(self, temp_git_repo: Path) -> None:
        """With ``auto_commit=False`` and no manual trigger, nothing commits."""

        _write(temp_git_repo, "d.txt", "d\n")
        ag = AutoGit(
            repo_path=temp_git_repo,
            config=GitConfig(auto_commit=False, fast_mode=True),
        )
        result = ag.commit(files=["d.txt"])
        assert result.success is False


# ── Sensitive file interception ─────────────────────────────────────


class TestSensitiveInterception:
    """Tests for the sensitive-file guard."""

    @pytest.mark.parametrize(
        "filename",
        [".env", "secret.key", "auth.enc", "credentials.json", "my_secret.txt"],
    )
    def test_sensitive_files_blocked(
        self, temp_git_repo: Path, filename: str
    ) -> None:
        """Sensitive file patterns are intercepted and never committed."""

        _write(temp_git_repo, filename, "topsecret\n")
        ag = AutoGit(repo_path=temp_git_repo, config=GitConfig(fast_mode=True))
        result = ag.commit(files=[filename])
        assert result.success is False
        # The sensitive file must remain unstaged/uncommitted.
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert filename in status

    def test_only_sensitive_files_yields_no_safe_files(
        self, temp_git_repo: Path
    ) -> None:
        """When every requested file is sensitive the commit aborts cleanly."""

        _write(temp_git_repo, ".env", "x\n")
        ag = AutoGit(repo_path=temp_git_repo, config=GitConfig(fast_mode=True))
        result = ag.commit(files=[".env"])
        assert result.success is False
        assert "无安全文件" in result.message

    def test_sensitive_file_filtered_keeps_safe_files(
        self, temp_git_repo: Path
    ) -> None:
        """A mixed list drops sensitive files but commits the safe ones."""

        _write(temp_git_repo, ".env", "x\n")
        _write(temp_git_repo, "code.py", "y = 1\n")
        ag = AutoGit(repo_path=temp_git_repo, config=GitConfig(fast_mode=True))
        result = ag.commit(files=[".env", "code.py"])
        assert result.success
        # The safe file is committed, the sensitive one is not.
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "code.py" in tracked
        assert ".env" not in tracked


# ── Audit log ───────────────────────────────────────────────────────


class TestAuditLog:
    """Tests for the commit audit trail."""

    def test_audit_log_records_successful_commit(
        self, temp_git_repo: Path
    ) -> None:
        """A successful commit appends a success entry to the audit log."""

        _write(temp_git_repo, "e.txt", "e\n")
        ag = AutoGit(repo_path=temp_git_repo, config=GitConfig(fast_mode=True))
        ag.commit(files=["e.txt"], role="executor")
        log = ag.audit_log
        assert len(log) == 1
        entry = log[0]
        assert entry["success"] is True
        assert entry["role"] == "executor"
        assert entry["commit_hash"]
        assert entry["note"] == "成功"

    def test_audit_log_returns_copy(self, temp_git_repo: Path) -> None:
        """``audit_log`` returns a copy that cannot mutate internals."""

        ag = AutoGit(repo_path=temp_git_repo, config=GitConfig(fast_mode=True))
        snapshot = ag.audit_log
        snapshot.clear()
        # Internal log is unaffected because a fresh copy is returned each call.
        assert ag._audit_log == []  # type: ignore[attr-defined]

    def test_audit_log_records_trigger(
        self, temp_git_repo: Path
    ) -> None:
        """The audit entry records the commit trigger value."""

        _write(temp_git_repo, "f.txt", "f\n")
        ag = AutoGit(repo_path=temp_git_repo, config=GitConfig(fast_mode=True))
        ag.commit(files=["f.txt"], trigger=CommitTrigger.MILESTONE)
        assert ag.audit_log[0]["trigger"] == "milestone"


# ── Checkpoint linkage ──────────────────────────────────────────────


class TestCheckpointLinkage:
    """Tests for the AutoGit <-> MemoryManager checkpoint linkage."""

    def test_commit_creates_checkpoint(
        self, temp_git_repo: Path, temp_memory: MemoryManager
    ) -> None:
        """A successful commit with a MemoryManager saves a checkpoint."""

        _write(temp_git_repo, "g.txt", "g\n")
        ag = AutoGit(
            repo_path=temp_git_repo,
            config=GitConfig(fast_mode=True),
            memory=temp_memory,
        )
        result = ag.commit(files=["g.txt"], role="executor")

        assert result.success
        assert result.checkpoint_id > 0
        checkpoints = temp_memory.list_checkpoints()
        assert len(checkpoints) == 1
        assert checkpoints[0]["commit_hash"] == result.commit_hash
        assert checkpoints[0]["role"] == "executor"

    def test_commit_without_memory_has_zero_checkpoint(
        self, temp_git_repo: Path
    ) -> None:
        """Without a MemoryManager the checkpoint id stays at its default 0."""

        _write(temp_git_repo, "h.txt", "h\n")
        ag = AutoGit(
            repo_path=temp_git_repo,
            config=GitConfig(fast_mode=True),
        )
        result = ag.commit(files=["h.txt"])
        assert result.success
        assert result.checkpoint_id == 0

    def test_multiple_commits_create_distinct_checkpoints(
        self, temp_git_repo: Path, temp_memory: MemoryManager
    ) -> None:
        """Two commits produce two distinct checkpoints."""

        ag = AutoGit(
            repo_path=temp_git_repo,
            config=GitConfig(fast_mode=True),
            memory=temp_memory,
        )
        _write(temp_git_repo, "i1.txt", "1\n")
        r1 = ag.commit(files=["i1.txt"], role="leader")
        _write(temp_git_repo, "i2.txt", "2\n")
        r2 = ag.commit(files=["i2.txt"], role="leader")

        assert r1.checkpoint_id != r2.checkpoint_id
        assert len(temp_memory.list_checkpoints()) == 2
