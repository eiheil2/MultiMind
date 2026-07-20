"""应用配置 — TOML 配置加载与验证。

配置文件位于 ``~/.multimind/config.toml``，使用 dataclass 验证。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any

from multimind.core.constants import DEFAULT_CONFIG_PATH

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["AppConfig", "GitConfigSpec", "MemoryConfigSpec", "load_config", "update_config", "get_config_value"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GitConfigSpec:
    """Git 配置规格。"""

    auto_commit: bool = True
    trigger: str = "step"
    work_branch_prefix: str = "mm/"
    protect_main: bool = True
    lint_before_commit: bool = True
    test_before_commit: bool = False
    fast_mode: bool = False
    max_retry: int = 3


@dataclass(slots=True)
class MemoryConfigSpec:
    """记忆系统配置规格。"""

    short_term_window: int = 100
    mid_term_limit: int = 500
    long_term_limit: int = 1000
    autodream_idle_seconds: int = 30
    allow_manual: bool = True


@dataclass(slots=True)
class AppConfig:
    """应用总配置。

    Attributes:
        language: 界面语言（"zh" / "en"）。
        topology: 默认拓扑模式（"layered" / "flat" / "hybrid"）。
        default_provider: 默认使用的 provider 名称。
        tool_permission: 工具执行权限（"none" / "ask" / "auto" / "all"）。
        auto_commit: 是否自动 git commit。
        output_dir: 输出目录。
        log_level: 日志级别。
        providers: Provider 配置列表。
        git: Git 配置。
        memory: 记忆系统配置。
        roles: 角色编排配置。
        api_keys: API 密钥映射（provider 名 → key）。
    """

    language: str = "zh"
    topology: str = "layered"
    default_provider: str = ""
    tool_permission: str = "ask"
    auto_commit: bool = True
    output_dir: str = ""
    log_level: str = "INFO"
    providers: list[dict[str, Any]] = field(default_factory=list)
    git: GitConfigSpec = field(default_factory=GitConfigSpec)
    memory: MemoryConfigSpec = field(default_factory=MemoryConfigSpec)
    roles: list[dict[str, Any]] = field(default_factory=list)
    api_keys: dict[str, str] = field(default_factory=dict)


def _filter_fields(spec_cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """仅保留 dataclass 已知字段，过滤 TOML 中的未知键。

    防止配置文件中出现废弃/拼写错误的字段时，``**kwargs`` 展开抛出
    ``TypeError: unexpected keyword argument`` 导致整个配置加载失败。
    """
    known = {f.name for f in fields(spec_cls)}
    return {k: v for k, v in data.items() if k in known}


def load_config(config_path: Path | None = None) -> AppConfig:
    """加载配置文件。

    Args:
        config_path: 配置文件路径。None 则使用默认路径。

    Returns:
        应用配置实例。
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        logger.info("Config file not found at %s, using defaults", path)
        return AppConfig()

    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found]

    with open(path, "rb") as f:
        data = tomllib.load(f)

    git_spec = GitConfigSpec(**_filter_fields(GitConfigSpec, data.get("git", {})))
    memory_spec = MemoryConfigSpec(**_filter_fields(MemoryConfigSpec, data.get("memory", {})))

    general = data.get("general", {})

    return AppConfig(
        language=general.get("language", "zh"),
        topology=general.get("topology", "layered"),
        default_provider=general.get("default_provider", ""),
        tool_permission=general.get("tool_permission", "ask"),
        auto_commit=general.get("auto_commit", True),
        output_dir=general.get("output_dir", ""),
        log_level=data.get("logging", {}).get("level", "INFO"),
        providers=data.get("providers", []),
        git=git_spec,
        memory=memory_spec,
        roles=data.get("roles", []),
        api_keys=data.get("api_keys", {}),
    )


# ── 运行时配置读写 ────────────────────────────────────────────────────

# general 段可设置的键及其类型
_SETTABLE_KEYS: dict[str, type] = {
    "language": str,
    "topology": str,
    "default_provider": str,
    "tool_permission": str,
    "auto_commit": bool,
    "output_dir": str,
}

# logging 段可设置的键
_LOGGING_KEYS: dict[str, type] = {
    "log_level": str,
}


def _read_toml(path: Path) -> dict[str, Any]:
    """读取 TOML 文件，不存在则返回空 dict。"""
    if not path.exists():
        return {}
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found]

    with open(path, "rb") as f:
        return tomllib.load(f)


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    """写入 TOML 文件。"""
    import tomli_w

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def update_config(
    key: str,
    value: str,
    config_path: Path | None = None,
) -> str:
    """更新配置文件中的单个键值。

    支持的键: language, topology, default_provider, tool_permission,
    auto_commit, output_dir, log_level, api_key.

    Args:
        key: 配置键名。
        value: 配置值（字符串形式，内部自动转换类型）。
        config_path: 配置文件路径，None 则使用默认路径。

    Returns:
        操作结果描述。
    """
    path = config_path or DEFAULT_CONFIG_PATH
    data = _read_toml(path)

    # API Key 特殊处理
    if key == "api_key":
        parts = value.split(maxsplit=1)
        if len(parts) != 2:
            return "用法: /set api_key <provider> <key>"
        provider, api_key = parts
        api_keys = data.get("api_keys", {})
        api_keys[provider] = api_key
        data["api_keys"] = api_keys
        _write_toml(path, data)
        return f"已设置 {provider} 的 API Key"

    # auto_commit 类型转换
    if key in _SETTABLE_KEYS:
        section = data.setdefault("general", {})
        expected_type = _SETTABLE_KEYS[key]

        if expected_type is bool:
            section[key] = value.lower() in ("true", "1", "yes", "on")
        else:
            section[key] = value
        _write_toml(path, data)
        return f"已设置 {key} = {section[key]}"

    # log_level 在 logging 段
    if key in _LOGGING_KEYS:
        section = data.setdefault("logging", {})
        section["level"] = value.upper()
        _write_toml(path, data)
        return f"已设置 log_level = {section['level']}"

    available = ", ".join(list(_SETTABLE_KEYS.keys()) + list(_LOGGING_KEYS.keys()) + ["api_key"])
    return f"未知配置项: {key}\n可设置: {available}"


def get_config_value(key: str, config_path: Path | None = None) -> Any:
    """读取配置文件中的单个键值。

    Args:
        key: 配置键名。
        config_path: 配置文件路径。

    Returns:
        配置值，不存在则返回 None。
    """
    path = config_path or DEFAULT_CONFIG_PATH
    data = _read_toml(path)

    if key in _SETTABLE_KEYS:
        return data.get("general", {}).get(key)
    if key in _LOGGING_KEYS:
        return data.get("logging", {}).get("level")
    if key == "api_keys":
        return data.get("api_keys", {})
    return None
