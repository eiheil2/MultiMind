"""额度追踪 — SQLite 记录每个 provider 的日用量/剩余。"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["QuotaTracker"]

logger = logging.getLogger(__name__)


class QuotaTracker:
    """额度池追踪器。

    维护每个 provider 的每日用量，支持查询剩余额度和记录消费。
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS quota_usage (
                provider TEXT NOT NULL,
                date TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                PRIMARY KEY (provider, date)
            );
        """)
        self._conn.commit()

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")

    def get_used(self, provider: str) -> int:
        """获取 provider 今日已用量。"""
        row = self._conn.execute(
            "SELECT used FROM quota_usage WHERE provider=? AND date=?",
            (provider, self._today()),
        ).fetchone()
        return row[0] if row else 0

    def record(self, provider: str, tokens: int = 1) -> None:
        """记录 provider 用量。"""
        self._conn.execute(
            """INSERT INTO quota_usage (provider, date, used) VALUES (?, ?, ?)
               ON CONFLICT(provider, date) DO UPDATE SET used = used + ?""",
            (provider, self._today(), tokens, tokens),
        )
        self._conn.commit()

    def remaining(self, provider: str, daily_quota: int) -> int:
        """计算剩余额度。"""
        if daily_quota < 0:
            return 999_999
        return max(0, daily_quota - self.get_used(provider))

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()
