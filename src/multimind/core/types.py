"""核心类型定义。

所有领域类型使用 ``dataclass`` 或 ``Enum`` 定义，确保不可变性和类型安全。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

__all__ = [
    "ChannelType",
    "RoleMode",
    "Permission",
    "RoleTier",
    "Message",
    "ProviderConfig",
]


class ChannelType(str, Enum):
    """五类通道类型。

    每个通道代表一种接入 AI 的方式，上层通过统一 ``AIAdapter.ask()``
    接口无感调用。

    Attributes:
        CLI_REUSE: 官方 CLI 复用（OAuth 登录态）。
        API_CLIENT: 免费 API（Key 鉴权）。
        BROWSER: 网页登录（Cookie / Playwright 操控）。
        PUBLIC_ENDPOINT: 公共端点（零鉴权，如 OpenCode 内置模型）。
        LOCAL: 本地兜底（Ollama / LM Studio）。
    """

    CLI_REUSE = "cli_reuse"
    API_CLIENT = "api_client"
    BROWSER = "browser"
    PUBLIC_ENDPOINT = "public"
    LOCAL = "local"


class RoleMode(str, Enum):
    """角色运行模式（借鉴 Claude Code 子 Agent 三态）。

    Attributes:
        EXPLORE: 只读模式，角色只能观察和检索，不能修改。
        PLAN: 规划模式，角色只产出方案，不执行任何工具。
        ACT: 执行模式，角色可调用工具执行操作。
    """

    EXPLORE = "explore"
    PLAN = "plan"
    ACT = "act"


class Permission(str, Enum):
    """工具调用权限级别（借鉴 Claude Code 五权限模式）。

    Attributes:
        NONE: 无工具权限。
        ASK: 每次工具调用前需用户确认。
        AUTO: 低风险自动执行，高风险询问用户。
        ALL: 全部自动执行，无需确认。
    """

    NONE = "none"
    ASK = "ask"
    AUTO = "auto"
    ALL = "all"


RoleTier = Literal["leader", "dispatcher", "executor"]
"""角色层级类型。"""


@dataclass(frozen=True, slots=True)
class Message:
    """群聊消息（不可变值对象）。

    Attributes:
        role: 发送者角色名。
        content: 消息内容。
        channel: 来源 provider 名称。
        mode: 发送时的角色模式。
        timestamp: Unix 时间戳（秒）。
        metadata: 附加元数据（token 数、耗时等）。
    """

    role: str
    content: str
    channel: str = ""
    mode: RoleMode = RoleMode.ACT
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Provider 配置（不可变值对象）。

    Attributes:
        name: Provider 唯一名称。
        channel: 通道类型。
        model: 模型标识。
        api_key: API 密钥（API 通道用）。
        endpoint: 自定义端点 URL。
        tags: 能力标签列表（用于路由匹配）。
        priority: 优先级（值越小越优先）。
        daily_quota: 每日额度上限（-1 表示无限）。
        rpm_limit: 每分钟请求上限。
        max_tokens: 上下文窗口大小。
    """

    name: str
    channel: ChannelType
    model: str = ""
    api_key: str = ""
    endpoint: str = ""
    tags: tuple[str, ...] = ()
    priority: int = 100
    daily_quota: int = -1
    rpm_limit: int = 60
    max_tokens: int = 8192
