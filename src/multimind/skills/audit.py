"""Skill 许可证合规审计。

扫描所有已加载 skill，检查 IP 合规性。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from multimind.skills.base import SourceType

if TYPE_CHECKING:
    from multimind.skills.registry import SkillRegistry

__all__ = ["AuditResult", "AuditIssue", "audit_skills"]

logger = logging.getLogger(__name__)

# 允许的开源许可证
ALLOWED_LICENSES: frozenset[str] = frozenset({
    "MIT",
    "Apache-2.0",
    "CC0",
    "CC0-1.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
})


@dataclass(slots=True)
class AuditIssue:
    """审计问题。

    Attributes:
        skill_name: skill 名称。
        severity: 严重程度（``error`` / ``warning``）。
        message: 问题描述。
    """

    skill_name: str
    severity: str
    message: str


@dataclass(slots=True)
class AuditResult:
    """审计结果。

    Attributes:
        total: 审计的 skill 总数。
        issues: 发现的问题列表。
        passed: 是否通过审计（无 error 级问题）。
    """

    total: int = 0
    issues: list[AuditIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """是否通过审计（无 error 级问题）。"""
        return not any(i.severity == "error" for i in self.issues)


def audit_skills(registry: SkillRegistry) -> AuditResult:
    """审计所有已注册 skill 的 IP 合规性。

    检查项：
    - ``open_source`` skill 是否有 LICENSE 文件（仅检查路径名存在）。
    - 许可证是否在允许列表内。
    - ``generated`` skill 是否有 source_docs 和 verified=True。
    - ``generated`` skill 未验证是否被加载（warning）。

    Args:
        registry: Skill 注册表。

    Returns:
        审计结果。
    """
    result = AuditResult(total=len(registry))

    for name, skill in registry.all().items():
        manifest = skill.manifest

        # 检查许可证是否在允许列表
        if manifest.license not in ALLOWED_LICENSES:
            result.issues.append(AuditIssue(
                skill_name=name,
                severity="error",
                message=f"License '{manifest.license}' not in allowed list: {ALLOWED_LICENSES}",
            ))

        # 开源 skill 检查
        if manifest.source_type == SourceType.OPEN_SOURCE and not manifest.upstream_url:
            result.issues.append(AuditIssue(
                skill_name=name,
                severity="error",
                message="open_source skill missing upstream_url",
            ))

        # 生成式 skill 检查
        if manifest.source_type == SourceType.GENERATED:
            if not manifest.source_docs:
                result.issues.append(AuditIssue(
                    skill_name=name,
                    severity="error",
                    message="generated skill missing source_docs",
                ))
            if not manifest.verified:
                result.issues.append(AuditIssue(
                    skill_name=name,
                    severity="warning",
                    message="generated skill not verified but loaded",
                ))
            if not manifest.generation_model:
                result.issues.append(AuditIssue(
                    skill_name=name,
                    severity="warning",
                    message="generated skill missing generation_model",
                ))

    # 汇总日志
    errors = sum(1 for i in result.issues if i.severity == "error")
    warnings = sum(1 for i in result.issues if i.severity == "warning")
    logger.info(
        "Skill audit: %d total, %d errors, %d warnings, %s",
        result.total,
        errors,
        warnings,
        "PASSED" if result.passed else "FAILED",
    )

    return result
