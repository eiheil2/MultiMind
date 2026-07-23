"""日志配置工具。

提供统一的结构化日志格式，支持 JSON 输出（用于 Headless 模式）
和彩色终端输出（用于 TUI 模式）。
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

__all__ = ["setup_logging", "get_logger"]

_LOG_FORMAT = "%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured: bool = False


def setup_logging(
    level: str | int = "INFO",
    format_type: Literal["text", "json"] = "text",
) -> None:
    """配置全局日志。

    Args:
        level: 日志级别（``DEBUG`` / ``INFO`` / ``WARNING`` / ``ERROR``）。
        format_type: 输出格式（``text`` 终端用 / ``json`` Headless 用）。
    """
    global _configured  # noqa: PLW0603
    if _configured:
        return

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    if format_type == "json":
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger。"""
    return logging.getLogger(name)


class _JsonFormatter(logging.Formatter):
    """JSON 格式日志（用于 Headless / CI 场景）。"""

    import json

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, _DATE_FORMAT),
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return self.json.dumps(log_entry, ensure_ascii=False)
