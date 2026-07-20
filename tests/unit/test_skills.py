"""Skill 子系统测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from multimind.skills.audit import ALLOWED_LICENSES, audit_skills
from multimind.skills.base import Skill, SkillManifest, SkillResult, SourceType
from multimind.skills.core.file_ops import FileReadSkill, FileWriteSkill
from multimind.skills.core.http import HttpRequestSkill
from multimind.skills.core.shell import ShellExecSkill
from multimind.skills.loader import SkillLoadConfig, SkillLoader
from multimind.skills.registry import SkillRegistry, get_skill_registry, reset_skill_registry

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset() -> None:
    """每个测试前重置 skill 注册表。"""
    reset_skill_registry()


# ── 基类测试 ────────────────────────────────────────────────────


class TestSkillBase:
    """测试 Skill 抽象基类和值对象。"""

    def test_manifest_is_frozen(self) -> None:
        """SkillManifest 是不可变的。"""
        manifest = SkillManifest(
            name="test",
            version="0.1.0",
            description="test skill",
            entry_point="mod:Cls",
            source_type=SourceType.CORE,
        )
        with pytest.raises(AttributeError):
            manifest.name = "changed"  # type: ignore[misc]

    def test_source_type_values(self) -> None:
        """SourceType 有三个值。"""
        assert SourceType.CORE.value == "core"
        assert SourceType.OPEN_SOURCE.value == "open_source"
        assert SourceType.GENERATED.value == "generated"

    def test_skill_describe_format(self) -> None:
        """describe() 返回正确格式。"""
        skill = FileReadSkill()
        desc = skill.describe()
        assert "file_read" in desc
        assert "file" in desc

    def test_skill_result_defaults(self) -> None:
        """SkillResult 默认值正确。"""
        result = SkillResult(success=True)
        assert result.success is True
        assert result.output == ""
        assert result.error == ""
        assert result.metadata == {}


# ── 注册表测试 ──────────────────────────────────────────────────


class TestSkillRegistry:
    """测试 SkillRegistry。"""

    def test_register_and_get(self) -> None:
        """注册后可按名获取。"""
        registry = SkillRegistry()
        skill = FileReadSkill()
        registry.register(skill)
        assert registry.get("file_read") is skill

    def test_get_nonexistent_returns_none(self) -> None:
        """获取不存在的 skill 返回 None。"""
        registry = SkillRegistry()
        assert registry.get("nonexistent") is None

    def test_by_tag(self) -> None:
        """按标签筛选正确。"""
        registry = SkillRegistry()
        registry.register(FileReadSkill())
        registry.register(HttpRequestSkill())
        file_skills = registry.by_tag("file")
        assert len(file_skills) == 1
        assert file_skills[0].name == "file_read"

    def test_index_summary(self) -> None:
        """索引摘要格式正确。"""
        registry = SkillRegistry()
        registry.register(FileReadSkill())
        summary = registry.index_summary()
        assert len(summary) == 1
        assert "file_read" in summary[0]

    def test_contains(self) -> None:
        """__contains__ 正确。"""
        registry = SkillRegistry()
        registry.register(FileReadSkill())
        assert "file_read" in registry
        assert "nonexistent" not in registry

    def test_len(self) -> None:
        """__len__ 正确。"""
        registry = SkillRegistry()
        assert len(registry) == 0
        registry.register(FileReadSkill())
        assert len(registry) == 1

    def test_reset_registry(self) -> None:
        """reset 清空注册表。"""
        reg = get_skill_registry()
        reg.register(FileReadSkill())
        assert len(reg) == 1
        reset_skill_registry()
        reg2 = get_skill_registry()
        assert len(reg2) == 0


# ── 加载器测试 ──────────────────────────────────────────────────


class TestSkillLoader:
    """测试 SkillLoader 动态扫描。"""

    def _create_skill_dir(
        self,
        base: Path,
        name: str,
        source_type: str = "core",
        verified: bool = True,
        source_docs: list[str] | None = None,
        upstream_url: str = "",
    ) -> Path:
        """创建测试 skill 目录。"""
        skill_dir = base / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        toml_content = f'''[skill]
name = "{name}"
version = "0.1.0"
description = "Test skill {name}"
entry_point = "multimind.skills.core.file_ops:FileReadSkill"

[provenance]
source_type = "{source_type}"
license = "Apache-2.0"
verified = {str(verified).lower()}
'''
        if upstream_url:
            toml_content += f'upstream_url = "{upstream_url}"\n'
        if source_docs:
            toml_content += f'source_docs = {source_docs}\n'

        toml_content += '''
[capabilities]
tags = ["test"]
requires_sandbox = false
requires_permission = "auto"
'''
        (skill_dir / "skill.toml").write_text(toml_content)
        return skill_dir

    def test_scan_finds_skill(self, tmp_path: Path) -> None:
        """动态扫描发现 skill。"""
        self._create_skill_dir(tmp_path, "test-skill")
        loader = SkillLoader(config=SkillLoadConfig(extra_dirs=[str(tmp_path)]))
        result = loader.load_all()
        assert len(result.found) == 1
        assert "test-skill" in result.loaded

    def test_disabled_skill_skipped(self, tmp_path: Path) -> None:
        """被禁用的 skill 被跳过。"""
        self._create_skill_dir(tmp_path, "test-skill")
        config = SkillLoadConfig(extra_dirs=[str(tmp_path)], disabled=["test-skill"])
        loader = SkillLoader(config=config)
        result = loader.load_all()
        assert "test-skill" not in result.loaded
        assert any(name == "test-skill" for name, _ in result.skipped)

    def test_enabled_filter(self, tmp_path: Path) -> None:
        """enabled 列表过滤。"""
        self._create_skill_dir(tmp_path, "skill-a")
        self._create_skill_dir(tmp_path, "skill-b")
        config = SkillLoadConfig(
            extra_dirs=[str(tmp_path)],
            enabled=["skill-a"],
        )
        loader = SkillLoader(config=config)
        result = loader.load_all()
        assert "skill-a" in result.loaded
        assert "skill-b" not in result.loaded

    def test_generated_unverified_skipped(self, tmp_path: Path) -> None:
        """未验证的 generated skill 被跳过。"""
        self._create_skill_dir(
            tmp_path,
            "gen-skill",
            source_type="generated",
            verified=False,
            source_docs=['"https://example.com/api"'],
        )
        config = SkillLoadConfig(extra_dirs=[str(tmp_path)], require_verified=True)
        loader = SkillLoader(config=config)
        result = loader.load_all()
        assert "gen-skill" not in result.loaded

    def test_generated_verified_loaded(self, tmp_path: Path) -> None:
        """已验证的 generated skill 可加载。"""
        self._create_skill_dir(
            tmp_path,
            "gen-skill",
            source_type="generated",
            verified=True,
            source_docs=['"https://example.com/api"'],
        )
        config = SkillLoadConfig(extra_dirs=[str(tmp_path)], require_verified=True)
        loader = SkillLoader(config=config)
        result = loader.load_all()
        assert "gen-skill" in result.loaded

    def test_select_for_task(self) -> None:
        """select_for_task 返回正确 skill。"""
        registry = get_skill_registry()
        registry.register(FileReadSkill())
        registry.register(HttpRequestSkill())
        loader = SkillLoader(registry=registry)
        selected = loader.select_for_task(["file_read"])
        assert len(selected) == 1
        assert selected[0].name == "file_read"

    def test_select_for_task_missing(self) -> None:
        """select_for_task 跳过不存在的 skill。"""
        registry = get_skill_registry()
        loader = SkillLoader(registry=registry)
        selected = loader.select_for_task(["nonexistent"])
        assert len(selected) == 0

    def test_index_for_model(self) -> None:
        """index_for_model 返回摘要。"""
        registry = get_skill_registry()
        registry.register(FileReadSkill())
        loader = SkillLoader(registry=registry)
        index = loader.index_for_model()
        assert len(index) == 1
        assert "file_read" in index[0]


# ── 核心 skill 执行测试 ────────────────────────────────────────


class TestCoreSkills:
    """测试核心自研 skill 执行。"""

    @pytest.mark.asyncio
    async def test_file_read(self, tmp_path: Path) -> None:
        """file_read 正确读取文件。"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        skill = FileReadSkill()
        result = await skill.execute({"path": str(test_file)})
        assert result.success is True
        assert "line1" in result.output
        assert "line2" in result.output

    @pytest.mark.asyncio
    async def test_file_read_not_found(self) -> None:
        """file_read 文件不存在返回失败。"""
        skill = FileReadSkill()
        result = await skill.execute({"path": "/nonexistent/file.txt"})
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_file_read_missing_path(self) -> None:
        """file_read 缺少 path 参数返回失败。"""
        skill = FileReadSkill()
        result = await skill.execute({})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_file_write(self, tmp_path: Path) -> None:
        """file_write 正确写入文件。"""
        test_file = tmp_path / "output.txt"
        skill = FileWriteSkill()
        result = await skill.execute({
            "path": str(test_file),
            "content": "hello world",
        })
        assert result.success is True
        assert test_file.read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_file_write_append(self, tmp_path: Path) -> None:
        """file_write append 模式追加内容。"""
        test_file = tmp_path / "output.txt"
        test_file.write_text("line1\n")
        skill = FileWriteSkill()
        await skill.execute({"path": str(test_file), "content": "line2\n", "mode": "append"})
        assert test_file.read_text() == "line1\nline2\n"

    @pytest.mark.asyncio
    async def test_http_request(self) -> None:
        """http_request 返回模拟结果。"""
        skill = HttpRequestSkill()
        result = await skill.execute({"url": "https://example.com", "method": "GET"})
        assert result.success is True
        assert "200" in result.output

    @pytest.mark.asyncio
    async def test_http_request_missing_url(self) -> None:
        """http_request 缺少 url 返回失败。"""
        skill = HttpRequestSkill()
        result = await skill.execute({})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_shell_exec(self) -> None:
        """shell_exec 返回模拟结果。"""
        skill = ShellExecSkill()
        result = await skill.execute({"command": "echo hello"})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_shell_exec_missing_command(self) -> None:
        """shell_exec 缺少 command 返回失败。"""
        skill = ShellExecSkill()
        result = await skill.execute({})
        assert result.success is False


