"""Skill 子系统 — 三层来源 · 动态扫描加载 · IP 风险隔离。

Skill 是 MultiMind 角色可调用的工具能力单元。按来源分为三层：
- 核心层：自研（Apache-2.0）
- 通用层：开源协议引入（MIT/Apache-2.0/CC0）
- 长尾层：LLM 基于公开文档生成

加载机制：动态扫描优先 → 配置文件 → 模型自判按需注入。
"""

from multimind.skills.audit import audit_skills
from multimind.skills.base import Skill, SkillManifest, SkillResult, SourceType
from multimind.skills.loader import SkillLoader
from multimind.skills.registry import SkillRegistry, get_skill_registry, reset_skill_registry

__all__ = [
    "Skill",
    "SkillResult",
    "SkillManifest",
    "SourceType",
    "SkillRegistry",
    "get_skill_registry",
    "reset_skill_registry",
    "SkillLoader",
    "audit_skills",
]
