"""自动 Git 子系统 — 改码即提交、提交即校验、失败即回退。"""

from multimind.git.auto_commit import AutoGit, CommitResult, CommitTrigger, GitConfig, LintResult

__all__ = ["AutoGit", "GitConfig", "CommitTrigger", "CommitResult", "LintResult"]
