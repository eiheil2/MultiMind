"""角色编排引擎 — while-loop 内核 + 群聊总线 + 动态拓扑。"""

from multimind.engine.groupchat import ChatEvent, GroupChatBus, TopologyMode
from multimind.engine.orchestrator import Orchestrator
from multimind.engine.roles import ROLE_PROMPTS, Role, default_roles
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
]
