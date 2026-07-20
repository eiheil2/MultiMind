"""``multimind init`` 命令 — 交互式初始化配置向导。

支持两种模式：
  - **快速开始** — 仅问 2 个问题（启用站点 + 输出目录），其余用默认值
  - **专家模式** — 逐项配置浏览器、安全参数、日志级别、自定义配置目录等

生成的配置文件位于 ``~/.multimind/config.toml``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomli_w
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from multimind.adapters.sites.profile import discover_profiles

__all__ = ["init_command"]

console = Console()

# 默认配置目录
_DEFAULT_CONFIG_DIR = Path.home() / ".multimind"
_DEFAULT_CONFIG_FILE = _DEFAULT_CONFIG_DIR / "config.toml"
_DEFAULT_OUTPUT_DIR = _DEFAULT_CONFIG_DIR / "output"
_DEFAULT_SITES_DIR = _DEFAULT_CONFIG_DIR / "sites"

# 内置站点列表
_BUILTIN_SITES = ["deepseek", "chatgpt", "qwen", "doubao", "kimi"]


def _print_banner() -> None:
    """打印欢迎横幅。"""
    console.print(
        Panel.fit(
            "[bold cyan]MultiMind 初始化向导[/]\n"
            "多 AI 协作 CLI Agent — 配置你的 AI 站点",
            border_style="cyan",
        )
    )


def _show_available_sites() -> list[str]:
    """显示可用站点列表，返回站点名列表。"""
    profiles = discover_profiles()
    sites = sorted(profiles.keys())

    table = Table(title="可用站点", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("站点", style="cyan")
    table.add_column("配置文件", style="green")

    for i, site in enumerate(sites, 1):
        table.add_row(str(i), site, str(profiles[site]))
    console.print(table)
    return sites


def _select_sites(available: list[str]) -> list[str]:
    """交互式选择启用的站点。"""
    default_str = ",".join(available)
    console.print(
        f"\n可用站点: [cyan]{', '.join(available)}[/]\n"
        f"输入要启用的站点（逗号分隔，回车=全部启用）:"
    )
    raw = typer.prompt("启用站点", default=default_str, show_default=False)
    selected = [s.strip() for s in raw.split(",") if s.strip()]

    # 验证
    invalid = [s for s in selected if s not in available]
    if invalid:
        console.print(f"[yellow]警告: 未知站点 {invalid}，已忽略[/]")
        selected = [s for s in selected if s in available]

    if not selected:
        console.print("[yellow]未选择任何站点，使用全部默认站点[/]")
        selected = list(available)

    return selected


def _simple_mode() -> dict[str, Any]:
    """快速开始模式 — 最少问题。"""
    console.print("\n[bold green]=== 快速开始模式 ===[/]\n")

    available = _show_available_sites()
    selected_sites = _select_sites(available)

    output_dir = typer.prompt(
        "输出目录",
        default=str(_DEFAULT_OUTPUT_DIR),
        show_default=True,
    )

    return {
        "general": {
            "mode": "simple",
            "output_dir": str(Path(output_dir).expanduser()),
        },
        "browser": {
            "headed": True,
        },
        "safety": {
            "min_delay": 1.0,
            "max_delay": 3.0,
            "max_requests_per_session": 50,
            "session_timeout": 3600,
            "max_consecutive_errors": 5,
        },
        "sites": {
            "enabled": selected_sites,
        },
        "logging": {
            "level": "INFO",
        },
    }


def _expert_mode() -> dict[str, Any]:
    """专家模式 — 逐项配置。"""
    console.print("\n[bold magenta]=== 专家模式 ===[/]\n")

    available = _show_available_sites()
    selected_sites = _select_sites(available)

    # 输出目录
    output_dir = typer.prompt(
        "输出目录",
        default=str(_DEFAULT_OUTPUT_DIR),
        show_default=True,
    )

    # 浏览器模式
    console.print("\n浏览器模式:")
    console.print("  1) 有头模式（推荐，降低封号风险）")
    console.print("  2) 无头模式（适合服务器）")
    browser_choice = typer.prompt("选择", default="1", show_default=False)
    headed = browser_choice != "2"

    # 安全参数
    console.print("\n[bold]安全参数配置[/]")
    min_delay = float(
        typer.prompt("操作间最小延迟（秒）", default="1.0", show_default=True)
    )
    max_delay = float(
        typer.prompt("操作间最大延迟（秒）", default="3.0", show_default=True)
    )
    max_requests = int(
        typer.prompt(
            "每会话最大请求数", default="50", show_default=True
        )
    )
    session_timeout = int(
        typer.prompt("会话超时（秒）", default="3600", show_default=True)
    )
    max_errors = int(
        typer.prompt("连续错误熔断阈值", default="5", show_default=True)
    )

    # 自定义站点配置目录
    console.print("\n[bold]自定义站点配置目录[/]")
    console.print(
        f"  默认: {_DEFAULT_SITES_DIR}\n"
        "  在此目录放置 .toml 文件即可添加新站点"
    )
    use_custom_dir = typer.confirm("使用自定义配置目录?", default=True)
    custom_dir = str(_DEFAULT_SITES_DIR)
    if use_custom_dir:
        custom_dir = typer.prompt(
            "配置目录路径",
            default=str(_DEFAULT_SITES_DIR),
            show_default=True,
        )

    # 日志级别
    console.print("\n[bold]日志级别[/]")
    console.print("  1) DEBUG（详细调试）")
    console.print("  2) INFO（一般信息，推荐）")
    console.print("  3) WARNING（仅警告）")
    console.print("  4) ERROR（仅错误）")
    log_choice = typer.prompt("选择", default="2", show_default=False)
    log_levels = {"1": "DEBUG", "2": "INFO", "3": "WARNING", "4": "ERROR"}
    log_level = log_levels.get(log_choice, "INFO")

    config: dict[str, Any] = {
        "general": {
            "mode": "expert",
            "output_dir": str(Path(output_dir).expanduser()),
        },
        "browser": {
            "headed": headed,
        },
        "safety": {
            "min_delay": min_delay,
            "max_delay": max_delay,
            "max_requests_per_session": max_requests,
            "session_timeout": session_timeout,
            "max_consecutive_errors": max_errors,
        },
        "sites": {
            "enabled": selected_sites,
        },
        "logging": {
            "level": log_level,
        },
    }

    if use_custom_dir:
        config["sites"]["custom_dir"] = str(Path(custom_dir).expanduser())

    return config


def _write_config(config: dict[str, Any], config_path: Path) -> None:
    """将配置写入 TOML 文件。"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "wb") as f:
        tomli_w.dump(config, f)
    console.print(f"\n[green]配置已写入: {config_path}[/]")


