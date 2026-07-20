"""TUI 主应用 — 三栏布局 · 方向键导航 · 群聊气泡。

使用 Textual 框架实现类 GUI 终端界面。
"""

from __future__ import annotations

import asyncio
import logging

try:
    from textual import on
    from textual.app import App, ComposeResult
    from textual.containers import Container
    from textual.widgets import Footer, Header, Input, RichLog, Static, Tree

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from multimind.adapters.registry import init_default_providers
from multimind.engine import Orchestrator

__all__ = ["run_tui", "TEXTUAL_AVAILABLE", "MultiMindTUI"]

logger = logging.getLogger(__name__)

# 角色颜色（按层级配色）
TIER_COLORS: dict[str, str] = {
    "leader": "#ff6b6b",
    "dispatcher": "#ffd93d",
    "executor": "#6bcf7f",
    "user": "#4ecdc4",
    "system": "#a0a0a0",
}

COMMAND_TREE: list[tuple[str, list[str]]] = [
    ("聊天", ["发送消息", "@提及", "广播"]),
    ("拓扑", ["/flatten 拉平", "/rebuild 重建", "/status 状态"]),
    ("记忆", ["/summarize day", "/summarize stage", "/memory list"]),
    ("Git", ["/commit", "/status", "/timeline", "/push"]),
    ("会话", ["/checkpoint", "/rollback", "/export", "/import"]),
    ("模式", ["/mode plan", "/mode ask", "/mode code"]),
]


if TEXTUAL_AVAILABLE:

    class CommandNav(Tree):
        """左栏：命令导航树（方向键选择）。"""

        def __init__(self) -> None:
            super().__init__("命令", id="command-nav")
            for category, cmds in COMMAND_TREE:
                node = self.root.add(category, expand=False)
                for cmd in cmds:
                    node.add_leaf(cmd)

    class ChatView(RichLog):
        """中栏：群聊聊天框（气泡形式）。"""

        def __init__(self) -> None:
            super().__init__(id="chat-view", markup=True, wrap=True, auto_scroll=True)

        def add_bubble(self, role: str, tier: str, content: str, channel: str = "") -> None:
            """添加聊天气泡。"""
            color = TIER_COLORS.get(tier, "#a0a0a0")
            border = f"[{color}]{'─' * 50}[/{color}]"
            header = f"[{color} bold]{'  ' + role}[/]"
            if channel:
                header += f" [dim]({channel})[/]"
            self.write(border)
            self.write(header)
            self.write(f"  {content}")
            self.write(border)
            self.write("")

    class StatusPanel(Static):
        """右栏：状态面板。"""

        def update_status(self, topology: str, providers: list[str], git_status: str = "") -> None:
            """更新状态面板内容。"""
            lines = ["[bold]状态面板[/]", "", f"[bold]拓扑:[/] {topology}", "", "[bold]Provider:[/]"]
            for p in providers:
                lines.append(f"  • {p}")
            if git_status:
                lines.extend(["", "[bold]Git:[/]", f"  {git_status}"])
            self.update("\n".join(lines))

    class InputBox(Input):
        """输入框。"""

        def __init__(self) -> None:
            super().__init__(
                placeholder="输入消息，或输入 / 开头的命令... (Tab 切换面板, ↑↓ 选择命令)",
                id="input-box",
            )

    class MultiMindTUI(App):
        """MultiMind TUI 主应用 — 三栏布局。"""

        CSS = """
        Screen { layout: horizontal; }
        #command-nav { width: 22; border: solid #555; margin: 0 1 0 0; }
        #center-panel { width: 1fr; }
        #chat-view { height: 1fr; border: solid #6bcf7f; margin: 0 1 0 0; }
        #input-box { height: 3; margin: 1 0 0 0; }
        #status-panel { width: 28; border: solid #555; }
        """

        BINDINGS = [
            ("q", "quit", "退出"),
            ("tab", "focus_next", "切换面板"),
            ("ctrl+t", "toggle_topology", "拉平/重建"),
        ]

        def __init__(self) -> None:
            super().__init__()
            init_default_providers()
            self.orchestrator = Orchestrator()
            self._running_task: asyncio.Task | None = None

        def compose(self) -> ComposeResult:
            yield Header()
            yield CommandNav()
            with Container(id="center-panel"):
                yield ChatView()
                yield InputBox()
            yield StatusPanel()
            yield Footer()

        def on_mount(self) -> None:
            self._update_status()
            chat = self.query_one(ChatView)
            chat.add_bubble("系统", "system", "MultiMind 已启动。输入消息开始群聊，或按 Tab 切换到左栏选择命令。")

        def _update_status(self) -> None:
            panel = self.query_one(StatusPanel)
            providers = [str(p) for p in self.orchestrator.registry.all().values()]
            panel.update_status(self.orchestrator.topology.describe(), providers)

        @on(Input.Submitted)
        async def on_input_submitted(self, event: Input.Submitted) -> None:
            """处理用户输入。"""
            text = event.value.strip()
            if not text:
                return
            event.input.value = ""

            chat = self.query_one(ChatView)
            chat.add_bubble("用户", "user", text)

            if text.startswith("/"):
                await self._handle_command(text, chat)
                return

            chat.add_bubble("系统", "system", "正在协调多角色协作...")
            self._running_task = asyncio.create_task(self._run_chat(text))

        async def _run_chat(self, user_input: str) -> None:
            """运行群聊。"""
            chat = self.query_one(ChatView)
            try:
                async for chunk in self.orchestrator.run(user_input, max_rounds=2):
                    chat.write(chunk, scroll_end=True)
            except Exception:
                logger.exception("Chat error")
                chat.add_bubble("系统", "system", "发生错误，请查看日志")

        async def _handle_command(self, cmd: str, chat: ChatView) -> None:
            """处理斜杠命令。"""
            parts = cmd.split(maxsplit=1)
            command = parts[0]

            if command == "/flatten":
                msg = await self.orchestrator.topology.flatten()
                chat.add_bubble("系统", "system", msg)
            elif command == "/rebuild":
                msg = await self.orchestrator.topology.rebuild()
                chat.add_bubble("系统", "system", msg)
            elif command == "/status":
                providers = [str(p) for p in self.orchestrator.registry.all().values()]
                chat.add_bubble("系统", "system", "\n".join(providers))
            elif command == "/commit":
                chat.add_bubble("系统", "system", "手动提交（需在 Git 仓库中运行）")
            else:
                chat.add_bubble("系统", "system", f"未知命令: {command}")

        def action_toggle_topology(self) -> None:
            """Ctrl+T: 切换拓扑。"""

            async def _toggle() -> None:
                chat = self.query_one(ChatView)
                msg = await self.orchestrator.topology.toggle()
                chat.add_bubble("系统", "system", msg)
                self._update_status()

            asyncio.create_task(_toggle())

else:

    class MultiMindTUI:  # type: ignore[no-redef]
        """Textual 未安装时的占位类。"""

        def __init__(self, *args: object, **kwargs: object) -> None:
            raise ImportError(
                "TUI 需要 Textual。请安装: pip install textual  或  pip install multimind[dev]"
            )


def run_tui() -> None:
    """启动 TUI。"""
    if not TEXTUAL_AVAILABLE:
        print("TUI 需要 Textual。请安装: pip install textual")
        return
    app = MultiMindTUI()
    app.run()
