"""站点配置数据结构 + TOML 加载器 + 配置校验。

每个 AI 网站一个 TOML 配置文件，包含：
  - CSS 选择器（输入框、发送按钮、响应容器、停止按钮）
  - 模式列表（深度思考、联网搜索等）
  - 安全参数（延迟、限流、有头模式）
  - 完成检测策略
  - 能力声明（流式、文件上传、多轮对话等）

网站改版时改配置不改代码，支持热更新。
支持用户自定义配置目录和第三方插件配置。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = [
    "SiteSelectors",
    "SiteMode",
    "SafetyConfig",
    "CompletionConfig",
    "SiteCapability",
    "SiteProfile",
    "ProfileValidationError",
    "load_profile",
    "load_profile_by_name",
    "discover_profiles",
    "validate_profile",
    "get_profile_search_dirs",
]

logger = logging.getLogger(__name__)

# 内置站点配置文件目录
_BUILTIN_PROFILES_DIR: Path = Path(__file__).parent / "profiles"


# ═══════════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SiteSelectors:
    """CSS 选择器集合 — 定位页面关键 DOM 元素。

    Attributes:
        input_box: 输入框选择器（textarea 或 contenteditable）。
        send_button: 发送按钮选择器。
        response_container: 响应内容容器选择器。
        stop_button: 停止生成按钮选择器（用于完成检测）。
        login_redirect: 登录重定向指示元素选择器（登录过期检测）。
        mode_container: 模式选择区域容器选择器。
    """

    input_box: str
    send_button: str
    response_container: str
    stop_button: str = ""
    login_redirect: str = ""
    mode_container: str = ""


@dataclass(frozen=True, slots=True)
class SiteMode:
    """站点模式定义（深度思考、联网搜索、画图等）。

    Attributes:
        name: 模式标识（用于 API 调用，如 ``deep_thinking``）。
        label: 模式显示名（如 ``深度思考``）。
        selector: 模式切换按钮的 CSS 选择器。
    """

    name: str
    label: str
    selector: str


@dataclass(frozen=True, slots=True)
class SafetyConfig:
    """反封号安全参数。

    Attributes:
        min_delay: 操作间最小延迟（秒）。
        max_delay: 操作间最大延迟（秒）。
        max_requests_per_session: 每会话最大请求数。
        session_timeout: 会话超时时间（秒）。
        headed: 是否使用有头模式（True=可见浏览器，降低检测风险）。
        max_consecutive_errors: 连续错误熔断阈值。
    """

    min_delay: float = 1.0
    max_delay: float = 3.0
    max_requests_per_session: int = 50
    session_timeout: int = 3600
    headed: bool = True
    max_consecutive_errors: int = 5


@dataclass(frozen=True, slots=True)
class CompletionConfig:
    """响应完成检测策略。

    Attributes:
        method: 检测方法（``stop_button_disappear`` 或 ``response_stable``）。
        timeout: 最大等待时间（秒）。
        stable_duration: ``response_stable`` 方法的稳定持续时间（秒）。
        poll_interval: 轮询间隔（秒）。
    """

    method: str = "stop_button_disappear"
    timeout: int = 120
    stable_duration: float = 2.0
    poll_interval: float = 0.5


@dataclass(frozen=True, slots=True)
class SiteCapability:
    """站点能力声明 — 告诉上层此站点支持哪些功能。

    用于编排器决策：哪些站点可以接收文件、哪些支持多轮对话等。

    Attributes:
        streaming: 是否支持流式输出。
        file_upload: 是否支持文件上传。
        multi_turn: 是否支持多轮对话。
        mode_switching: 是否支持模式切换。
        max_input_length: 最大输入字符数。
        custom: 自定义能力标签（如 ``image_generation``、``code_execution``）。
    """

    streaming: bool = True
    file_upload: bool = False
    multi_turn: bool = True
    mode_switching: bool = False
    max_input_length: int = 10000
    custom: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SiteProfile:
    """站点完整配置（不可变值对象）。

    Attributes:
        name: 站点标识（如 ``deepseek``）。
        url: 站点主页 URL。
        login_url: 登录页 URL（用于登录过期时引导用户）。
        selectors: CSS 选择器集合。
        modes: 支持的模式列表。
        safety: 安全参数。
        completion: 完成检测策略。
        capabilities: 站点能力声明。
    """

    name: str
    url: str
    login_url: str = ""
    selectors: SiteSelectors = field(
        default_factory=lambda: SiteSelectors(
            input_box="", send_button="", response_container=""
        )
    )
    modes: tuple[SiteMode, ...] = ()
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    completion: CompletionConfig = field(default_factory=CompletionConfig)
    capabilities: SiteCapability = field(default_factory=SiteCapability)


# ═══════════════════════════════════════════════════════════════════════
# 配置校验
# ═══════════════════════════════════════════════════════════════════════


class ProfileValidationError(Exception):
    """站点配置校验错误。

    Attributes:
        site_name: 出错的站点名。
        errors: 错误消息列表。
    """

    def __init__(self, site_name: str, errors: list[str]) -> None:
        self.site_name = site_name
        self.errors = errors
        detail = "; ".join(errors)
        super().__init__(f"Profile '{site_name}' validation failed: {detail}")


def validate_profile(profile: SiteProfile) -> list[str]:
    """校验站点配置，返回错误消息列表。

    空列表表示配置通过校验。不抛出异常，由调用方决定如何处理。

    Args:
        profile: 待校验的站点配置。

    Returns:
        错误消息列表（空列表 = 全部通过）。
    """
    errors: list[str] = []

    # 必填字段
    if not profile.name:
        errors.append("[site] name is required")
    if not profile.url:
        errors.append("[site] url is required")
    if not profile.url.startswith("https://") and not profile.url.startswith("http://"):
        errors.append(f"[site] url must start with http(s)://, got: {profile.url}")

    # 选择器必填
    sel = profile.selectors
    if not sel.input_box:
        errors.append("[selectors] input_box is required")
    if not sel.send_button:
        errors.append("[selectors] send_button is required")
    if not sel.response_container:
        errors.append("[selectors] response_container is required")

    # 安全参数合理性
    s = profile.safety
    if s.min_delay < 0:
        errors.append(f"[safety] min_delay must be >= 0, got {s.min_delay}")
    if s.max_delay < s.min_delay:
        errors.append(
            f"[safety] max_delay ({s.max_delay}) must be >= min_delay ({s.min_delay})"
        )
    if s.max_requests_per_session <= 0:
        errors.append(
            f"[safety] max_requests_per_session must be > 0, got {s.max_requests_per_session}"
        )
    if s.session_timeout <= 0:
        errors.append(f"[safety] session_timeout must be > 0, got {s.session_timeout}")
    if s.max_consecutive_errors <= 0:
        errors.append(
            f"[safety] max_consecutive_errors must be > 0, got {s.max_consecutive_errors}"
        )

    # 完成检测参数
    c = profile.completion
    if c.method not in ("stop_button_disappear", "response_stable"):
        errors.append(
            f"[completion] method must be 'stop_button_disappear' or 'response_stable', "
            f"got: {c.method}"
        )
    if c.timeout <= 0:
        errors.append(f"[completion] timeout must be > 0, got {c.timeout}")
    if c.poll_interval <= 0:
        errors.append(f"[completion] poll_interval must be > 0, got {c.poll_interval}")
    if c.method == "stop_button_disappear" and not sel.stop_button:
        errors.append(
            "[completion] method='stop_button_disappear' requires "
            "[selectors] stop_button to be set"
        )

    # 模式唯一性校验
    mode_names: list[str] = []
    for mode in profile.modes:
        if not mode.name:
            errors.append("[modes] mode name is required")
        if not mode.selector:
            errors.append(f"[modes] mode '{mode.name}' has empty selector")
        mode_names.append(mode.name)
    if len(mode_names) != len(set(mode_names)):
        duplicates = [n for n in mode_names if mode_names.count(n) > 1]
        errors.append(f"[modes] duplicate mode names: {', '.join(set(duplicates))}")

    # 能力声明合理性
    cap = profile.capabilities
    if cap.max_input_length <= 0:
        errors.append(
            f"[capabilities] max_input_length must be > 0, got {cap.max_input_length}"
        )
    if cap.mode_switching and not profile.modes:
        errors.append(
            "[capabilities] mode_switching=true but no modes defined"
        )

    return errors


# ═══════════════════════════════════════════════════════════════════════
# TOML 解析
# ═══════════════════════════════════════════════════════════════════════


def _parse_selectors(data: dict[str, Any]) -> SiteSelectors:
    """从 TOML 字典解析选择器。"""
    return SiteSelectors(
        input_box=data.get("input_box", ""),
        send_button=data.get("send_button", ""),
        response_container=data.get("response_container", ""),
        stop_button=data.get("stop_button", ""),
        login_redirect=data.get("login_redirect", ""),
        mode_container=data.get("mode_container", ""),
    )


def _parse_modes(data: list[dict[str, Any]]) -> tuple[SiteMode, ...]:
    """从 TOML 字典列表解析模式。"""
    return tuple(
        SiteMode(
            name=m["name"],
            label=m.get("label", m["name"]),
            selector=m["selector"],
        )
        for m in data
    )


def _parse_safety(data: dict[str, Any]) -> SafetyConfig:
    """从 TOML 字典解析安全参数。"""
    return SafetyConfig(
        min_delay=float(data.get("min_delay", 1.0)),
        max_delay=float(data.get("max_delay", 3.0)),
        max_requests_per_session=int(data.get("max_requests_per_session", 50)),
        session_timeout=int(data.get("session_timeout", 3600)),
        headed=bool(data.get("headed", True)),
        max_consecutive_errors=int(data.get("max_consecutive_errors", 5)),
    )


def _parse_completion(data: dict[str, Any]) -> CompletionConfig:
    """从 TOML 字典解析完成检测配置。"""
    return CompletionConfig(
        method=data.get("method", "stop_button_disappear"),
        timeout=int(data.get("timeout", 120)),
        stable_duration=float(data.get("stable_duration", 2.0)),
        poll_interval=float(data.get("poll_interval", 0.5)),
    )


def _parse_capabilities(data: dict[str, Any]) -> SiteCapability:
    """从 TOML 字典解析能力声明。"""
    custom_raw = data.get("custom", [])
    if isinstance(custom_raw, str):
        custom_tuple: tuple[str, ...] = tuple(
            s.strip() for s in custom_raw.split(",") if s.strip()
        )
    else:
        custom_tuple = tuple(str(s) for s in custom_raw)

    return SiteCapability(
        streaming=bool(data.get("streaming", True)),
        file_upload=bool(data.get("file_upload", False)),
        multi_turn=bool(data.get("multi_turn", True)),
        mode_switching=bool(data.get("mode_switching", False)),
        max_input_length=int(data.get("max_input_length", 10000)),
        custom=custom_tuple,
    )


def load_profile(path: Path) -> SiteProfile:
    """从 TOML 文件加载站点配置。

    Args:
        path: TOML 配置文件路径。

    Returns:
        站点配置对象。

    Raises:
        FileNotFoundError: 文件不存在。
        KeyError: 缺少必需字段。
    """
    logger.debug("Loading site profile from %s", path)
    with open(path, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    site_data: dict[str, Any] = data.get("site", {})
    name: str = site_data["name"]
    url: str = site_data["url"]

    selectors = _parse_selectors(data.get("selectors", {}))
    modes = _parse_modes(data.get("modes", []))
    safety = _parse_safety(data.get("safety", {}))
    completion = _parse_completion(data.get("completion", {}))
    capabilities = _parse_capabilities(data.get("capabilities", {}))

    profile = SiteProfile(
        name=name,
        url=url,
        login_url=site_data.get("login_url", ""),
        selectors=selectors,
        modes=modes,
        safety=safety,
        completion=completion,
        capabilities=capabilities,
    )

    logger.info(
        "Loaded site profile '%s' (url=%s, modes=%d, capabilities=%s)",
        name,
        url,
        len(modes),
        [c for c in ("streaming", "file_upload", "multi_turn") if getattr(capabilities, c)],
    )
    return profile


# ═══════════════════════════════════════════════════════════════════════
# 多目录搜索 + 配置发现
# ═══════════════════════════════════════════════════════════════════════


def get_profile_search_dirs() -> list[Path]:
    """获取配置文件搜索目录列表（用户目录优先，内置目录兜底）。

    搜索顺序：
      1. 环境变量 ``MULTIMIND_SITES_DIR``（冒号分隔多目录）
      2. ``~/.multimind/sites/``
      3. 内置 ``profiles/`` 目录

    Returns:
        搜索目录列表，优先级从高到低。
    """
    dirs: list[Path] = []

    # 环境变量（支持冒号分隔多目录）
    env_dir = os.environ.get("MULTIMIND_SITES_DIR", "")
    if env_dir:
        for part in env_dir.split(":"):
            part = part.strip()
            if part:
                dirs.append(Path(part).expanduser())

    # 用户默认目录
    user_dir = Path.home() / ".multimind" / "sites"
    if user_dir not in dirs:
        dirs.append(user_dir)

    # 内置目录（最低优先级）
    dirs.append(_BUILTIN_PROFILES_DIR)

    return dirs


def discover_profiles() -> dict[str, Path]:
    """发现所有可用站点配置文件。

    搜索所有配置目录，用户目录覆盖内置目录（同名配置以高优先级目录为准）。

    Returns:
        站点名 → 配置文件路径的映射。
    """
    result: dict[str, Path] = {}

    # 从低优先级到高优先级遍历，高优先级覆盖低优先级
    for search_dir in reversed(get_profile_search_dirs()):
        if not search_dir.is_dir():
            continue
        for path in search_dir.glob("*.toml"):
            result[path.stem] = path

    logger.debug("Discovered %d site profiles: %s", len(result), sorted(result.keys()))
    return result


def load_profile_by_name(site_name: str) -> SiteProfile:
    """按站点名加载配置文件。

    在所有配置搜索目录中查找 ``{site_name}.toml``，用户目录优先于内置目录。

    Args:
        site_name: 站点标识（如 ``deepseek``）。

    Returns:
        站点配置对象。

    Raises:
        FileNotFoundError: 配置文件不存在。
    """
    for search_dir in get_profile_search_dirs():
        path = search_dir / f"{site_name}.toml"
        if path.exists():
            return load_profile(path)

    available = sorted(discover_profiles().keys())
    raise FileNotFoundError(
        f"Site profile '{site_name}' not found in any search directory. "
        f"Available: {', '.join(available) if available else 'none'}"
    )
