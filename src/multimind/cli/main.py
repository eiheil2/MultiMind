"""CLI 主入口 — Typer 应用定义与命令注册。"""

from __future__ import annotations

import logging

import typer
from rich.console import Console

from multimind.cli.commands.chat import chat_command
from multimind.cli.commands.git import git_status_command
from multimind.cli.commands.init import init_command
from multimind.cli.commands.providers import providers_command, stats_command

__all__ = ["app"]

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(
    name="multimind",
    help="MultiMind — 多 AI 协作 CLI Agent",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# 注册命令
app.command(name="chat")(chat_command)
app.command(name="providers")(providers_command)
app.command(name="stats")(stats_command)
app.command(name="git-status")(git_status_command)
app.command(name="init")(init_command)


def main() -> None:
    """CLI 入口点。"""
    app()


if __name__ == "__main__":
    main()
