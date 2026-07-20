"""``multimind chat`` 命令 — 现代 TUI 风格交互界面。

设计参考 OpenCode / Codex CLI：
  - 背景色分层替代边框框线
  - 斜杠命令内联自动补全（输入 / 触发，继续输入过滤）
  - 符号前缀区分操作类型（→ 读、● 完成）
  - 极简深色配色，语义化色槽
  - 流式输出 + 实时状态指示
  - 运行时配置：/config /set /lang /apikey /model
  - 会话管理：/history /save /retry /clear
"""

from __future__ import annotations

import asyncio
import os
import select
import sys
from datetime import datetime

import typer
from rich.console import Console

from multimind.adapters.registry import init_default_providers
from multimind.config.settings import get_config_value, load_config, update_config
from multimind.core.constants import (
    APP_VERSION,
    CHAT_HISTORY_FILE,
    DEFAULT_CONFIG_PATH,
    HISTORY_DIR,
    INPUT_HISTORY_FILE,
)
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
    # 会话
    ("/history", "查看本轮对话历史", "session"),
    ("/import", "导入上次会话的对话历史", "session"),
    ("/save", "保存对话到文件", "session"),
    ("/retry", "重新发送上一条消息", "session"),
    ("/clear", "清屏并清空对话历史", "session"),
    # 配置
    ("/config", "查看当前配置", "config"),
    ("/set", "设置配置项（/set <key> <value>）", "config"),
    ("/lang", "切换语言（/lang zh|en）", "config"),
    ("/apikey", "设置 API Key（/apikey <provider> <key>）", "config"),
    ("/model", "切换默认 Provider（/model <name>）", "config"),
    # 模式
    ("/flatten", "切换为扁平模式（所有角色同层）", "mode"),
    ("/rebuild", "重建分层拓扑（Leader→Dispatcher→Executor）", "mode"),
    # 提示词
    ("/prompt", "查看/编辑/重置角色提示词", "prompt"),
    # 信息
    ("/status", "查看 Provider 额度和拓扑状态", "info"),
    ("/providers", "列出所有可用 Provider", "info"),
    ("/version", "查看版本信息", "info"),
    ("/help", "显示所有命令", "info"),
    # 退出
    ("/exit", "退出 MultiMind", "util"),
]

# ── 会话状态 ──────────────────────────────────────────────────────────
# 对话历史: [(role, content, timestamp), ...]
_chat_history: list[tuple[str, str, str]] = []
_last_input: str = ""
# 输入历史（bash 风格 Up/Down 导航）
_input_history: list[str] = []
_history_idx: int = -1  # -1 表示当前未在浏览历史


def _load_input_history() -> None:
    """从文件加载输入历史。"""
    global _input_history
    _input_history = []
    if INPUT_HISTORY_FILE.exists():
        try:
            _input_history = INPUT_HISTORY_FILE.read_text(
                encoding="utf-8"
            ).splitlines()
            # 去重：保留最后出现的（同一条命令只记最后一次）
            seen: set[str] = set()
            deduped: list[str] = []
            for line in reversed(_input_history):
                stripped = line.strip()
                if stripped and stripped not in seen:
                    seen.add(stripped)
                    deduped.append(stripped)
            _input_history = list(reversed(deduped))[-200:]  # 最多 200 条
        except OSError:
            pass


def _save_input_history(entry: str) -> None:
    """保存一条输入到历史文件。"""
    global _input_history
    entry = entry.strip()
    if not entry:
        return
    _input_history.append(entry)
    # 限制内存中 200 条
    if len(_input_history) > 200:
        _input_history = _input_history[-200:]
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(INPUT_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except OSError:
        pass


def _save_chat_history() -> None:
    """保存当前会话对话历史到 JSON 文件。"""
    if not _chat_history:
        return
    import json

    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "messages": [
                {"role": r, "content": c, "time": t}
                for r, c, t in _chat_history
            ],
        }
        CHAT_HISTORY_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, ValueError):
        pass


def _load_last_chat() -> dict | None:
    """加载上次会话的对话历史。"""
    import json

    if not CHAT_HISTORY_FILE.exists():
        return None
    try:
        data = json.loads(CHAT_HISTORY_FILE.read_text(encoding="utf-8"))
        return data
    except (OSError, ValueError, json.JSONDecodeError):
        return None


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
    cfg = load_config()
    orchestrator = Orchestrator(language=cfg.language)

    if flatten:
        asyncio.run(orchestrator.topology.flatten())

    if message:
        _run_headless(orchestrator, message)
    else:
        _interactive(orchestrator)


def _run_headless(orchestrator: Orchestrator, message: str) -> None:
    """非交互模式：Headless 流式输出。"""

    async def _run() -> None:
        from multimind.engine.orchestrator import OrchestratorEvent

        async for event in orchestrator.run(message, max_rounds=2):
            if event.event_type == OrchestratorEvent.ROLE_CHUNK:
                console.print(event.content, end="")
            elif event.event_type == OrchestratorEvent.ROUND_END:
                console.print()

    asyncio.run(_run())


