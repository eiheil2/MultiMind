"""角色编排引擎 — while-loop 内核 + 群聊总线 + 动态拓扑。"""

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
    "load_custom_prompt",
    "save_custom_prompt",
    "reset_custom_prompt",
    "get_effective_prompt",
    "is_custom",
]