# ── 审计测试 ────────────────────────────────────────────────────


class TestSkillAudit:
    """测试许可证合规审计。"""

    def test_audit_passes_for_core(self) -> None:
        """核心 skill 审计通过。"""
        registry = SkillRegistry()
        registry.register(FileReadSkill())
        result = audit_skills(registry)
        assert result.passed is True
        assert result.total == 1
        assert len(result.issues) == 0

    def test_audit_fails_for_bad_license(self) -> None:
        """非允许许可证审计失败。"""
        from multimind.skills.base import SkillManifest
        manifest = SkillManifest(
            name="bad-license",
            version="0.1.0",
            description="test",
            entry_point="mod:Cls",
            source_type=SourceType.CORE,
            license="Proprietary",
        )

        class FakeSkill(Skill):
            async def execute(self, args):
                return SkillResult(success=True)

        registry = SkillRegistry()
        fake = FakeSkill(manifest)
        registry.register(fake)
        result = audit_skills(registry)
        assert result.passed is False
        assert any("not in allowed list" in i.message for i in result.issues)

    def test_audit_warns_unverified_generated(self) -> None:
        """未验证的 generated skill 产生 warning。"""
        from multimind.skills.base import SkillManifest
        manifest = SkillManifest(
            name="gen-skill",
            version="0.1.0",
            description="test",
            entry_point="mod:Cls",
            source_type=SourceType.GENERATED,
            source_docs=("https://example.com",),
            generation_model="test-model",
            verified=False,
        )

        class FakeSkill(Skill):
            async def execute(self, args):
                return SkillResult(success=True)

        registry = SkillRegistry()
        registry.register(FakeSkill(manifest))
        result = audit_skills(registry)
        assert any(i.severity == "warning" for i in result.issues)

    def test_audit_fails_for_generated_without_docs(self) -> None:
        """generated skill 无 source_docs 审计失败。"""
        from multimind.skills.base import SkillManifest
        manifest = SkillManifest(
            name="gen-no-docs",
            version="0.1.0",
            description="test",
            entry_point="mod:Cls",
            source_type=SourceType.GENERATED,
            verified=True,
        )

        class FakeSkill(Skill):
            async def execute(self, args):
                return SkillResult(success=True)

        registry = SkillRegistry()
        registry.register(FakeSkill(manifest))
        result = audit_skills(registry)
        assert result.passed is False

    def test_allowed_licenses_includes_expected(self) -> None:
        """允许的许可证列表包含预期的。"""
        assert "MIT" in ALLOWED_LICENSES
        assert "Apache-2.0" in ALLOWED_LICENSES
        assert "CC0" in ALLOWED_LICENSES
