"""``multimind init`` 命令 — 交互式初始化配置向导。

支持两种模式：
  - **快速开始** — 3 个问题（语言 + 启用站点 + 默认 Provider），其余用默认值
  - **专家模式** — 逐项配置语言、拓扑模式、API 密钥、工具权限、安全参数等

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

# 可用语言
_LANGUAGES = {
    "1": ("zh", "中文"),
    "2": ("en", "English"),
}

# 可用拓扑模式
_TOPOLOGIES = {
    "1": ("layered", "分层模式 — Leader → Dispatcher → Executor（推荐）"),
    "2": ("flat", "扁平模式 — 所有角色同层平等"),
    "3": ("hybrid", "混合模式 — 部分分层部分扁平"),
}

# 工具权限级别
_TOOL_PERMISSIONS = {
    "1": ("none", "禁用工具调用"),
    "2": ("ask", "每次确认（推荐）"),
    "3": ("auto", "低风险自动，高风险确认"),
    "4": ("all", "全部自动执行"),
}


def _print_banner() -> None:
    """打印欢迎横幅。"""
    console.print(
        Panel.fit(
            "[bold cyan]MultiMind 初始化向导[/]\n"
            "多 AI 协作 CLI Agent — 配置你的 AI 站点",
            border_style="cyan",
        )
    )


def _select_language() -> str:
    """选择界面语言。"""
    console.print("\n[bold]界面语言 / Interface Language[/]")
    for key, (_code, label) in _LANGUAGES.items():
        console.print(f"  {key}) {label}")
    choice = typer.prompt("选择", default="1", show_default=False)
    return _LANGUAGES.get(choice, ("zh", "中文"))[0]


def _select_topology() -> str:
    """选择拓扑模式。"""
    console.print("\n[bold]调用模式（拓扑）[/]")
    for key, (_code, label) in _TOPOLOGIES.items():
        console.print(f"  {key}) {label}")
    choice = typer.prompt("选择", default="1", show_default=False)
    return _TOPOLOGIES.get(choice, ("layered", ""))[0]


def _select_tool_permission() -> str:
    """选择工具权限。"""
    console.print("\n[bold]工具执行权限[/]")
    for key, (_code, label) in _TOOL_PERMISSIONS.items():
        console.print(f"  {key}) {label}")
    choice = typer.prompt("选择", default="2", show_default=False)
    return _TOOL_PERMISSIONS.get(choice, ("ask", ""))[0]


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

    invalid = [s for s in selected if s not in available]
    if invalid:
        console.print(f"[yellow]警告: 未知站点 {invalid}，已忽略[/]")
        selected = [s for s in selected if s in available]

    if not selected:
        console.print("[yellow]未选择任何站点，使用全部默认站点[/]")
        selected = list(available)

    return selected


def _select_default_provider(has_groq: bool) -> str:
    """选择默认 Provider。"""
    console.print("\n[bold]默认 Provider[/]")
    console.print("  1) gemini-cli — 免费CLI通道（推荐，无需密钥）")
    console.print("  2) opencode-free — 免费公共端点（无需密钥）")
    if has_groq:
        console.print("  3) groq — API通道（已配置密钥）")
    console.print("  4) ollama-local — 本地模型（需提前安装Ollama）")

    default = "1"
    choice = typer.prompt("选择", default=default, show_default=False)
    providers = {
        "1": "gemini-cli",
        "2": "opencode-free",
        "3": "groq" if has_groq else "gemini-cli",
        "4": "ollama-local",
    }
    return providers.get(choice, "gemini-cli")


def _input_api_keys() -> dict[str, str]:
    """输入 API 密钥（可选）。"""
    console.print("\n[bold]API 密钥配置（可选，回车跳过）[/]")
    console.print("  [dim]未配置密钥的 API Provider 会被跳过，不影响 CLI/公共端点通道[/]")

    keys: dict[str, str] = {}
    groq_key = typer.prompt("  Groq API Key (https://console.groq.com)", default="", show_default=False)
    if groq_key:
        keys["groq"] = groq_key

    return keys


def _simple_mode() -> dict[str, Any]:
    """快速开始模式 — 3 个核心问题。"""
    console.print("\n[bold green]=== 快速开始模式 ===[/]\n")

    language = _select_language()

    available = _show_available_sites()
    selected_sites = _select_sites(available)

    default_provider = _select_default_provider(has_groq=False)

    output_dir = typer.prompt(
        "输出目录",
        default=str(_DEFAULT_OUTPUT_DIR),
        show_default=True,
    )

    return {
        "general": {
            "language": language,
            "mode": "simple",
            "topology": "layered",
            "default_provider": default_provider,
            "tool_permission": "ask",
            "auto_commit": True,
            "output_dir": str(Path(output_dir).expanduser()),
        },
        "browser": {"headed": True},
        "safety": {
            "min_delay": 1.0,
            "max_delay": 3.0,
            "max_requests_per_session": 50,
            "session_timeout": 3600,
            "max_consecutive_errors": 5,
        },
        "sites": {"enabled": selected_sites},
        "logging": {"level": "INFO"},
    }


def _expert_mode() -> dict[str, Any]:
    """专家模式 — 逐项配置。"""
    console.print("\n[bold magenta]=== 专家模式 ===[/]\n")

    # 语言
    language = _select_language()

    # 拓扑模式
    topology = _select_topology()

    # 工具权限
    tool_permission = _select_tool_permission()

    # 站点
    available = _show_available_sites()
    selected_sites = _select_sites(available)

    # API 密钥
    api_keys = _input_api_keys()

    # 默认 Provider
    default_provider = _select_default_provider(has_groq="groq" in api_keys)

    # 输出目录
    output_dir = typer.prompt(
        "输出目录",
        default=str(_DEFAULT_OUTPUT_DIR),
        show_default=True,
    )

    # Auto-commit
    auto_commit = typer.confirm("自动 Git commit（每次任务后自动提交）", default=True)

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
        typer.prompt("每会话最大请求数", default="50", show_default=True)
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
            "language": language,
            "mode": "expert",
            "topology": topology,
            "default_provider": default_provider,
            "tool_permission": tool_permission,
            "auto_commit": auto_commit,
            "output_dir": str(Path(output_dir).expanduser()),
        },
        "browser": {"headed": headed},
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
        "logging": {"level": log_level},
    }

    if api_keys:
        config["api_keys"] = api_keys

    if use_custom_dir:
        config["sites"]["custom_dir"] = str(Path(custom_dir).expanduser())

    return config


def _generate_default_config() -> dict[str, Any]:
    """生成全默认配置（非交互式模式使用）。"""
    available = sorted(discover_profiles().keys())
    return {
        "general": {
            "language": "zh",
            "mode": "simple",
            "topology": "layered",
            "default_provider": "gemini-cli",
            "tool_permission": "ask",
            "auto_commit": True,
            "output_dir": str(_DEFAULT_OUTPUT_DIR),
        },
        "browser": {"headed": True},
        "safety": {
            "min_delay": 1.0,
            "max_delay": 3.0,
            "max_requests_per_session": 50,
            "session_timeout": 3600,
            "max_consecutive_errors": 5,
        },
        "sites": {"enabled": available},
        "logging": {"level": "INFO"},
    }


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
    general = config["general"]
    table = Table(title="配置摘要", show_header=True, header_style="bold cyan")
    table.add_column("项目", style="cyan", width=20)
    table.add_column("值", style="green")

    lang_label = "中文" if general["language"] == "zh" else "English"
    topo_label = {
        "layered": "分层 (Leader→Dispatcher→Executor)",
        "flat": "扁平",
        "hybrid": "混合",
    }.get(general["topology"], general["topology"])

    table.add_row("语言", lang_label)
    table.add_row("调用模式", topo_label)
    table.add_row("默认Provider", general["default_provider"])
    table.add_row("工具权限", general["tool_permission"])
    table.add_row("自动Commit", str(general["auto_commit"]))
    table.add_row("输出目录", general["output_dir"])
    table.add_row("浏览器有头", str(config["browser"]["headed"]))
    table.add_row("启用站点", ", ".join(config["sites"]["enabled"]))
    table.add_row("最小延迟", f"{config['safety']['min_delay']}s")
    table.add_row("最大延迟", f"{config['safety']['max_delay']}s")
    table.add_row("请求上限", str(config["safety"]["max_requests_per_session"]))
    table.add_row("日志级别", config["logging"]["level"])

    api_keys = config.get("api_keys", {})
    table.add_row("API密钥", ", ".join(api_keys.keys()) if api_keys else "无")

    custom_dir = config.get("sites", {}).get("custom_dir")
    if custom_dir:
        table.add_row("自定义配置目录", custom_dir)

    console.print(table)


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
        console.print("  [bold green]1) 快速开始[/] — 3 个问题，推荐新用户")
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

    # 将 API key 写入环境变量提示
    api_keys = cfg.get("api_keys", {})
    if api_keys:
        console.print(
            Panel.fit(
                "[bold green]初始化完成！[/]\n\n"
                "[bold]API 密钥已保存到配置文件。[/]\n"
                "同时建议设置环境变量（重启后仍可用）:\n"
                + "\n".join(
                    f"  export {k.upper().replace('-', '_')}_API_KEY=your_key"
                    for k in api_keys
                )
                + "\n\n下一步:\n"
                "  1. 直接运行: multimind\n"
                "  2. 查看Provider: multimind providers\n"
                "  3. 重新配置: multimind init --force",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel.fit(
                "[bold green]初始化完成！[/]\n\n"
                "下一步:\n"
                "  1. 直接运行: multimind\n"
                "  2. 查看Provider: multimind providers\n"
                "  3. 重新配置: multimind init --force\n"
                "  4. 配置API Key: multimind init --mode expert",
                border_style="green",
            )
        )
