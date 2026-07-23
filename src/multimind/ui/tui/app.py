"""TUI 主应用 — 三栏布局 · 方向键导航 · 群聊气泡 · 赛博科技感。

使用 Textual 框架实现类 GUI 终端界面。

视觉语言：
- 近黑底 + 霓虹青/紫/绿/红 —— 赛博面板风格。
- heavy 发光边框、ASCII 启动横幅、角色图标。
- 结构化事件渲染：ROLE_START/CHUNK/END 聚合为角色气泡，
  ERROR 红色告警气泡，ROUND_END 回合分隔线。
"""

from __future__ import annotations

import asyncio
import logging

try:
    from rich.panel import Panel
    from rich.text import Text
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

# ── 赛博配色（按角色层级）───────────────────────────────────────────
TIER_COLORS: dict[str, str] = {
    "leader": "#ff2a6d",  # 霓虹红 — 指挥官
    "dispatcher": "#ffd300",  # 霓虹黄 — 调度员
    "executor": "#00ff9d",  # 霓虹绿 — 执行者
    "user": "#00e5ff",  # 霓虹青 — 用户
    "system": "#5c6773",  # 冷灰 — 系统
    "error": "#ff3860",  # 告警红
}

TIER_ICONS: dict[str, str] = {
    "leader": "◆",
    "dispatcher": "▸",
    "executor": "⚙",
    "user": "❯",
    "system": "·",
    "error": "✗",
}

BANNER = r"""[#00e5ff]  __  __ _   _ _   _____ ___ __  __ ___ _  _ ___
 |  \/  | | | | | |_   _|_ _|  \/  |_ _| \| |   \
 | |\/| | |_| | |__ | |  | || |\/| || || .` | |) |
 |_|  |_|\___/|____||_| |___|_|  |_|___|_|\_|___/[/]
[#5c6773]  多 AI 协作终端 · Multi-Agent Orchestration[/]"""

COMMAND_TREE: list[tuple[str, list[str]]] = [
    ("⚡ 聊天", ["发送消息", "@提及", "广播"]),
    ("🔀 拓扑", ["/flatten 拉平", "/rebuild 重建", "/status 状态"]),
    ("🧠 记忆", ["/summarize day", "/summarize stage", "/memory list"]),
    ("📦 Git", ["/commit", "/status", "/timeline", "/push"]),
    ("💾 会话", ["/checkpoint", "/rollback", "/export", "/import"]),
    ("🎛 模式", ["/mode plan", "/mode ask", "/mode code"]),
]


