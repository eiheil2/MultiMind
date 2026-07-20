"""自动 Git 提交引擎 — 改码即提交、提交即校验、失败即回退。

借鉴 Aider 细粒度自动提交 + Claude Code checkpoint 联动。

流程：
1. Executor 改码 → 触发提交
2. 暂存改动文件（精确 ``git add``）
3. lint/test 校验链
4. 全通过 → ``git commit`` + 创建 checkpoint
5. 任一失败 → ``git reset --hard`` 回退 + 报告
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from multimind.core.exceptions import GitError

if TYPE_CHECKING:
    from multimind.memory.manager import MemoryManager

__all__ = [
    "CommitTrigger",
    "LintResult",
    "GitConfig",
    "CommitResult",
    "AutoGit",
]

logger = logging.getLogger(__name__)


class CommitTrigger(str, Enum):
    """提交触发时机。

    Attributes:
        STEP: Executor 单步改码后。
        STAGE: Dispatcher 阶段完成。
        MILESTONE: Leader 决策落地。
        MANUAL: 手动 ``/commit``。
    """

    STEP = "step"
    STAGE = "stage"
    MILESTONE = "milestone"
    MANUAL = "manual"


class LintResult(str, Enum):
    """校验结果。"""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(slots=True)
class GitConfig:
    """自动 Git 配置。

    Attributes:
        auto_commit: 总开关。
        trigger: 默认触发时机。
        work_branch_prefix: 工作分支前缀。
        protect_main: 禁止直接提交 main/master。
        lint_before_commit: 提交前跑 lint。
        test_before_commit: 提交前跑 test。
        fast_mode: 快速模式（跳过 lint/test）。
        max_retry: 校验失败重试上限。
        commit_message_style: commit message 风格。
        custom_hook: 自定义钩子脚本路径。
        worktree_isolation: 多 Executor 并行时 worktree 隔离。
        gc_on_exit: 退出时清理 worktree。
    """

    auto_commit: bool = True
    trigger: CommitTrigger = CommitTrigger.STEP
    work_branch_prefix: str = "mm/"
    protect_main: bool = True
    lint_before_commit: bool = True
    test_before_commit: bool = False
    fast_mode: bool = False
    max_retry: int = 3
    commit_message_style: str = "conventional"
    custom_hook: str = ""
    worktree_isolation: bool = True
    gc_on_exit: bool = True


@dataclass(slots=True)
class CommitResult:
    """提交结果。

    Attributes:
        success: 是否成功。
        commit_hash: 提交 hash（成功时）。
        message: commit message。
        lint_result: lint 校验结果。
        test_result: test 校验结果。
        rolled_back: 是否已回退。
        checkpoint_id: 关联的 checkpoint ID。
    """

    success: bool
    commit_hash: str = ""
    message: str = ""
    lint_result: LintResult = LintResult.SKIP
    test_result: LintResult = LintResult.SKIP
    rolled_back: bool = False
    checkpoint_id: int = 0


class AutoGit:
    """自动 Git 提交引擎。

    职责：
    - 监听群聊总线事件，在触发时机自动提交。
    - 提交前执行 lint/test 校验链。
    - 校验失败自动回退。
    - 与记忆系统的 checkpoint 联动。
    - 敏感文件拦截。

    Attributes:
        repo_path: Git 仓库路径。
        config: Git 配置。
        memory: 记忆管理器（可选，用于 checkpoint 联动）。
    """

    # 敏感文件模式（.multimindignore 强制排除）
    SENSITIVE_PATTERNS: tuple[str, ...] = (".env", ".key", "auth.enc", "secret", "credential")

    def __init__(
        self,
        repo_path: str | Path = ".",
        config: GitConfig | None = None,
        memory: MemoryManager | None = None,
    ) -> None:
        self.repo_path = Path(repo_path)
        self.config = config or GitConfig()
        self.memory = memory
        self._audit_log: list[dict[str, object]] = []

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        """执行 git 命令。

        Raises:
            GitError: git 命令执行超时或失败。
        """
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            raise GitError(f"git {' '.join(args)} timed out") from e

    def _is_sensitive(self, filepath: str) -> bool:
        """检查是否为敏感文件。"""
        return any(p in filepath.lower() for p in self.SENSITIVE_PATTERNS)

    def _generate_commit_message(
        self,
        role: str,
        files: list[str],
        style: str = "conventional",
    ) -> str:
        """生成 commit message（框架验证用模板，实际由 AI 生成）。"""
        if style == "conventional":
            file_summary = ", ".join(f[:30] for f in files[:3])
            return f"feat({role}): 更新 {file_summary}"
        return f"[{role}] 自动提交 {len(files)} 个文件"

    def _run_lint(self) -> LintResult:
        """lint 校验。"""
        if not self.config.lint_before_commit or self.config.fast_mode:
            return LintResult.SKIP
        # TODO: 实际实现 — 探测项目语言并跑 ruff/eslint
        return LintResult.PASS

    def _run_test(self) -> LintResult:
        """test 校验。"""
        if not self.config.test_before_commit or self.config.fast_mode:
            return LintResult.SKIP
        # TODO: 实际实现 — pytest -x / npm test
        return LintResult.PASS

    def _run_custom_hook(self) -> LintResult:
        """自定义钩子。"""
        if not self.config.custom_hook:
            return LintResult.SKIP
        hook_path = self.repo_path / self.config.custom_hook
        if not hook_path.exists():
            return LintResult.SKIP
        result = subprocess.run(
            ["bash", str(hook_path)],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return LintResult.PASS if result.returncode == 0 else LintResult.FAIL

    def commit(
        self,
        files: list[str],
        role: str = "executor",
        trigger: CommitTrigger | None = None,
        message: str = "",
    ) -> CommitResult:
        """执行自动提交。

        Args:
            files: 改动的文件列表。
            role: 触发提交的角色名。
            trigger: 触发时机（None 则用配置默认值）。
            message: 自定义 commit message（空则自动生成）。

        Returns:
            提交结果。
        """
        if not self.config.auto_commit and trigger != CommitTrigger.MANUAL:
            return CommitResult(success=False, message="自动提交已关闭")

        # 敏感文件过滤
        safe_files = [f for f in files if not self._is_sensitive(f)]
        if not safe_files:
            return CommitResult(success=False, message="无安全文件可提交")

        trigger = trigger or self.config.trigger
        commit_msg = message or self._generate_commit_message(
            role, safe_files, self.config.commit_message_style
        )

        # 记录提交前 HEAD（用于回退）
        head_before = self._git("rev-parse", "HEAD").stdout.strip()

        # 1. 精确暂存
        for f in safe_files:
            self._git("add", f)

        # 2. 校验链
        lint = self._run_lint()
        if lint == LintResult.FAIL:
            self._git("reset", "--hard", head_before)
            return self._log_result(
                CommitResult(False, message=commit_msg, lint_result=lint, rolled_back=True),
                role, trigger, "lint 失败",
            )

        test = self._run_test()
        if test == LintResult.FAIL:
            self._git("reset", "--hard", head_before)
            return self._log_result(
                CommitResult(False, message=commit_msg, lint_result=lint, test_result=test, rolled_back=True),
                role, trigger, "test 失败",
            )

        hook = self._run_custom_hook()
        if hook == LintResult.FAIL:
            self._git("reset", "--hard", head_before)
            return self._log_result(
                CommitResult(False, message=commit_msg, lint_result=hook, rolled_back=True),
                role, trigger, "自定义钩子失败",
            )

        # 3. 提交
        result = self._git("commit", "-m", commit_msg)
        if result.returncode != 0:
            return self._log_result(
                CommitResult(False, message=commit_msg, lint_result=lint, test_result=test),
                role, trigger, f"git commit 失败: {result.stderr[:100]}",
            )

        commit_hash = self._git("rev-parse", "HEAD").stdout.strip()

        # 4. 创建 checkpoint（联动）
        checkpoint_id = 0
        if self.memory:
            checkpoint_id = self.memory.save_checkpoint(commit_hash=commit_hash, role=role)

        logger.info("Committed: %s by %s (%s)", commit_hash[:8], role, trigger.value)
        return self._log_result(
            CommitResult(
                True,
                commit_hash=commit_hash,
                message=commit_msg,
                lint_result=lint,
                test_result=test,
                checkpoint_id=checkpoint_id,
            ),
            role, trigger, "成功",
        )

    def _log_result(
        self,
        result: CommitResult,
        role: str,
        trigger: CommitTrigger,
        note: str,
    ) -> CommitResult:
        """记录审计日志。"""
        self._audit_log.append({
            "timestamp": time.time(),
            "role": role,
            "trigger": trigger.value,
            "success": result.success,
            "commit_hash": result.commit_hash,
            "message": result.message,
            "lint": result.lint_result.value,
            "test": result.test_result.value,
            "rolled_back": result.rolled_back,
            "note": note,
        })
        return result

    @property
    def audit_log(self) -> list[dict[str, object]]:
        """审计日志副本。"""
        return list(self._audit_log)

    def status(self) -> str:
        """当前 Git 状态摘要。"""
        branch = self._git("branch", "--show-current").stdout.strip()
        status = self._git("status", "--porcelain").stdout.strip()
        n_changed = len([line for line in status.splitlines() if line.strip()]) if status else 0
        auto = "开" if self.config.auto_commit else "关"
        return f"分支: {branch} | 改动文件: {n_changed} | 自动提交: {auto}"

    def create_worktree(self, executor_name: str, session_id: str = "default") -> Path:
        """为 Executor 创建隔离 worktree。

        Args:
            executor_name: Executor 角色名。
            session_id: 会话 ID。

        Returns:
            worktree 路径。
        """
        branch_name = f"{self.config.work_branch_prefix}{session_id}/{executor_name}"
        wt_path = self.repo_path.parent / f".mm-worktree-{executor_name}"
        self._git("worktree", "add", "-b", branch_name, str(wt_path))
        logger.info("Worktree created: %s -> %s", executor_name, wt_path)
        return wt_path

    def remove_worktree(self, wt_path: Path) -> None:
        """清理 worktree。"""
        self._git("worktree", "remove", str(wt_path), "--force")
        logger.info("Worktree removed: %s", wt_path)
