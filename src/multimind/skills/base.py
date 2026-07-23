"""Skill 抽象基类与核心类型。

所有 skill 无论来源层级，都实现统一的 ``Skill`` 接口。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from multimind.core.types import Permission

__all__ = [
    "SourceType",
    "SkillManifest",
    "SkillResult",
    "Skill",
]

logger = logging.getLogger(__name__)


class SourceType(str, Enum):
    """Skill 来源类型。

    Attributes:
        CORE: 自研核心 skill（Apache-2.0，随项目发布）。
        OPEN_SOURCE: 开源协议引入（MIT/Apache-2.0/CC0，保留许可证）。
        GENERATED: LLM 基于公开文档生成（需人工审核）。
    """

    CORE = "core"
    OPEN_SOURCE = "open_source"
    GENERATED = "generated"


@dataclass(frozen=True, slots=True)
class SkillManifest:
    """Skill 清单（不可变值对象）。

    对应 ``skill.toml`` 的内容。

    Attributes:
        name: Skill 唯一名称。
        version: 语义化版本号。
        description: 一句话描述（用于模型自判索引）。
        entry_point: 入口点（``module:ClassName`` 格式）。
        source_type: 来源类型。
        license: 许可证标识（如 ``Apache-2.0``）。
        upstream_url: 开源 skill 的上游 URL（open_source 必填）。
        source_docs: 生成式 skill 引用的公开文档 URL 列表。
        generation_model: 生成式 skill 使用的模型名。
        verified: 生成式 skill 是否已通过人工审核。
        tags: 能力标签（用于路由匹配）。
        requires_sandbox: 是否需要沙箱执行。
        requires_permission: 所需权限级别。
        max_retries: 最大重试次数。
    """

    name: str
    version: str
    description: str
    entry_point: str
    source_type: SourceType
    license: str = "Apache-2.0"
    upstream_url: str = ""
    source_docs: tuple[str, ...] = ()
    generation_model: str = ""
    verified: bool = True
    tags: tuple[str, ...] = ()
    requires_sandbox: bool = False
    requires_permission: Permission = Permission.AUTO
    max_retries: int = 3


@dataclass(slots=True)
class SkillResult:
    """Skill 执行结果。

    执行失败不抛异常，返回 ``success=False``，
    由调用方决定是否重试或降级。

    Attributes:
        success: 是否成功。
        output: 输出内容（成功时）。
        error: 错误信息（失败时）。
        metadata: 附加元数据（token 消耗、耗时等）。
    """

    success: bool
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    """Skill 抽象基类 — 所有 skill 实现此接口。

    无论来源层级（自研/开源/生成），都通过统一的 ``execute()`` 方法调用。
    """

    manifest: SkillManifest

    def __init__(self, manifest: SkillManifest) -> None:
        self.manifest = manifest

    @property
    def name(self) -> str:
        """Skill 名称。"""
        return self.manifest.name

    @property
    def description(self) -> str:
        """Skill 描述。"""
        return self.manifest.description

    @property
    def tags(self) -> tuple[str, ...]:
        """能力标签。"""
        return self.manifest.tags

    @abstractmethod
    async def execute(self, args: dict[str, Any]) -> SkillResult:
        """执行 skill。

        Args:
            args: 调用参数。

        Returns:
            执行结果（失败不抛异常，返回 ``success=False``）。
        """
        ...

    def describe(self) -> str:
        """返回用于模型自判的简短描述。

        格式：``name: description [tag1,tag2]``
        """
        tags_str = ",".join(self.manifest.tags) if self.manifest.tags else ""
        return f"{self.name}: {self.description} [{tags_str}]"

    def __repr__(self) -> str:
        return (
            f"<Skill {self.name} "
            f"source={self.manifest.source_type.value} "
            f"v{self.manifest.version}>"
        )