def _create_directories(config: dict[str, Any]) -> None:
    """根据配置创建必要目录。"""
    dirs_to_create = [
        Path(config["general"]["output_dir"]),
        _DEFAULT_CONFIG_DIR,
    ]

    custom_dir = config.get("sites", {}).get("custom_dir")
    if custom_dir:
        dirs_to_create.append(Path(custom_dir))

    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)
        console.print(f"  [dim]创建目录: {d}[/]")


def _show_summary(config: dict[str, Any]) -> None:
    """显示配置摘要。"""
    table = Table(title="配置摘要", show_header=True, header_style="bold cyan")
    table.add_column("项目", style="cyan", width=20)
    table.add_column("值", style="green")

    table.add_row("模式", config["general"]["mode"])
    table.add_row("输出目录", config["general"]["output_dir"])
    table.add_row("浏览器有头", str(config["browser"]["headed"]))
    table.add_row("启用站点", ", ".join(config["sites"]["enabled"]))
    table.add_row("最小延迟", f"{config['safety']['min_delay']}s")
    table.add_row("最大延迟", f"{config['safety']['max_delay']}s")
    table.add_row("请求上限", str(config["safety"]["max_requests_per_session"]))
    table.add_row("日志级别", config["logging"]["level"])

    custom_dir = config.get("sites", {}).get("custom_dir")
    if custom_dir:
        table.add_row("自定义配置目录", custom_dir)

    console.print(table)


