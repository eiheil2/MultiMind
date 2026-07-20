"""``multimind chat`` 命令 — 开始群聊。"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from multimind.adapters.registry import init_default_providers
from multimind.engine import Orchestrator

__all__ = ["chat_command"]

console = Console()


def chat_command(
    message: str = typer.Option("", "-m", "--message", help="直接发送消息（非交互模式）"),
    tui: bool = typer.Option(False, "--tui", help="启动 TUI 界面"),
    flatten: bool = typer.Option(False, "--flatten", help="以扁平模式启动"),
    no_auto_commit: bool = typer.Option(False, "--no-auto-commit", help="关闭自动提交"),
) -> None:
    """开始群聊。"""
    if tui:
        from multimind.ui.tui import run_tui

        run_tui()
        return

    init_default_providers()
    orchestrator = Orchestrator()

    if flatten:
        asyncio.run(orchestrator.topology.flatten())

    if message:
        _run_headless(orchestrator, message)
    else:
        _interactive(orchestrator)


def _run_headless(orchestrator: Orchestrator, message: str) -> None:
    """非交互模式：Headless 流式输出。"""

    async def _run() -> None:
        async for chunk in orchestrator.run(message, max_rounds=2):
            console.print(chunk, end="")

    asyncio.run(_run())


def _interactive(orchestrator: Orchestrator) -> None:
    """交互式群聊。"""
    console.print(Panel.fit(
        "[bold]MultiMind[/] — 多 AI 协作 CLI Agent\n"
        "输入消息开始群聊，[/]退出。命令: /flatten /rebuild /status /help",
        title="欢迎使用",
        border_style="green",
    ))

    while True:
        try:
            user_input = console.input("\n[bold cyan]👤 你:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n再见!")
            break

        if not user_input:
            continue
        if user_input in ("/exit", "/quit", "/q"):
            break
        if user_input == "/help":
            _show_help()
            continue
        if user_input == "/status":
            _show_status(orchestrator)
            continue
        if user_input == "/flatten":
            msg = asyncio.run(orchestrator.topology.flatten())
            console.print(f"[yellow]{msg}[/]")
            continue
        if user_input == "/rebuild":
            msg = asyncio.run(orchestrator.topology.rebuild())
            console.print(f"[yellow]{msg}[/]")
            continue

        asyncio.run(_run_chat(orchestrator, user_input))


async def _run_chat(orchestrator: Orchestrator, user_input: str) -> None:
    """运行一轮群聊。"""
    async for chunk in orchestrator.run(user_input, max_rounds=2):
        console.print(chunk, end="")


def _show_status(orchestrator: Orchestrator) -> None:
    """显示状态。"""
    table = Table(title="MultiMind 状态", show_header=True)
    table.add_column("Provider", style="cyan")
    table.add_column("通道", style="magenta")
    table.add_column("剩余额度", justify="right")
    table.add_column("优先级", justify="right")

    for adapter in orchestrator.registry.all().values():
        table.add_row(
            adapter.config.name,
            adapter.channel_type.value,
            str(adapter.remaining_quota),
            str(adapter.config.priority),
        )
    console.print(table)
    console.print(f"\n拓扑: [bold]{orchestrator.topology.describe()}[/]")


def _show_help() -> None:
    """显示帮助。"""
    table = Table(title="命令列表", show_header=True)
    table.add_column("命令", style="cyan")
    table.add_column("说明")
    for cmd, desc in [
        ("/flatten", "拉平拓扑 — 所有角色同层"),
        ("/rebuild", "重建层级拓扑"),
        ("/status", "显示 provider 和拓扑状态"),
        ("/help", "显示此帮助"),
        ("/exit", "退出"),
    ]:
        table.add_row(cmd, desc)
    console.print(table)
