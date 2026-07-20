"""Skill 加载器 — 动态扫描 + 配置文件 + 模型自判按需注入。

加载优先级：动态扫描 → 配置文件 → 内置核心。
三者叠加，不互斥。
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from multimind.core.constants import USER_CONFIG_DIR
from multimind.core.exceptions import ConfigurationError
from multimind.core.types import Permission
from multimind.skills.base import Skill, SkillManifest, SourceType
from multimind.skills.registry import SkillRegistry, get_skill_registry

__all__ = ["SkillLoader", "SkillLoadConfig", "ScanResult"]

logger = logging.getLogger(__name__)

# 动态扫描目录优先级（高 → 低）
SCAN_DIRS: list[Path] = [
    Path.cwd() / ".multimind" / "skills",   # 项目级
    USER_CONFIG_DIR / "skills",             # 用户级
]


@dataclass(slots=True)
class SkillLoadConfig:
    """Skill 加载配置。

    Attributes:
        extra_dirs: 额外扫描目录。
        enabled: 显式启用的 skill 名列表（None 表示不限制）。
        disabled: 显式禁用的 skill 名列表。
        require_verified: 生成式 skill 是否必须人工审核。
        max_description_tokens: 描述 token 上限（超过则不自动注入）。
    """

    extra_dirs: list[str] = field(default_factory=list)
    enabled: list[str] | None = None
    disabled: list[str] = field(default_factory=lambda: [])
    require_verified: bool = True
    max_description_tokens: int = 200


@dataclass(slots=True)
class ScanResult:
    """扫描结果。

    Attributes:
        found: 发现的 skill 清单列表。
        loaded: 成功加载的 skill 名列表。
        skipped: 跳过的 skill 名列表（含原因）。
        errors: 加载失败的 skill 名列表（含错误信息）。
    """

    found: list[SkillManifest] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


class SkillLoader:
    """Skill 加载器。

    职责：
    1. 动态扫描目录，发现含 ``skill.toml`` 的子目录。
    2. 解析清单文件，创建 skill 实例。
    3. 根据配置过滤（启用/禁用/审核状态）。
    4. 注册到 ``SkillRegistry``。
    5. 提供「模型自判」接口，按需注入 skill 描述。
    """

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        config: SkillLoadConfig | None = None,
    ) -> None:
        self._registry = registry or get_skill_registry()
        self._config = config or SkillLoadConfig()

    def load_all(self) -> ScanResult:
        """扫描所有目录并加载 skill。

        Returns:
            扫描结果。
        """
        result = ScanResult()

        # 合并扫描目录（去重）
        scan_dirs: list[Path] = []
        scan_dirs.extend(SCAN_DIRS)
        scan_dirs.extend(Path(d) for d in self._config.extra_dirs)

        # 按优先级遍历（高 → 低），同名 skill 高优先级覆盖
        seen_names: set[str] = set()
        for scan_dir in scan_dirs:
            if not scan_dir.is_dir():
                continue
            logger.debug("Scanning skill dir: %s", scan_dir)
            for entry in sorted(scan_dir.iterdir()):
                if not entry.is_dir():
                    continue
                manifest_path = entry / "skill.toml"
                if not manifest_path.exists():
                    continue

                try:
                    manifest = self._parse_manifest(manifest_path, entry)
                except Exception as e:
                    result.errors.append((entry.name, str(e)))
                    logger.exception("Failed to parse manifest: %s", manifest_path)
                    continue

                if manifest.name in seen_names:
                    logger.debug("Skipping duplicate skill (lower priority): %s", manifest.name)
                    continue
                seen_names.add(manifest.name)
                result.found.append(manifest)

        # 过滤并加载
        for manifest in result.found:
            skip_reason = self._should_skip(manifest)
            if skip_reason:
                result.skipped.append((manifest.name, skip_reason))
                continue

            try:
                skill = self._instantiate(manifest)
                self._registry.register(skill)
                result.loaded.append(manifest.name)
            except Exception as e:
                result.errors.append((manifest.name, str(e)))
                logger.exception("Failed to load skill: %s", manifest.name)

        logger.info(
            "Skill load complete: %d found, %d loaded, %d skipped, %d errors",
            len(result.found),
            len(result.loaded),
            len(result.skipped),
            len(result.errors),
        )
        return result

    def _should_skip(self, manifest: SkillManifest) -> str:
        """检查是否应跳过该 skill。返回跳过原因，空字符串表示不跳过。"""
        # 显式禁用
        if manifest.name in self._config.disabled:
            return "disabled by config"
        # 显式启用列表（非空时不在此列表则跳过）
        if self._config.enabled and manifest.name not in self._config.enabled:
            return "not in enabled list"
        # 生成式 skill 需审核
        if (
            manifest.source_type == SourceType.GENERATED
            and self._config.require_verified
            and not manifest.verified
        ):
            return "generated skill not verified"
        return ""

    def _parse_manifest(self, path: Path, skill_dir: Path) -> SkillManifest:
        """解析 ``skill.toml`` 清单文件。"""
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            import tomli as tomllib  # type: ignore[import-not-found]

        with open(path, "rb") as f:
            data = tomllib.load(f)

        skill_data = data.get("skill", {})
        prov = data.get("provenance", {})
        caps = data.get("capabilities", {})

        # 验证必填字段
        required = ["name", "version", "description", "entry_point"]
        for field_name in required:
            if field_name not in skill_data:
                raise ConfigurationError(
                    f"skill.toml missing required field: {field_name}"
                )

        source_type = SourceType(prov.get("source_type", "core"))

        # 开源 skill 必须有 upstream_url
        if source_type == SourceType.OPEN_SOURCE and not prov.get("upstream_url"):
            raise ConfigurationError(
                f"open_source skill '{skill_data['name']}' missing upstream_url"
            )

        # 生成式 skill 必须有 source_docs
        if source_type == SourceType.GENERATED and not prov.get("source_docs"):
            raise ConfigurationError(
                f"generated skill '{skill_data['name']}' missing source_docs"
            )

        return SkillManifest(
            name=skill_data["name"],
            version=skill_data["version"],
            description=skill_data["description"],
            entry_point=skill_data["entry_point"],
            source_type=source_type,
            license=prov.get("license", "Apache-2.0"),
            upstream_url=prov.get("upstream_url", ""),
            source_docs=tuple(prov.get("source_docs", [])),
            generation_model=prov.get("generation_model", ""),
            verified=prov.get("verified", source_type != SourceType.GENERATED),
            tags=tuple(caps.get("tags", [])),
            requires_sandbox=caps.get("requires_sandbox", False),
            requires_permission=Permission(caps.get("requires_permission", "auto")),
            max_retries=caps.get("max_retries", 3),
        )

    def _instantiate(self, manifest: SkillManifest) -> Skill:
        """根据清单实例化 skill。

        ``entry_point`` 格式为 ``module:ClassName``，动态导入并实例化。
        """
        entry = manifest.entry_point
        if ":" not in entry:
            raise ConfigurationError(
                f"Invalid entry_point '{entry}', expected 'module:ClassName'"
            )

        module_path, class_name = entry.rsplit(":", 1)
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise ConfigurationError(
                f"Cannot import skill module '{module_path}': {e}"
            ) from e

        cls = getattr(module, class_name, None)
        if cls is None:
            raise ConfigurationError(
                f"Skill class '{class_name}' not found in '{module_path}'"
            )

        return cls(manifest)

    def index_for_model(self) -> list[str]:
        """返回轻量索引摘要（供 Leader 角色模型自判）。

        每个元素格式：``name: description [tags]``
        """
        return self._registry.index_summary()

    def select_for_task(
        self,
        needed_skills: list[str],
    ) -> list[Skill]:
        """根据 Leader 声明的所需 skill，返回完整实例列表。

        Args:
            needed_skills: Leader 声明的 skill 名列表。

        Returns:
            选中的 skill 实例列表（跳过不存在的）。
        """
        selected: list[Skill] = []
        for name in needed_skills:
            skill = self._registry.get(name)
            if skill is not None:
                selected.append(skill)
            else:
                logger.warning("Requested skill not found: %s", name)
        return selected
