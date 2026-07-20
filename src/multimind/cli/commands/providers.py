"""``multimind providers`` 和 ``multimind stats`` 命令。"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from multimind.adapters.registry import get_registry, init_default_providers
from multimind.engine import Orchestrator

__all__ = ["providers_command", "stats_command"]

console = Console()


def providers_command() -> None:
    """列出已注册 provider。"""
    init_default_providers()
    table = Table(title="已注册 Provider")
    table.add_column("名称", style="cyan")
    table.add_column("通道", style="magenta")
    table.add_column("模型")
    table.add_column("标签", style="green")
    table.add_column("额度/天", justify="right")

    for adapter in get_registry().all().values():
        cfg = adapter.config
        quota = str(cfg.daily_quota) if cfg.daily_quota > 0 else "无限"
        table.add_row(
            cfg.name,
            cfg.channel.value,
            cfg.model,
            ",".join(cfg.tags),
            quota,
        )
    console.print(table)


def stats_command() -> None:
    """显示用量统计。"""
    init_default_providers()
    orch = Orchestrator()
    table = Table(title="MultiMind 状态", show_header=True)
    table.add_column("Provider", style="cyan")
    table.add_column("通道", style="magenta")
    table.add_column("剩余额度", justify="right")
    table.add_column("优先级", justify="right")

    for adapter in orch.registry.all().values():
        table.add_row(
            adapter.config.name,
            adapter.channel_type.value,
            str(adapter.remaining_quota),
            str(adapter.config.priority),
        )
    console.print(table)
    console.print(f"\n拓扑: [bold]{orch.topology.describe()}[/]")
