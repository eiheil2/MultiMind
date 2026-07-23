"""角色编排引擎 — while-loop 内核 + 群聊总线 + 动态拓扑 + 分层上下文。"""

from multimind.engine.context import (
    ContextBuilder,
    ContextStats,
    Fact,
    Turn,
    count_char_classes,
    estimate_tokens,
    split_turns,
)
from multimind.engine.groupchat import ChatEvent, GroupChatBus, TopologyMode
from multimind.engine.orchestrator import Orchestrator, OrchestratorEvent
from multimind.engine.roles import (
    ROLE_PROMPTS,
    Role,
    default_roles,
    get_effective_prompt,
    is_custom,
    load_custom_prompt,
    reset_custom_prompt,
    save_custom_prompt,
)
from multimind.engine.topology import TopologyManager

__all__ = [
    "GroupChatBus",
    "TopologyMode",
    "ChatEvent",
    "Role",
    "default_roles",
    "ROLE_PROMPTS",
    "TopologyManager",
    "Orchestrator",
    "OrchestratorEvent",
    "ContextBuilder",
    "ContextStats",
    "Fact",
    "Turn",
    "split_turns",
    "estimate_tokens",
    "count_char_classes",
    "load_custom_prompt",
    "save_custom_prompt",
    "reset_custom_prompt",
    "get_effective_prompt",
    "is_custom",
]
