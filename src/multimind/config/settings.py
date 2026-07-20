"""应用配置 — TOML 配置加载与验证。

配置文件位于 ``~/.multimind/config.toml``，使用 dataclass 验证。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from multimind.core.constants import DEFAULT_CONFIG_PATH

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["AppConfig", "GitConfigSpec", "MemoryConfigSpec", "load_config"]

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

    git_spec = GitConfigSpec(**data.get("git", {}))
    memory_spec = MemoryConfigSpec(**data.get("memory", {}))

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