def _generate_default_config() -> dict[str, Any]:
    """生成全默认配置（非交互式模式使用）。"""
    available = sorted(discover_profiles().keys())
    return {
        "general": {
            "mode": "simple",
            "output_dir": str(_DEFAULT_OUTPUT_DIR),
        },
        "browser": {
            "headed": True,
        },
        "safety": {
            "min_delay": 1.0,
            "max_delay": 3.0,
            "max_requests_per_session": 50,
            "session_timeout": 3600,
            "max_consecutive_errors": 5,
        },
        "sites": {
            "enabled": available,
        },
        "logging": {
            "level": "INFO",
        },
    }


def init_command(
    mode: str = typer.Option(
        "",
        "--mode",
        "-m",
        help="配置模式: simple(快速开始) 或 expert(专家模式)。留空则交互式选择。",
    ),
    config: str = typer.Option(
        "",
        "--config",
        "-c",
        help=f"配置文件路径（默认: {_DEFAULT_CONFIG_FILE}）",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="覆盖已存在的配置文件",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="非交互式模式：使用全部默认值，不提示任何问题（适合脚本/CI 环境）",
    ),
) -> None:
    """初始化 MultiMind 配置 — 交互式向导。"""
    config_path = Path(config).expanduser() if config else _DEFAULT_CONFIG_FILE

    # 检查已存在
    if config_path.exists() and not force:
        if non_interactive:
            console.print(f"[yellow]配置文件已存在: {config_path}，跳过（使用 --force 覆盖）[/]")
            raise typer.Exit(code=0)
        console.print(f"[yellow]配置文件已存在: {config_path}[/]")
        if not typer.confirm("是否覆盖?", default=False):
            console.print("[dim]取消初始化[/]")
            raise typer.Exit(code=0)

    # 非交互式模式：全默认值
    if non_interactive:
        console.print("[cyan]非交互式模式：使用全部默认值[/]")
        cfg = _generate_default_config()
        _write_config(cfg, config_path)
        console.print("\n[bold]创建目录...[/]")
        _create_directories(cfg)
        _show_summary(cfg)
        console.print(
            Panel.fit(
                "[bold green]初始化完成（非交互式）！[/]\n\n"
                f"配置文件: {config_path}\n"
                "如需自定义: multimind init --force",
                border_style="green",
            )
        )
        return

    _print_banner()

    # 选择模式
    if not mode:
        console.print("\n请选择配置模式:")
        console.print("  [bold green]1) 快速开始[/] — 2 个问题，推荐新用户")
        console.print("  [bold magenta]2) 专家模式[/] — 逐项配置所有参数")
        choice = typer.prompt("选择", default="1", show_default=False)
        mode = "simple" if choice != "2" else "expert"

    # 执行配置
    cfg = _expert_mode() if mode == "expert" else _simple_mode()

    # 写入配置
    _write_config(cfg, config_path)

    # 创建目录
    console.print("\n[bold]创建目录...[/]")
    _create_directories(cfg)

    # 显示摘要
    _show_summary(cfg)

    # 完成提示
    console.print(
        Panel.fit(
            "[bold green]初始化完成！[/]\n\n"
            "下一步:\n"
            f"  1. 编辑配置: {config_path}\n"
            "  2. 安装浏览器: playwright install chromium\n"
            "  3. 启动对话: multimind chat\n"
            "\n如需重新配置: multimind init --force",
            border_style="green",
        )
    )