if TEXTUAL_AVAILABLE:

    class CommandNav(Tree[str]):
        """左栏：命令导航树（方向键选择）。"""

        def __init__(self) -> None:
            super().__init__("控制台", id="command-nav")
            for category, cmds in COMMAND_TREE:
                node = self.root.add(category, expand=False)
                for cmd in cmds:
                    node.add_leaf(cmd)
            self.root.expand()

    class ChatView(RichLog):
        """中栏：群聊聊天框（霓虹气泡）。"""

        def __init__(self) -> None:
            super().__init__(id="chat-view", markup=True, wrap=True, auto_scroll=True)

        def add_bubble(self, role: str, tier: str, content: str, channel: str = "") -> None:
            """添加聊天气泡（Rich Panel，角色色边框 + 图标）。"""
            color = TIER_COLORS.get(tier, TIER_COLORS["system"])
            icon = TIER_ICONS.get(tier, "·")
            title = f"{icon} {role}"
            if channel:
                title += f" [{channel}]"
            self.write(
                Panel(
                    content,
                    title=title,
                    title_align="left",
                    border_style=color,
                    padding=(0, 1),
                )
            )

        def add_notice(self, text: str) -> None:
            """添加系统提示行（灰暗小字）。"""
            self.write(f"[{TIER_COLORS['system']}]{text}[/]")

        def add_round_separator(self, round_num: int) -> None:
            """回合分隔线。"""
            line = Text()
            line.append("─" * 8, style="#1f2b3a")
            line.append(f" ⚡ 第 {round_num} 轮完成 ", style="#00e5ff dim")
            line.append("─" * 8, style="#1f2b3a")
            self.write(line)

    class StatusPanel(Static):
        """右栏：状态面板（赛博仪表盘）。"""

        def update_status(self, topology: str, providers: list[str], git_status: str = "") -> None:
            """更新状态面板内容。"""
            lines = [
                "[bold #00e5ff]◢ 系统状态[/]",
                "[#1f2b3a]" + "─" * 22 + "[/]",
                "",
                "[bold #ffd300]⛁ 拓扑[/]",
                f"  [#e0e0e0]{topology}[/]",
                "",
                "[bold #00ff9d]⏻ Provider[/]",
            ]
            for p in providers:
                lines.append(f"  [#00e5ff]▪[/] [#e0e0e0]{p}[/]")
            if git_status:
                lines.extend(
                    [
                        "",
                        "[bold #ff2a6d]⎇ Git[/]",
                        f"  [#e0e0e0]{git_status}[/]",
                    ]
                )
            self.update("\n".join(lines))

    class InputBox(Input):
        """输入框。"""

        def __init__(self) -> None:
            super().__init__(
                placeholder="输入消息，或 / 开头的命令… (Tab 切换面板, ↑↓ 选择命令)",
                id="input-box",
            )

    class MultiMindTUI(App[None]):
        """MultiMind TUI 主应用 — 三栏赛博布局。"""

        CSS = """
        Screen { background: #0a0e14; }
        Header { background: #0d1420; color: #00e5ff; }
        Footer { background: #0d1420; color: #5c6773; }
        #command-nav {
            width: 26;
            border: heavy #1f2b3a;
            background: #0d1219;
            margin: 0 1 0 0;
        }
        #command-nav:focus { border: heavy #00e5ff; }
        #center-panel { width: 1fr; }
        #chat-view {
            height: 1fr;
            border: heavy #134e4a;
            background: #0a0f16;
            margin: 0 1 0 0;
            padding: 0 1;
        }
        #chat-view:focus { border: heavy #00ff9d; }
        #input-box {
            height: 3;
            border: heavy #1f2b3a;
            background: #0d1420;
            margin: 1 1 0 0;
        }
        #input-box:focus { border: heavy #00e5ff; }
        #status-panel {
            width: 30;
            border: heavy #1f2b3a;
            background: #0d1219;
            padding: 1 2;
        }
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
            self._running_task: asyncio.Task[None] | None = None

        def compose(self) -> ComposeResult:
            yield Header()
            yield CommandNav()
            with Container(id="center-panel"):
                yield ChatView()
                yield InputBox()
            yield StatusPanel()
            yield Footer()

        def on_mount(self) -> None:
            self.title = "MultiMind"
            self.sub_title = "多 AI 协作终端"
            self._update_status()
            chat = self.query_one(ChatView)
            chat.write(BANNER)
            chat.add_notice("系统就绪。输入消息开始多角色协作，/help 查看命令，Tab 切换面板。")

        def _update_status(self) -> None:
            panel = self.query_one(StatusPanel)
            providers = [a.config.name for a in self.orchestrator.registry.all().values()]
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

            if self._running_task is not None and not self._running_task.done():
                chat.add_notice("上一轮协作仍在进行，请稍候…")
                return

            chat.add_notice("⚡ 正在协调多角色协作…")
            self._running_task = asyncio.create_task(self._run_chat(text))

        async def _run_chat(self, user_input: str) -> None:
            """运行群聊 — 结构化事件聚合成角色气泡。"""
            from multimind.engine.orchestrator import OrchestratorEvent

            chat = self.query_one(ChatView)
            current_role = ""
            current_tier = "system"
            buf: list[str] = []

            try:
                async for event in self.orchestrator.run(user_input, max_rounds=2):
                    if event.event_type == OrchestratorEvent.ROLE_START:
                        current_role = event.role_name
                        current_tier = event.role_tier
                        buf = []
                        icon = TIER_ICONS.get(event.role_tier, "·")
                        color = TIER_COLORS.get(event.role_tier, TIER_COLORS["system"])
                        chat.add_notice(f"[{color}]{icon} {current_role} 正在思考…[/]")
                    elif event.event_type == OrchestratorEvent.ROLE_CHUNK:
                        buf.append(event.content)
                    elif event.event_type == OrchestratorEvent.ROLE_END:
                        content = "".join(buf).strip() or "（无输出）"
                        chat.add_bubble(current_role, current_tier, content, event.provider)
                        buf = []
                    elif event.event_type == OrchestratorEvent.ROUND_END:
                        chat.add_round_separator(event.round_num)
                    elif event.event_type == OrchestratorEvent.ERROR:
                        chat.add_bubble("错误", "error", event.content)
                        buf = []
            except Exception:
                logger.exception("Chat error")
                chat.add_bubble("错误", "error", "发生内部错误，请查看日志")

        async def _handle_command(self, cmd: str, chat: ChatView) -> None:
            """处理斜杠命令。"""
            parts = cmd.split(maxsplit=1)
            command = parts[0]

            if command == "/flatten":
                msg = await self.orchestrator.topology.flatten()
                chat.add_notice(msg)
                self._update_status()
            elif command == "/rebuild":
                msg = await self.orchestrator.topology.rebuild()
                chat.add_notice(msg)
                self._update_status()
            elif command == "/status":
                providers = [str(p) for p in self.orchestrator.registry.all().values()]
                chat.add_bubble("系统", "system", "\n".join(providers) or "（无 provider）")
            elif command == "/commit":
                chat.add_notice("手动提交（需在 Git 仓库中运行）")
            elif command in ("/help", "/?"):
                chat.add_bubble(
                    "系统",
                    "system",
                    "/flatten 拉平拓扑 · /rebuild 重建 · /status 状态\n"
                    "/commit 提交 · q 退出 · Tab 切换面板",
                )
            else:
                chat.add_notice(f"未知命令: {command}（/help 查看可用命令）")

        def action_toggle_topology(self) -> None:
            """Ctrl+T: 切换拓扑。"""

            async def _toggle() -> None:
                chat = self.query_one(ChatView)
                msg = await self.orchestrator.topology.toggle()
                chat.add_notice(msg)
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
