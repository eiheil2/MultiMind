"""``multimind git-status`` 命令。"""

from __future__ import annotations

import typer
from rich.console import Console

from multimind.git import AutoGit

__all__ = ["git_status_command"]

console = Console()


def git_status_command(
    repo: str = typer.Option(".", "--repo", help="Git 仓库路径"),
) -> None:
    """查看自动 Git 状态。"""
    ag = AutoGit(repo_path=repo)
    console.print("[bold]Git 状态:[/]")
    console.print(f"  {ag.status()}")
    if ag.audit_log:
        console.print(f"\n[bold]提交审计日志 ({len(ag.audit_log)} 条):[/]")
        for log in ag.audit_log[-5:]:
            status = "✅" if log["success"] else "❌"
            msg = str(log["message"])[:50]
            console.print(f"  {status} [{log['role']}] {msg}  ({log['note']})")
