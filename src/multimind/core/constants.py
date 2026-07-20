"""全局常量定义。"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_SESSION_ID",
    "DEFAULT_DB_PATH",
    "USER_CONFIG_DIR",
]

APP_NAME: str = "multimind"
APP_VERSION: str = "0.1.0"

USER_CONFIG_DIR: Path = Path(os.environ.get("MULTIMIND_HOME", Path.home() / ".multimind"))
DEFAULT_CONFIG_PATH: Path = USER_CONFIG_DIR / "config.toml"
DEFAULT_DB_PATH: Path = USER_CONFIG_DIR / "multimind.db"
DEFAULT_SESSION_ID: str = "default"
