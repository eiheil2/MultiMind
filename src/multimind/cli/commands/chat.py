"""``multimind chat`` 命令 — 现代 TUI 风格交互界面。

设计参考 OpenCode / Codex CLI：
  - 背景色分层替代边框框线
  - 斜杠命令内联自动补全（输入 / 触发，继续输入过滤）
  - 符号前缀区分操作类型（→ 读、● 完成）
  - 极简深色配色，语义化色槽
  - 流式输出 + 实时状态指示
"""

from __future__ import annotations

import asyncio
import os
import sys

import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from multimind.adapters.registry import init_default_providers
from multimind.engine import Orchestrator

__all__ = ["chat_command"]

console = Console()

# ── 语义色槽 ──────────────────────────────────────────────────────────
# 深色优先，近黑背景，输入框略亮
C_TEXT = "#e0e0e0"        # 主文本
C_MUTED = "#666666"       # 次要文本
C_DIM = "#444444"         # 最暗
C_ACCENT = "#7aa2f7"      # 品牌色（蓝紫）
C_SUCCESS = "#9ece6a"     # 成功（绿）
C_WARNING = "#e0af68"     # 警告（橙）
C_ERROR = "#f7768e"       # 错误（红）
C_USER = "#7dcfff"        # 用户消息（青）

# ── 斜杠命令注册表 ────────────────────────────────────────────────────
SLASH_COMMANDS: list[tuple[str, str, str]] = [
    ("/flatten", "切换为扁平模式（所有角色同层）", "mode"),
    ("/rebuild", "重建分层拓扑（Leader→Dispatcher→Executor）", "mode"),
    ("/status", "查看 Provider 额度和拓扑状态", "info"),
    ("/providers", "列出所有可用 Provider", "info"),
    ("/help", "显示所有命令", "info"),
    ("/clear", "清屏", "util"),
    ("/exit", "退出 MultiMind", "util"),
]


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


# ═══════════════════════════════════════════════════════════════════════
# 现代交互界面
# ═══════════════════════════════════════════════════════════════════════


def _interactive(orchestrator: Orchestrator) -> None:
    """现代交互式群聊 — OpenCode/Codex 风格。"""
    _print_header()
    _print_footer_hint()

    while True:
        try:
            user_input = _read_input()
        except (EOFError, KeyboardInterrupt):
            console.print(f"\n[{C_MUTED}]再见[/]")
            break

        if not user_input:
            continue

        # 斜杠命令
        if user_input.startswith("/"):
            if _handle_slash(user_input, orchestrator):
                break
            continue

        # 普通消息
        _print_user_message(user_input)
        asyncio.run(_run_chat(orchestrator, user_input))


def _print_header() -> None:
    """打印极简头部 — 无边框，用空白和颜色制造层次。"""
    console.print()
    console.print(
        f"[bold {C_ACCENT}]MultiMind[/] "
        f"[{C_MUTED}]多 AI 协作 CLI Agent[/]"
    )
    console.print(f"[{C_DIM}]{'─' * 50}[/]")
    console.print(
        f"[{C_MUTED}]输入消息开始对话，[/]"
        f"[bold {C_ACCENT}]/[/]"
        f"[{C_MUTED}]查看命令，[/]"
        f"[bold {C_MUTED}]Ctrl+C[/]"
        f"[{C_MUTED}]退出[/]"
    )
    console.print()


def _print_footer_hint() -> None:
    """底部快捷键提示。"""
    console.print(
        f"[{C_DIM}]  / 命令  ·  Tab 补全  ·  Ctrl+C 退出[/]\n"
    )


