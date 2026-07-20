"""核心领域层 — 类型定义、抽象接口、异常体系和常量。

本包不依赖任何具体实现（adapters / engine / ui 等），是整个项目的
基础。其他所有层都依赖 ``core``，``core`` 不依赖任何其他层。
"""
from multimind.core.constants import APP_NAME, DEFAULT_CONFIG_PATH, DEFAULT_SESSION_ID
from multimind.core.exceptions import (
    AdapterError,
    ConfigurationError,
    GitError,
    MemoryError,
    MultiMindError,
    RoutingError,
    SessionError,
)
from multimind.core.interfaces import AIAdapter, MemoryStore, ToolProvider
from multimind.core.types import (
    ChannelType,
    Message,
    Permission,
    ProviderConfig,
    RoleMode,
    RoleTier,
)

__all__ = [
    # Types
    "ChannelType",
    "Message",
    "Permission",
    "ProviderConfig",
    "RoleMode",
    "RoleTier",
    # Exceptions
    "MultiMindError",
    "AdapterError",
    "ConfigurationError",
    "GitError",
    "MemoryError",
    "RoutingError",
    "SessionError",
    # Interfaces
    "AIAdapter",
    "MemoryStore",
    "ToolProvider",
    # Constants
    "APP_NAME",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_SESSION_ID",
]