# ═══════════════════════════════════════════════════════════════════════
# 现代交互界面
# ═══════════════════════════════════════════════════════════════════════


def _interactive(orchestrator: Orchestrator) -> None:
    """现代交互式群聊 — OpenCode/Codex 风格。"""
    global _last_input
    # 加载输入历史
    _load_input_history()
    _print_header()
    _show_last_session_reminder()
    _print_footer_hint()

    while True:
        try:
            user_input = _read_input()
        except (EOFError, KeyboardInterrupt):
            console.print(f"\n[{C_MUTED}]再见[/]")
            _save_chat_history()
            break

        if not user_input:
            continue

        # 保存到输入历史
        _save_input_history(user_input)

        # 斜杠命令
        if user_input.startswith("/"):
            if _handle_slash(user_input, orchestrator):
                break
            continue

        # 普通消息
        _last_input = user_input
        _print_user_message(user_input)
        _chat_history.append(("user", user_input, datetime.now().strftime("%H:%M:%S")))
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
        f"[{C_DIM}]  / 命令  ·  Tab 补全  ·  ↑↓ 历史  ·  Ctrl+C 退出[/]\n"
    )


def _show_last_session_reminder() -> None:
    """启动时显示上次会话提醒。"""
    last = _load_last_chat()
    if not last:
        return

    saved_at = last.get("saved_at", "未知时间")
    messages = last.get("messages", [])
    if not messages:
        return

    # 找到最后一条用户消息
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "")
            break

    console.print(
        f"[{C_DIM}]上次对话: {saved_at} "
        f"({len(messages)} 条消息)[/]"
    )
    if last_user_msg:
        preview = last_user_msg[:60].replace("\n", " ")
        if len(last_user_msg) > 60:
            preview += "..."
        console.print(f"[{C_DIM}]  最后: {preview}[/]")
    console.print(
        f"[{C_DIM}]  /history 查看本次  ·  /import 导入上次对话[/]\n"
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
    nav_idx = -1  # 输入历史导航索引，-1 表示当前未在浏览历史
    saved_buf = ""  # 浏览历史前保存的当前输入

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

    def navigate_history(direction: str) -> None:
        """浏览输入历史（Up=向前/更早, Down=向后/更新）。"""
        nonlocal buf, nav_idx, saved_buf
        if not _input_history:
            return

        if direction == "up":
            if nav_idx == -1:
                # 首次按 Up，保存当前输入
                saved_buf = buf
                nav_idx = len(_input_history) - 1
            elif nav_idx > 0:
                nav_idx -= 1
            else:
                return  # 已到最早
        else:  # down
            if nav_idx == -1:
                return  # 不在浏览历史
            elif nav_idx < len(_input_history) - 1:
                nav_idx += 1
            else:
                # 回到当前输入
                nav_idx = -1
                buf = saved_buf
                clear_suggestions()
                draw_prompt()
                return

        buf = _input_history[nav_idx]
        clear_suggestions()
        if buf.startswith("/"):
            show_suggestions()
        else:
            draw_prompt()

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

        # 转义序列处理（方向键等）
        if char == "\x1b":
            seq2 = _read_char()
            if seq2 == "[":
                seq3 = _read_char()
                if seq3 == "A":  # ↑ 上箭头 — 历史导航
                    navigate_history("up")
                    continue
                if seq3 == "B":  # ↓ 下箭头 — 历史导航
                    navigate_history("down")
                    continue
                # 其他方向键（C=右, D=左）暂不处理
                continue
            # 单独 ESC — 清除当前输入
            if seq2 is None:
                buf = ""
                clear_suggestions()
                draw_prompt()
                continue
            continue

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
                nav_idx = -1  # 编辑时退出历史浏览
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
                nav_idx = -1
                if buf.startswith("/"):
                    show_suggestions()
                else:
                    clear_suggestions()
                    draw_prompt()
            continue

        # 任何新字符输入都退出历史浏览
        nav_idx = -1
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


# ═══════════════════════════════════════════════════════════════════════
# 通用方向键选择器
# ═══════════════════════════════════════════════════════════════════════


def _interactive_select(
    title: str,
    options: list[tuple[str, str]],
    hint: str = "↑↓ 选择 · Enter 确认 · Esc 取消",
) -> str | None:
    """通用方向键选择器。

    Args:
        title: 选择器标题。
        options: 选项列表，每项为 (label, value) 元组。
            label 用于显示，value 为返回值。
        hint: 底部提示文字。

    Returns:
        选中的 value，取消则返回 None。

    Note:
        一次性进入 raw 模式读取按键，避免 tty 在 raw/cooked 之间反复
        切换导致转义序列被回显；用 ``select`` 超时区分单独 ESC 与方向键
        转义序列，重绘时完整重画整块（含标题与提示）避免残留光标。
    """
    if not options:
        console.print(f"  [{C_WARNING}]● 没有可选项[/]\n")
        return None

    # 非 TTY 环境回退到数字选择
    if not sys.stdin.isatty():
        console.print(f"\n  [{C_ACCENT}]{title}[/]")
        console.print(f"  [{C_DIM}]{'─' * 48}[/]")
        for i, (label, _) in enumerate(options, 1):
            console.print(f"  [{C_MUTED}]{i}.[/] [{C_TEXT}]{label}[/]")
        console.print()
        try:
            choice = input(f"  选择 (1-{len(options)}): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx][1]
        except (ValueError, EOFError):
            pass
        return None

    count = len(options)
    selected = 0
    total_lines = count + 2  # 标题 + 选项 + 提示

    # 尝试一次性进入 raw 模式；失败（如 Windows）则降级处理
    fd = sys.stdin.fileno()
    try:
        import termios
        import tty

        old_attr = termios.tcgetattr(fd)
        tty.setraw(fd)
        raw = True
    except (ImportError, ValueError, OSError):
        old_attr = None
        raw = False

    def restore_term() -> None:
        """恢复终端到进入选择器前的模式。"""
        if old_attr is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_attr)
            except (ValueError, OSError):
                pass

    def emit_block() -> None:
        """在「当前行 = 标题行」处完整重画整块（含标题与提示）。"""
        sys.stdout.write("\r\x1b[K")
        sys.stdout.write(f"\x1b[1;38;2;122;162;247m{title}\x1b[0m\n")
        for i, (label, _value) in enumerate(options):
            sys.stdout.write("\r\x1b[K")
            if i == selected:
                sys.stdout.write(f"  \x1b[1;38;2;122;162;247m▶ {label}\x1b[0m\n")
            else:
                sys.stdout.write(f"  \x1b[38;2;102;102;102m  {label}\x1b[0m\n")
        sys.stdout.write("\r\x1b[K")
        sys.stdout.write(f"\x1b[38;2;68;68;68m  {hint}\x1b[0m")
        sys.stdout.flush()

    def redraw() -> None:
        """回到标题行并重画整块。"""
        if raw:
            sys.stdout.write(f"\x1b[{total_lines}A")
        emit_block()

    def clear_block() -> None:
        """清除整块选择区域。"""
        if raw:
            sys.stdout.write(f"\x1b[{total_lines}A")
            for _ in range(total_lines):
                sys.stdout.write("\r\x1b[K\n")
            sys.stdout.write(f"\x1b[{total_lines}A")
            sys.stdout.flush()

    def read_key() -> str | None:
        """读取单个按键，区分 ESC 与方向键。

        Returns:
            语义化按键名（"esc"/"up"/"down"/"left"/"right"）、
            原始单字符、或 None（EOF）。
        """
        if raw:
            ch = os.read(fd, 1)
            if not ch:
                return None
            if ch == b"\x1b":
                # 等待后续字节，区分单独 ESC 与转义序列（如方向键）
                rlist, _, _ = select.select([fd], [], [], 0.15)
                if not rlist:
                    return "esc"
                # 只读取紧随其后的「[」与最终字节，绝不吞噬后续按键
                b2 = os.read(fd, 1)
                if b2 == b"[":
                    r3, _, _ = select.select([fd], [], [], 0.05)
                    if not r3:
                        return "esc"
                    b3 = os.read(fd, 1)
                    return {
                        b"A": "up",
                        b"B": "down",
                        b"C": "left",
                        b"D": "right",
                    }.get(b3, "esc")
                # Alt+组合键或其他转义，按 ESC 处理
                return "esc"
            return ch.decode("utf-8", errors="replace")

        # 降级：使用逐字符读取（无 select 超时，ESC 无法可靠取消）
        char = _read_char()
        if char is None:
            return None
        if char == "\x1b":
            seq2 = _read_char()
            if seq2 == "[":
                seq3 = _read_char()
                return {"A": "up", "B": "down", "C": "left", "D": "right"}.get(
                    seq3 or "", None
                )
            return "esc"
        return char

    try:
        emit_block()  # 首次绘制（当前行即标题行）
        while True:
            key = read_key()
            if key is None:
                clear_block()
                restore_term()
                return None

            if key == "up":
                selected = (selected - 1) % count
                redraw()
            elif key == "down":
                selected = (selected + 1) % count
                redraw()
            elif key == "esc":
                clear_block()
                console.print(f"  [{C_MUTED}]已取消[/]\n")
                restore_term()
                return None
            elif key in ("\r", "\n"):
                clear_block()
                restore_term()
                return options[selected][1]
            elif key == "\x03":  # Ctrl+C
                restore_term()
                raise KeyboardInterrupt
            elif key == "\x04":  # Ctrl+D
                clear_block()
                restore_term()
                return None
            elif key == "q":
                clear_block()
                console.print(f"  [{C_MUTED}]已取消[/]\n")
                restore_term()
                return None
            elif key.isdigit():
                idx = int(key) - 1
                if 0 <= idx < count:
                    selected = idx
                    redraw()
            # 其他按键（left/right 等）忽略
    except KeyboardInterrupt:
        restore_term()
        raise


def _print_user_message(text: str) -> None:
    """打印用户消息 — 极简风格，无气泡框。"""
    console.print(f"[{C_USER}]❯[/] {text}")


# 角色层级的显示标签
_TIER_LABELS = {
    "leader": ("◆", C_ACCENT, "Leader"),
    "dispatcher": ("◇", C_WARNING, "Dispatcher"),
    "executor": ("▪", C_SUCCESS, "Executor"),
}


async def _run_chat(orchestrator: Orchestrator, user_input: str) -> None:
    """运行一轮群聊 — 结构化事件流 + 美化过程展示。"""
    from multimind.engine.orchestrator import OrchestratorEvent

    spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    try:
        current_role = ""
        current_tier = ""
        current_provider = ""
        role_output = ""
        role_count = 0
        round_num = 0
        spinner_idx = 0

        async for event in orchestrator.run(user_input, max_rounds=2):
            if event.event_type == OrchestratorEvent.ROLE_START:
                role_count += 1
                current_role = event.role_name
                current_tier = event.role_tier
                current_provider = event.provider
                round_num = event.round_num
                role_output = ""

                # 角色标签行
                symbol, color, _ = _TIER_LABELS.get(
                    current_tier, ("●", C_TEXT, current_tier)
                )
                console.print(
                    f"  [{color}]{symbol}[/] "
                    f"[bold {color}]{current_role}[/]"
                    f"  [{C_DIM}]via {current_provider}[/]"
                )
                # 思考中提示
                spinner_idx = 0
                console.print(
                    f"  [{C_MUTED}]{spinner_chars[spinner_idx]} thinking...[/]",
                    end="\r",
                )

            elif event.event_type == OrchestratorEvent.ROLE_CHUNK:
                role_output += event.content
                spinner_idx = (spinner_idx + 1) % len(spinner_chars)
                # 清除 thinking 行，显示实际输出
                sys.stdout.write("\r\x1b[K")
                sys.stdout.write(event.content)
                sys.stdout.flush()

            elif event.event_type == OrchestratorEvent.ROLE_END:
                if role_output.strip():
                    console.print()  # 换行
                    _chat_history.append(
                        (current_role, role_output.strip(),
                         datetime.now().strftime("%H:%M:%S"))
                    )

            elif event.event_type == OrchestratorEvent.ROUND_END:
                round_num = event.round_num

            elif event.event_type == OrchestratorEvent.ERROR:
                sys.stdout.write("\r\x1b[K")
                console.print(f"  [{C_ERROR}]✗ {event.content}[/]")

        # 轮次总结
        if role_count > 0:
            console.print(f"  [{C_DIM}]{'─' * 48}[/]")
            console.print(
                f"  [{C_SUCCESS}]✓[/] "
                f"[{C_MUTED}]{role_count} role(s) responded · "
                f"{round_num} round(s)[/]"
            )

    except Exception as e:
        console.print(f"\n  [{C_ERROR}]✗ Error: {e}[/]")
    console.print()


def _handle_slash(cmd: str, orchestrator: Orchestrator) -> bool:
    """处理斜杠命令。返回 True 表示退出。"""
    global _last_input, _chat_history
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    # 退出
    if command in ("/exit", "/quit", "/q"):
        return True

    # 帮助
    if command == "/help":
        _show_help()

    # 信息
    elif command == "/status":
        _show_status(orchestrator)
    elif command == "/providers":
        _show_providers(orchestrator)
    elif command == "/version":
        _show_version()

    # 模式
    elif command == "/flatten":
        msg = asyncio.run(orchestrator.topology.flatten())
        console.print(f"  [{C_WARNING}]→[/] [{C_MUTED}]{msg}[/]")
    elif command == "/rebuild":
        msg = asyncio.run(orchestrator.topology.rebuild())
        console.print(f"  [{C_WARNING}]→[/] [{C_MUTED}]{msg}[/]")

    # 提示词
    elif command == "/prompt":
        _handle_prompt(args, orchestrator)

    # 会话
    elif command == "/clear":
        os.system("clear" if os.name != "nt" else "cls")
        _chat_history.clear()
        _last_input = ""
        _print_header()
    elif command == "/history":
        _show_history()
    elif command == "/import":
        _import_last_session()
    elif command == "/save":
        _save_conversation(args)
    elif command == "/retry":
        if not _last_input:
            console.print(f"  [{C_WARNING}]● 没有上一条消息可重试[/]")
        else:
            console.print(f"  [{C_MUTED}]→ 重新发送: {_last_input}[/]")
            _print_user_message(_last_input)
            asyncio.run(_run_chat(orchestrator, _last_input))

    # 配置
    elif command == "/config":
        _show_config()
    elif command == "/set":
        _handle_set(args)
    elif command == "/lang":
        _handle_lang(args)
    elif command == "/apikey":
        _handle_apikey(args)
    elif command == "/model":
        _handle_model(args, orchestrator)

    else:
        console.print(f"  [{C_ERROR}]✗ 未知命令: {command}[/]")
        console.print(f"  [{C_MUTED}]输入 / 查看可用命令[/]")

    return False


# ═══════════════════════════════════════════════════════════════════════
# 信息命令
# ═══════════════════════════════════════════════════════════════════════


def _show_version() -> None:
    """显示版本信息。"""
    console.print(f"\n  [{C_ACCENT}]MultiMind[/] [{C_MUTED}]v{APP_VERSION}[/]")
    console.print(f"  [{C_DIM}]{'─' * 48}[/]")
    console.print(f"  [{C_TEXT}]配置文件: [/][{C_MUTED}]{DEFAULT_CONFIG_PATH}[/]")
    cfg = load_config()
    console.print(f"  [{C_TEXT}]语言: [/][{C_MUTED}]{cfg.language}[/]")
    console.print(f"  [{C_TEXT}]拓扑: [/][{C_MUTED}]{cfg.topology}[/]")
    console.print(f"  [{C_TEXT}]Provider 数: [/][{C_MUTED}]{len(cfg.providers)}[/]")
    console.print()


def _show_status(orchestrator: Orchestrator) -> None:
    """显示状态 — 极简列表风格，无边框表格。"""
    console.print(f"\n  [{C_ACCENT}]Provider 状态[/]")
    console.print(f"  [{C_DIM}]{'─' * 48}[/]")

    for adapter in orchestrator.registry.all().values():
        name = adapter.config.name
        channel = adapter.channel_type.value
        daily = adapter.config.daily_quota
        remaining = adapter.remaining_quota
        priority = adapter.config.priority

        if daily < 0:
            quota_str = "∞"
            q_color = C_SUCCESS
        elif remaining == 0:
            quota_str = "0"
            q_color = C_ERROR
        elif remaining < 100:
            quota_str = f"{remaining}"
            q_color = C_WARNING
        else:
            quota_str = f"{remaining}"
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


# ═══════════════════════════════════════════════════════════════════════
# 会话命令
# ═══════════════════════════════════════════════════════════════════════


def _show_history() -> None:
    """显示本轮对话历史。"""
    if not _chat_history:
        console.print(f"\n  [{C_MUTED}]暂无对话历史[/]\n")
        return

    console.print(f"\n  [{C_ACCENT}]对话历史[/] [{C_DIM}]({len(_chat_history)} 条)[/]")
    console.print(f"  [{C_DIM}]{'─' * 48}[/]")

    for role, content, ts in _chat_history:
        label = f"[{C_USER}]你[/]" if role == "user" else f"[{C_ACCENT}]AI[/]"

        # 截取前 80 字符预览
        preview = content[:80].replace("\n", " ")
        if len(content) > 80:
            preview += "..."
        console.print(f"  [{C_DIM}]{ts}[/] {label} {preview}")

    console.print()


def _import_last_session() -> None:
    """导入上次会话的对话历史到当前会话。"""
    global _chat_history
    last = _load_last_chat()
    if not last:
        console.print(f"\n  [{C_WARNING}]● 没有上次会话记录可导入[/]\n")
        return

    messages = last.get("messages", [])
    if not messages:
        console.print(f"\n  [{C_WARNING}]● 上次会话没有消息[/]\n")
        return

    saved_at = last.get("saved_at", "未知时间")

    # 如果当前已有历史，先提示
    if _chat_history:
        console.print(f"\n  [{C_WARNING}]当前已有 {len(_chat_history)} 条消息[/]")
        console.print(f"  [{C_MUTED}]导入将追加到当前历史之后[/]")

    imported = 0
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        ts = msg.get("time", "")
        if content:
            _chat_history.append((role, content, ts))
            imported += 1

    console.print(f"  [{C_SUCCESS}]● 已导入 {imported} 条消息（来自 {saved_at}）[/]")
    console.print(f"  [{C_DIM}]  当前共 {len(_chat_history)} 条消息，/history 查看[/]\n")


def _save_conversation(args: str) -> None:
    """保存对话到文件。"""
    if not _chat_history:
        console.print(f"\n  [{C_WARNING}]● 没有对话内容可保存[/]\n")
        return

    # 确定保存路径
    if args:
        filepath = args.strip()
    else:
        cfg = load_config()
        output_dir = cfg.output_dir or str(DEFAULT_CONFIG_PATH.parent / "output")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"{output_dir}/chat_{ts}.md"

    try:
        from pathlib import Path

        path = Path(filepath).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = ["# MultiMind 对话记录\n"]
        lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append(f"消息数: {len(_chat_history)}\n\n---\n")

        for role, content, ts in _chat_history:
            speaker = "你" if role == "user" else "AI"
            lines.append(f"\n### [{ts}] {speaker}\n\n{content}\n")

        path.write_text("\n".join(lines), encoding="utf-8")
        console.print(f"  [{C_SUCCESS}]● 已保存到: {path}[/]\n")
    except Exception as e:
        console.print(f"  [{C_ERROR}]✗ 保存失败: {e}[/]\n")


# ═══════════════════════════════════════════════════════════════════════
# 配置命令
# ═══════════════════════════════════════════════════════════════════════


def _show_config() -> None:
    """显示当前配置。"""
    cfg = load_config()

    console.print(f"\n  [{C_ACCENT}]当前配置[/]")
    console.print(f"  [{C_DIM}]{'─' * 48}[/]")

    config_items = [
        ("语言", cfg.language, "language"),
        ("拓扑模式", cfg.topology, "topology"),
        ("默认Provider", cfg.default_provider or "(未设置)", "default_provider"),
        ("工具权限", cfg.tool_permission, "tool_permission"),
        ("自动Commit", str(cfg.auto_commit), "auto_commit"),
        ("输出目录", cfg.output_dir or "(默认)", "output_dir"),
        ("日志级别", cfg.log_level, "log_level"),
    ]

    for label, value, key in config_items:
        console.print(
            f"  [{C_TEXT}]{label:<14}[/]"
            f"  [{C_MUTED}]{value}[/]"
            f"  [{C_DIM}]  ({key})[/]"
        )

    # API Keys
    api_keys = get_config_value("api_keys") or {}
    if api_keys:
        console.print(f"\n  [{C_MUTED}]API Keys:[/]")
        for provider, key in api_keys.items():
            masked = key[:4] + "****" if len(key) > 4 else "****"
            console.print(f"  [{C_TEXT}]  {provider:<12}[/] [{C_DIM}]{masked}[/]")
    else:
        console.print(f"\n  [{C_DIM}]API Keys: (无)[/]")

    console.print(f"\n  [{C_DIM}]配置文件: {DEFAULT_CONFIG_PATH}[/]")
    console.print(f"  [{C_DIM}]用法: /set <key> <value>[/]\n")


def _handle_set(args: str) -> None:
    """处理 /set 命令 — 无参数时弹出方向键选择配置项。"""
    # 可设置项及其描述
    settable = [
        ("language — 语言 (zh/en)", "language"),
        ("topology — 拓扑模式 (layered/flat/hybrid)", "topology"),
        ("default_provider — 默认 Provider", "default_provider"),
        ("tool_permission — 工具权限 (none/ask/auto/all)", "tool_permission"),
        ("auto_commit — 自动提交 (true/false)", "auto_commit"),
        ("output_dir — 输出目录", "output_dir"),
        ("log_level — 日志级别 (DEBUG/INFO/WARNING/ERROR)", "log_level"),
        ("api_key — API Key (provider key)", "api_key"),
    ]

    if not args:
        selected = _interactive_select("选择要修改的配置项", settable)
        if selected is None:
            return

        # 特殊处理某些 key 的值选择
        if selected == "language":
            cfg = load_config()
            value = _interactive_select(
                f"选择语言（当前: {cfg.language}）",
                [("中文 (zh)", "zh"), ("English (en)", "en")],
            )
            if value is None:
                return
        elif selected == "topology":
            cfg = load_config()
            value = _interactive_select(
                f"选择拓扑（当前: {cfg.topology}）",
                [
                    ("分层 (layered)", "layered"),
                    ("扁平 (flat)", "flat"),
                    ("混合 (hybrid)", "hybrid"),
                ],
            )
            if value is None:
                return
        elif selected == "tool_permission":
            cfg = load_config()
            value = _interactive_select(
                f"选择权限（当前: {cfg.tool_permission}）",
                [
                    ("none — 无工具", "none"),
                    ("ask — 每次询问", "ask"),
                    ("auto — 自动执行", "auto"),
                    ("all — 全部自动", "all"),
                ],
            )
            if value is None:
                return
        elif selected == "auto_commit":
            cfg = load_config()
            value = _interactive_select(
                f"自动提交（当前: {cfg.auto_commit}）",
                [("开启 (true)", "true"), ("关闭 (false)", "false")],
            )
            if value is None:
                return
        else:
            # 需要手动输入值
            console.print(f"  [{C_MUTED}]请输入 {selected} 的值:[/] ", end="")
            try:
                value = input().strip()
            except EOFError:
                return
            if not value:
                console.print(f"  [{C_MUTED}]已取消[/]\n")
                return

        result = update_config(selected, value)
        console.print(f"  [{C_SUCCESS}]● {result}[/]")
        console.print(f"  [{C_DIM}]  重启后生效[/]\n")
        return

    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        console.print(f"  [{C_ERROR}]✗ 用法: /set <key> <value>[/]")
        console.print(f"  [{C_MUTED}]例如: /set language en[/]\n")
        return

    key, value = parts
    result = update_config(key, value)
    console.print(f"  [{C_SUCCESS}]● {result}[/]")
    console.print(f"  [{C_DIM}]  重启后生效，或使用对应命令即时切换[/]\n")


def _handle_lang(args: str) -> None:
    """快速切换语言 — 无参数时弹出方向键选择器。"""
    if not args:
        # 弹出选择器
        cfg = load_config()
        options = [
            ("中文 (zh)", "zh"),
            ("English (en)", "en"),
        ]
        selected = _interactive_select(
            f"选择语言（当前: {cfg.language}）",
            options,
        )
        if selected is None:
            return
        lang = selected
    else:
        lang = args.strip()
        if lang not in ("zh", "en"):
            console.print(f"  [{C_ERROR}]✗ 无效语言: {lang}[/]")
            console.print(f"  [{C_MUTED}]可选: zh, en[/]\n")
            return

    result = update_config("language", lang)
    console.print(f"  [{C_SUCCESS}]● {result}[/]")
    if lang == "en":
        console.print(f"  [{C_DIM}]  Language switched to English. Restart to apply.[/]\n")
    else:
        console.print(f"  [{C_DIM}]  语言已切换为中文，重启后生效。[/]\n")


def _handle_apikey(args: str) -> None:
    """设置 API Key。"""
    if not args:
        api_keys = get_config_value("api_keys") or {}
        console.print(f"\n  [{C_ACCENT}]API Key 管理[/]")
        console.print(f"  [{C_DIM}]{'─' * 48}[/]")
        if api_keys:
            for provider, key in api_keys.items():
                masked = key[:4] + "****" if len(key) > 4 else "****"
                console.print(f"  [{C_TEXT}]{provider:<16}[/] [{C_DIM}]{masked}[/]")
        else:
            console.print(f"  [{C_MUTED}]  (无已配置的 API Key)[/]")
        console.print(f"\n  [{C_DIM}]用法: /apikey <provider> <key>[/]")
        console.print(f"  [{C_DIM}]例如: /apikey groq gsk_xxxxxxxx[/]\n")
        return

    # /apikey provider key
    result = update_config("api_key", args)
    console.print(f"  [{C_SUCCESS}]● {result}[/]")
    console.print(f"  [{C_DIM}]  重启后生效，或设置环境变量: export GROQ_API_KEY=xxx[/]\n")


def _handle_model(args: str, orchestrator: Orchestrator) -> None:
    """切换默认 Provider — 无参数时弹出方向键选择器。"""
    if not args:
        # 构建选项列表
        providers = orchestrator.registry.all()
        if not providers:
            console.print(f"  [{C_WARNING}]● 没有可用 Provider[/]\n")
            return

        cfg = load_config()
        current = cfg.default_provider or ""
        options = [
            (f"{name}  [{adapter.config.model}]", name)
            for name, adapter in providers.items()
        ]
        selected = _interactive_select(
            f"选择默认 Provider（当前: {current or '未设置'}）",
            options,
        )
        if selected is None:
            return
        provider_name = selected
    else:
        provider_name = args.strip()
        # 检查是否已注册
        if provider_name not in orchestrator.registry.all():
            console.print(f"  [{C_ERROR}]✗ 未找到 Provider: {provider_name}[/]")
            console.print(f"  [{C_MUTED}]输入 /model 查看可用 Provider[/]\n")
            return

    result = update_config("default_provider", provider_name)
    console.print(f"  [{C_SUCCESS}]● {result}[/]")
    console.print(f"  [{C_DIM}]  重启后生效[/]\n")


# ═══════════════════════════════════════════════════════════════════════
# 提示词命令
# ═══════════════════════════════════════════════════════════════════════

# 角色 tier 的中文标签
_TIER_ZH: dict[str, str] = {
    "leader": "指挥官 (Leader)",
    "dispatcher": "调度员 (Dispatcher)",
    "executor": "执行者 (Executor)",
}


def _handle_prompt(args: str, orchestrator: Orchestrator) -> None:
    """处理 /prompt 命令 — 查看/编辑/重置角色提示词。

    用法:
      /prompt              — 方向键选择角色查看
      /prompt <tier>       — 查看指定角色的完整提示词
      /prompt edit [tier]  — 用 $EDITOR 编辑（可方向键选择）
      /prompt reset [tier] — 重置为内置默认（可方向键选择）
    """
    parts = args.split() if args else []

    # 构建角色选项（共享）
    tier_options = [(label, tier) for tier, label in _TIER_ZH.items()]

    # /prompt — 方向键选择角色
    if not parts:
        selected = _interactive_select("选择角色查看提示词", tier_options)
        if selected is None:
            return
        _show_single_prompt(selected)
        return

    # /prompt edit [tier]
    if parts[0] == "edit":
        if len(parts) >= 2:
            tier = parts[1].lower()
            if tier not in _TIER_ZH:
                console.print(f"  [{C_ERROR}]✗ 未知角色: {tier}[/]")
                console.print(f"  [{C_MUTED}]可选: leader, dispatcher, executor[/]\n")
                return
        else:
            # 无 tier 参数，弹出选择器
            selected = _interactive_select("选择角色编辑提示词", tier_options)
            if selected is None:
                return
            tier = selected
        _edit_prompt(tier)
        return

    # /prompt reset [tier]
    if parts[0] == "reset":
        from multimind.engine.roles import reset_custom_prompt

        if len(parts) >= 2:
            tier = parts[1].lower()
            if tier not in _TIER_ZH:
                console.print(f"  [{C_ERROR}]✗ 未知角色: {tier}[/]")
                console.print(f"  [{C_MUTED}]可选: leader, dispatcher, executor[/]\n")
                return
        else:
            # 无 tier 参数，弹出选择器
            selected = _interactive_select("选择角色重置提示词", tier_options)
            if selected is None:
                return
            tier = selected

        deleted = reset_custom_prompt(tier)
        if deleted:
            console.print(f"  [{C_SUCCESS}]● 已重置 {_TIER_ZH[tier]} 的提示词为内置默认[/]")
        else:
            console.print(f"  [{C_MUTED}]● {_TIER_ZH[tier]} 本就在使用内置默认[/]")
        console.print(f"  [{C_DIM}]  重启后生效[/]\n")
        return

    # /prompt <tier> — 查看指定角色
    tier = parts[0].lower()
    if tier not in _TIER_ZH:
        console.print(f"\n  [{C_ERROR}]✗ 未知角色: {tier}[/]")
        console.print(f"  [{C_MUTED}]可选: leader, dispatcher, executor[/]")
        console.print(f"  [{C_DIM}]用法: /prompt [edit|reset] <tier>[/]\n")
        return

    _show_single_prompt(tier)


def _show_single_prompt(tier: str) -> None:
    """显示单个角色的完整提示词。"""
    from multimind.engine.roles import get_effective_prompt, is_custom

    label = _TIER_ZH[tier]
    prompt = get_effective_prompt(tier)  # type: ignore[arg-type]
    custom = is_custom(tier)  # type: ignore[arg-type]
    status = f"[{C_WARNING}]自定义[/]" if custom else f"[{C_DIM}]默认[/]"

    console.print(f"\n  [{C_ACCENT}]{label}[/] {status}")
    console.print(f"  [{C_DIM}]{'─' * 48}[/]")
    console.print(f"  [{C_TEXT}]{prompt}[/]")
    console.print(f"\n  [{C_DIM}]编辑: /prompt edit {tier}  ·  重置: /prompt reset {tier}[/]\n")


def _edit_prompt(tier: str) -> None:
    """用 $EDITOR 编辑角色提示词，预填充当前内容。"""
    import contextlib
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from multimind.engine.roles import (
        get_effective_prompt,
        reset_custom_prompt,
        save_custom_prompt,
    )

    current = get_effective_prompt(tier)  # type: ignore[arg-type]
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")

    if not editor:
        # 无 EDITOR，尝试常见编辑器
        for candidate in ("vim", "nano", "vi", "micro"):
            if shutil.which(candidate):
                editor = candidate
                break

    if not editor:
        console.print(f"  [{C_ERROR}]✗ 未找到编辑器[/]")
        console.print(f"  [{C_MUTED}]设置环境变量: export EDITOR=vim[/]")
        console.print(f"  [{C_DIM}]或直接编辑文件: ~/.multimind/prompts/{tier}.md[/]\n")
        return

    # 写入临时文件，预填充当前提示词
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(f"# 编辑 {tier} 提示词 — 保存退出即可应用\n")
        f.write("# 删除全部内容（只留注释）将恢复默认\n\n")
        f.write(current + "\n")
        tmp_path = f.name

    console.print(f"  [{C_MUTED}]正在打开 {editor} 编辑 {tier} 提示词...[/]")

    try:
        result = subprocess.run([editor, tmp_path], check=False)
        if result.returncode != 0:
            console.print(f"  [{C_WARNING}]● 编辑器退出码非零，未保存[/]\n")
            return
    except FileNotFoundError:
        console.print(f"  [{C_ERROR}]✗ 编辑器未找到: {editor}[/]\n")
        return

    # 读取编辑后的内容
    content = Path(tmp_path).read_text(encoding="utf-8")

    # 清理临时文件
    with contextlib.suppress(OSError):
        Path(tmp_path).unlink()

    # 过滤注释行和空行
    lines = [
        line for line in content.splitlines()
        if not line.strip().startswith("#") and line.strip()
    ]
    cleaned = "\n".join(lines).strip()

    if not cleaned:
        # 内容为空 → 重置为默认
        reset_custom_prompt(tier)  # type: ignore[arg-type]
        console.print(f"  [{C_SUCCESS}]● 内容为空，已重置为默认[/]\n")
        return

    # 检查是否有变化
    if cleaned == current:
        console.print(f"  [{C_MUTED}]● 提示词未变化[/]\n")
        return

    # 保存
    save_custom_prompt(tier, cleaned)  # type: ignore[arg-type]
    console.print(f"  [{C_SUCCESS}]● 已保存自定义提示词[/]")
    console.print(f"  [{C_DIM}]  文件: ~/.multimind/prompts/{tier}.md[/]")
    console.print(f"  [{C_DIM}]  重启后生效，或 /prompt reset {tier} 恢复默认[/]\n")


# ═══════════════════════════════════════════════════════════════════════
# 帮助
# ═══════════════════════════════════════════════════════════════════════


def _show_help() -> None:
    """显示帮助 — 按分类分组，内联列表。"""
    console.print(f"\n  [{C_ACCENT}]命令列表[/]")
    console.print(f"  [{C_DIM}]{'─' * 48}[/]")

    cat_labels = {
        "session": "会话",
        "config": "配置",
        "mode": "模式",
        "prompt": "提示词",
        "info": "信息",
        "util": "工具",
    }
    last_cat = ""
    for cmd, desc, cat in SLASH_COMMANDS:
        if cat != last_cat:
            console.print(f"\n  [{C_MUTED}]  {cat_labels.get(cat, cat)}[/]")
            last_cat = cat
        console.print(f"  [{C_ACCENT}]{cmd:<14}[/] [{C_TEXT}]{desc}[/]")

    console.print()