def _read_input() -> str:
    """读取用户输入，支持斜杠命令自动补全。

    TTY 环境下逐字符读取，输入 ``/`` 触发命令建议列表，
    继续输入实时过滤。非 TTY 环境回退为行输入。
    """
    # 非 TTY（管道 / CI）直接行输入
    if not sys.stdin.isatty():
        sys.stdout.write("\x1b[1;38;2;122;162;247m❯\x1b[0m ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            raise EOFError from None
        return line.rstrip("\n")

    buf = ""
    shown = 0  # 当前显示的建议行数

    def clear_suggestions() -> None:
        nonlocal shown
        if shown > 0:
            for _ in range(shown):
                sys.stdout.write("\x1b[B")   # 下移
                sys.stdout.write("\r\x1b[K")  # 清行
            sys.stdout.write(f"\x1b[{shown}A")
            shown = 0

    def draw_prompt() -> None:
        sys.stdout.write("\r\x1b[K")
        sys.stdout.write(f"\x1b[1;38;2;122;162;247m❯\x1b[0m {buf}")
        sys.stdout.flush()

    def show_suggestions() -> None:
        nonlocal shown
        clear_suggestions()

        matches = [
            (cmd, desc, cat)
            for cmd, desc, cat in SLASH_COMMANDS
            if cmd.startswith(buf)
        ]
        if not matches:
            draw_prompt()
            return

        rows = matches[:6]
        sys.stdout.write("\n")
        for i, (cmd, desc, _cat) in enumerate(rows):
            if i > 0:
                sys.stdout.write("\n")
            plen = len(buf)
            sys.stdout.write(
                f"\r  \x1b[38;2;122;162;247m{cmd[:plen]}\x1b[0m"
                f"\x1b[38;2;224;224;224m{cmd[plen:]}\x1b[0m"
                f"  \x1b[38;2;102;102;102m{desc}\x1b[0m"
            )
        shown = len(rows)
        sys.stdout.write(f"\x1b[{shown}A")
        sys.stdout.write("\r")
        draw_prompt()

    draw_prompt()

    while True:
        char = _read_char()
        if char is None:
            # termios 不可用，回退到行输入
            line = sys.stdin.readline()
            if not line:
                raise EOFError from None
            buf = line.rstrip("\n")
            clear_suggestions()
            sys.stdout.write("\n")
            sys.stdout.flush()
            return buf
        if char in ("\r", "\n"):
            clear_suggestions()
            sys.stdout.write("\n")
            sys.stdout.flush()
            return buf
        if char == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        if char == "\x04":  # Ctrl+D
            raise EOFError
        if char == "\x7f":  # Backspace
            if buf:
                buf = buf[:-1]
                if buf.startswith("/"):
                    show_suggestions()
                else:
                    clear_suggestions()
                    draw_prompt()
            continue
        if char == "\t":  # Tab
            completed = _tab_complete(buf)
            if completed != buf:
                buf = completed
                if buf.startswith("/"):
                    show_suggestions()
                else:
                    clear_suggestions()
                    draw_prompt()
            continue

        buf += char
        if buf.startswith("/"):
            show_suggestions()
        else:
            sys.stdout.write(char)
            sys.stdout.flush()


def _read_char() -> str | None:
    """读取单个字符（TTY 专用）。"""
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return ch
    except (ImportError, ValueError, OSError):
        return None


def _tab_complete(buf: str) -> str:
    """Tab 补全斜杠命令。"""
    if not buf.startswith("/"):
        return buf
    matches = [cmd for cmd, _, _ in SLASH_COMMANDS if cmd.startswith(buf)]
    if len(matches) == 1:
        return matches[0] + " "
    if matches:
        return os.path.commonprefix(matches)
    return buf


def _print_user_message(text: str) -> None:
    """打印用户消息 — 极简风格，无气泡框。"""
    console.print(f"[{C_USER}]你[/] {text}")


async def _run_chat(orchestrator: Orchestrator, user_input: str) -> None:
    """运行一轮群聊 — 流式输出 + Spinner。"""
    console.print()
    spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    spinner_idx = 0

    try:
        with Live(
            Text.from_markup(f"[{C_MUTED}]{spinner_chars[spinner_idx]} 思考中...[/]"),
            console=console,
            refresh_per_second=10,
            transient=True,
        ) as live:
            full_output = ""
            async for chunk in orchestrator.run(user_input, max_rounds=2):
                full_output += chunk
                spinner_idx = (spinner_idx + 1) % len(spinner_chars)
                live.update(
                    Text.from_markup(
                        f"[{C_MUTED}]{spinner_chars[spinner_idx]} 响应中...[/]",
                    )
                )

        # 流式结束后用 Markdown 渲染
        if full_output.strip():
            console.print(f"[{C_ACCENT}]●[/] ", end="")
            console.print(Markdown(full_output))
        else:
            console.print(f"[{C_WARNING}]● 无响应内容[/]")
    except Exception as e:
        console.print(f"[{C_ERROR}]✗ 错误: {e}[/]")
    console.print()


def _handle_slash(cmd: str, orchestrator: Orchestrator) -> bool:
    """处理斜杠命令。返回 True 表示退出。"""
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()

    if command in ("/exit", "/quit", "/q"):
        return True
    if command == "/help":
        _show_help()
    elif command == "/status":
        _show_status(orchestrator)
    elif command == "/providers":
        _show_providers(orchestrator)
    elif command == "/flatten":
        msg = asyncio.run(orchestrator.topology.flatten())
        console.print(f"  [{C_WARNING}]→[/] [{C_MUTED}]{msg}[/]")
    elif command == "/rebuild":
        msg = asyncio.run(orchestrator.topology.rebuild())
        console.print(f"  [{C_WARNING}]→[/] [{C_MUTED}]{msg}[/]")
    elif command == "/clear":
        os.system("clear" if os.name != "nt" else "cls")
        _print_header()
    else:
        console.print(f"  [{C_ERROR}]✗ 未知命令: {command}[/]")
        console.print(f"  [{C_MUTED}]输入 / 查看可用命令[/]")

    return False


def _show_status(orchestrator: Orchestrator) -> None:
    """显示状态 — 极简列表风格，无边框表格。"""
    console.print(f"\n  [{C_ACCENT}]Provider 状态[/]")
    console.print(f"  [{C_DIM}]{'─' * 48}[/]")

    for adapter in orchestrator.registry.all().values():
        name = adapter.config.name
        channel = adapter.channel_type.value
        quota = adapter.remaining_quota
        quota_str = f"{quota}" if quota >= 0 else "∞"
        priority = adapter.config.priority

        if quota == 0:
            q_color = C_ERROR
        elif 0 < quota < 100:
            q_color = C_WARNING
        else:
            q_color = C_SUCCESS

        console.print(
            f"  [{C_TEXT}]{name:<20}[/]"
            f"  [{C_MUTED}]{channel:<16}[/]"
            f"  [{q_color}]{quota_str:>8}[/]"
            f"  [{C_DIM}]P{priority}[/]"
        )

    console.print(f"  [{C_DIM}]{'─' * 48}[/]")
    console.print(
        f"  [{C_MUTED}]拓扑: [/][bold {C_ACCENT}]{orchestrator.topology.describe()}[/]\n"
    )


def _show_providers(orchestrator: Orchestrator) -> None:
    """列出 Provider — 极简列表风格。"""
    console.print(f"\n  [{C_ACCENT}]可用 Provider[/]")
    console.print(f"  [{C_DIM}]{'─' * 48}[/]")

    for adapter in orchestrator.registry.all().values():
        name = adapter.config.name
        model = adapter.config.model
        channel = adapter.channel_type.value
        tags = ", ".join(adapter.config.tags)

        console.print(
            f"  [{C_TEXT}]{name:<20}[/]"
            f"  [{C_MUTED}]{model:<20}[/]"
            f"  [{C_DIM}]{channel}[/]"
        )
        if tags:
            console.print(f"  [{C_DIM}]  tags: {tags}[/]")

    console.print()


def _show_help() -> None:
    """显示帮助 — 按分类分组，内联列表。"""
    console.print(f"\n  [{C_ACCENT}]命令列表[/]")
    console.print(f"  [{C_DIM}]{'─' * 48}[/]")

    last_cat = ""
    cat_labels = {"mode": "模式", "info": "信息", "util": "工具"}
    for cmd, desc, cat in SLASH_COMMANDS:
        if cat != last_cat:
            console.print(f"\n  [{C_MUTED}]  {cat_labels.get(cat, cat)}[/]")
            last_cat = cat
        console.print(f"  [{C_ACCENT}]{cmd:<14}[/] [{C_TEXT}]{desc}[/]")

    console.print()
