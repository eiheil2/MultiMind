"""``roles.py`` 提示词自定义功能测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_prompts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """创建临时提示词目录并 monkeypatch PROMPTS_DIR。"""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    # monkeypatch roles 模块中的 PROMPTS_DIR
    import multimind.engine.roles as roles_module

    monkeypatch.setattr(roles_module, "PROMPTS_DIR", prompts_dir)
    return prompts_dir


class TestCustomPrompts:
    """自定义提示词加载/保存/重置测试。"""

    def test_default_prompt_when_no_file(self, temp_prompts_dir: Path) -> None:
        """无自定义文件时返回内置默认。"""
        prompt = get_effective_prompt("leader")
        assert prompt == ROLE_PROMPTS["leader"]

    def test_is_custom_false_by_default(self, temp_prompts_dir: Path) -> None:
        """默认非自定义。"""
        assert not is_custom("leader")
        assert not is_custom("dispatcher")
        assert not is_custom("executor")

    def test_save_and_load_custom(self, temp_prompts_dir: Path) -> None:
        """保存后可加载自定义提示词。"""
        custom = "You are a custom leader. Be awesome."
        save_custom_prompt("leader", custom)

        assert is_custom("leader")
        loaded = load_custom_prompt("leader")
        assert loaded == custom

    def test_get_effective_prefers_custom(self, temp_prompts_dir: Path) -> None:
        """get_effective_prompt 优先返回自定义。"""
        custom = "Custom dispatcher prompt."
        save_custom_prompt("dispatcher", custom)

        effective = get_effective_prompt("dispatcher")
        assert effective == custom
        assert effective != ROLE_PROMPTS["dispatcher"]

    def test_reset_deletes_file(self, temp_prompts_dir: Path) -> None:
        """reset_custom_prompt 删除自定义文件。"""
        save_custom_prompt("executor", "Custom executor.")
        assert is_custom("executor")

        deleted = reset_custom_prompt("executor")
        assert deleted is True
        assert not is_custom("executor")

    def test_reset_returns_false_if_no_file(self, temp_prompts_dir: Path) -> None:
        """reset_custom_prompt 无文件时返回 False。"""
        deleted = reset_custom_prompt("leader")
        assert deleted is False

    def test_reset_restores_default(self, temp_prompts_dir: Path) -> None:
        """reset 后 get_effective_prompt 返回默认。"""
        save_custom_prompt("leader", "Custom.")
        reset_custom_prompt("leader")

        effective = get_effective_prompt("leader")
        assert effective == ROLE_PROMPTS["leader"]

    def test_save_creates_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """save_custom_prompt 自动创建目录。"""
        prompts_dir = tmp_path / "nested" / "prompts"
        assert not prompts_dir.exists()

        import multimind.engine.roles as roles_module

        monkeypatch.setattr(roles_module, "PROMPTS_DIR", prompts_dir)
        save_custom_prompt("leader", "Test prompt.")

        assert prompts_dir.exists()
        assert (prompts_dir / "leader.md").exists()

    def test_load_returns_none_on_missing(self, temp_prompts_dir: Path) -> None:
        """load_custom_prompt 文件不存在返回 None。"""
        assert load_custom_prompt("leader") is None

    def test_load_handles_read_error(
        self, temp_prompts_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_custom_prompt 读取失败返回 None。"""
        # 创建一个无法读取的文件
        prompt_file = temp_prompts_dir / "leader.md"
        prompt_file.write_text("content", encoding="utf-8")
        # monkeypatch Path.read_text 抛异常
        original_read = type(prompt_file).read_text

        def mock_read_text(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            if "leader.md" in str(self):
                raise OSError("Permission denied")
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr("pathlib.Path.read_text", mock_read_text)
        assert load_custom_prompt("leader") is None


class TestRoleWithCustomPrompt:
    """Role 类集成自定义提示词测试。"""

    def test_role_uses_default_when_no_custom(self, temp_prompts_dir: Path) -> None:
        """Role 无自定义文件时使用内置默认。"""
        role = Role(name="test", tier="leader", provider="test")
        assert role.prompt == ROLE_PROMPTS["leader"]

    def test_role_uses_custom_when_exists(self, temp_prompts_dir: Path) -> None:
        """Role 有自定义文件时使用自定义。"""
        custom = "You are a test leader."
        save_custom_prompt("leader", custom)

        role = Role(name="test", tier="leader", provider="test")
        assert role.prompt == custom
        assert role.prompt != ROLE_PROMPTS["leader"]

    def test_role_explicit_prompt_overrides_file(self, temp_prompts_dir: Path) -> None:
        """显式传入 prompt 时优先使用。"""
        save_custom_prompt("leader", "File prompt.")

        explicit = "Explicit prompt."
        role = Role(name="test", tier="leader", provider="test", prompt=explicit)
        assert role.prompt == explicit

    def test_default_roles_load_custom(self, temp_prompts_dir: Path) -> None:
        """default_roles 加载自定义提示词。"""
        custom_leader = "Custom leader for testing."
        save_custom_prompt("leader", custom_leader)

        roles = default_roles()
        leader = roles[0]
        assert leader.prompt == custom_leader
