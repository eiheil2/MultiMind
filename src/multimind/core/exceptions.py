"""自定义异常层次体系。

所有 MultiMind 异常都继承自 ``MultiMindError``，调用方可通过
``except MultiMindError`` 统一捕获。

异常设计原则：
- 每个子系统有独立的异常类。
- 异常携带上下文信息（provider 名、文件路径等）。
- 不暴露底层实现细节（如 HTTP 状态码），转为业务语义。
"""

from __future__ import annotations

__all__ = [
    "MultiMindError",
    "AdapterError",
    "ConfigurationError",
    "GitError",
    "MemoryError",
    "RoutingError",
    "SessionError",
]


class MultiMindError(Exception):
    """所有 MultiMind 异常的基类。"""


class AdapterError(MultiMindError):
    """适配器层异常（通道调用失败、鉴权过期等）。"""


class ConfigurationError(MultiMindError):
    """配置异常（配置文件缺失、格式错误等）。"""


class GitError(MultiMindError):
    """自动 Git 异常（提交失败、校验未通过、回退失败等）。"""


class MemoryError(MultiMindError):
    """记忆系统异常（数据库错误、检索失败等）。"""


class RoutingError(MultiMindError):
    """路由异常（无可用 provider、标签不匹配等）。"""


class SessionError(MultiMindError):
    """会话异常（checkpoint 损坏、回放失败等）。"""
