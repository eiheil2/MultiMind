"""``settings.py`` 配置读写测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from multimind.config.settings import get_config_value, load_config, update_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_config(tmp_path: Path) -> Path:
    """创建临时配置文件。"""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[general]\n'
        'language = "zh"\n'
        'topology = "layered"\n'
        'default_provider = "gemini-cli"\n'
        'tool_permission = "ask"\n'
        'auto_commit = true\n'
        'output_dir = "/tmp/output"\n'
        '\n'
        '[logging]\n'
        'level = "INFO"\n'
        '\n'
        '[api_keys]\n'
        'groq = "gsk_test123"\n',
        encoding="utf-8",
    )
    return config_path


class TestUpdateConfig:
    """update_config 函数测试。"""

    def test_set_language(self, temp_config: Path) -> None:
        """设置语言。"""
        result = update_config("language", "en", temp_config)
        assert "language" in result
        assert get_config_value("language", temp_config) == "en"

    def test_set_topology(self, temp_config: Path) -> None:
        """设置拓扑。"""
        result = update_config("topology", "flat", temp_config)
        assert "topology" in result
        assert get_config_value("topology", temp_config) == "flat"

    def test_set_auto_commit_bool(self, temp_config: Path) -> None:
        """设置 auto_commit 布尔值。"""
        update_config("auto_commit", "false", temp_config)
        assert get_config_value("auto_commit", temp_config) is False

        update_config("auto_commit", "true", temp_config)
        assert get_config_value("auto_commit", temp_config) is True

    def test_set_auto_commit_yes(self, temp_config: Path) -> None:
        """auto_commit 接受 yes/on/1。"""
        update_config("auto_commit", "yes", temp_config)
        assert get_config_value("auto_commit", temp_config) is True

        update_config("auto_commit", "0", temp_config)
        assert get_config_value("auto_commit", temp_config) is False

    def test_set_log_level(self, temp_config: Path) -> None:
        """设置日志级别。"""
        result = update_config("log_level", "debug", temp_config)
        assert "log_level" in result
        assert get_config_value("log_level", temp_config) == "DEBUG"

    def test_set_api_key(self, temp_config: Path) -> None:
        """设置 API Key。"""
        result = update_config("api_key", "groq gsk_newkey456", temp_config)
        assert "groq" in result
        keys = get_config_value("api_keys", temp_config)
        assert keys["groq"] == "gsk_newkey456"

    def test_set_api_key_new_provider(self, temp_config: Path) -> None:
        """设置新 provider 的 API Key。"""
        update_config("api_key", "openai sk-newkey", temp_config)
        keys = get_config_value("api_keys", temp_config)
        assert keys["openai"] == "sk-newkey"
        # 原有的不丢失
        assert keys["groq"] == "gsk_test123"

    def test_set_api_key_invalid_format(self, temp_config: Path) -> None:
        """API Key 格式错误返回用法提示。"""
        result = update_config("api_key", "only_one_arg", temp_config)
        assert "用法" in result

    def test_unknown_key(self, temp_config: Path) -> None:
        """未知配置项返回错误。"""
        result = update_config("nonexistent", "value", temp_config)
        assert "未知" in result


class TestGetConfigValue:
    """get_config_value 函数测试。"""

    def test_get_language(self, temp_config: Path) -> None:
        """读取语言。"""
        assert get_config_value("language", temp_config) == "zh"

    def test_get_log_level(self, temp_config: Path) -> None:
        """读取日志级别。"""
        assert get_config_value("log_level", temp_config) == "INFO"

    def test_get_api_keys(self, temp_config: Path) -> None:
        """读取 API Keys。"""
        keys = get_config_value("api_keys", temp_config)
        assert keys["groq"] == "gsk_test123"

    def test_get_nonexistent(self, temp_config: Path) -> None:
        """读取不存在的键返回 None。"""
        assert get_config_value("nonexistent", temp_config) is None

    def test_get_from_missing_file(self, tmp_path: Path) -> None:
        """配置文件不存在时返回 None。"""
        path = tmp_path / "nonexistent.toml"
        assert get_config_value("language", path) is None


class TestLoadConfig:
    """load_config 函数测试（已有配置文件）。"""

    def test_load_full_config(self, temp_config: Path) -> None:
        """加载完整配置。"""
        cfg = load_config(temp_config)
        assert cfg.language == "zh"
        assert cfg.topology == "layered"
        assert cfg.default_provider == "gemini-cli"
        assert cfg.tool_permission == "ask"
        assert cfg.auto_commit is True
        assert cfg.log_level == "INFO"

    def test_load_missing_file(self, tmp_path: Path) -> None:
        """配置文件不存在时返回默认配置。"""
        path = tmp_path / "nonexistent.toml"
        cfg = load_config(path)
        assert cfg.language == "zh"
        assert cfg.topology == "layered"

    def test_update_then_reload(self, temp_config: Path) -> None:
        """更新配置后重新加载。"""
        update_config("language", "en", temp_config)
        update_config("topology", "flat", temp_config)
        cfg = load_config(temp_config)
        assert cfg.language == "en"
        assert cfg.topology == "flat"
