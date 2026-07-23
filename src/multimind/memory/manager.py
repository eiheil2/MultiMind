"""记忆管理器 — 三层记忆 · 单一中介。

借鉴 Claude Code 三层记忆索引 + AutoDream 记忆固化。
记忆管理器是角色与模型间的唯一中介：组装上下文 → 调用 provider → 写回 → 触发总结。

三层记忆：
- **短期**：群聊总线 + 滚动摘要（MicroCompact）。
- **中期**：阶段总结 + 向量检索。
- **长期**：项目档案 + 知识图谱。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal

from multimind.core.types import Message
from multimind.engine.context import ContextBuilder

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["MemoryTier", "MemoryEntry", "MemoryManager"]

logger = logging.getLogger(__name__)


class MemoryTier(str, Enum):
    """记忆层级。

    Attributes:
        SHORT: 短期 — 群聊总线 + 滚动摘要。
        MID: 中期 — 阶段总结 + 向量检索。
        LONG: 长期 — 项目档案 + 知识图谱。
    """

    SHORT = "short"
    MID = "mid"
    LONG = "long"


@dataclass(slots=True)
class MemoryEntry:
    """记忆条目。

    Attributes:
        tier: 记忆层级。
        content: 记忆内容。
        role: 来源角色。
        timestamp: Unix 时间戳。
        tags: 分类标签。
        embedding: 向量嵌入（框架验证留空）。
    """

    tier: MemoryTier
    content: str
    role: str = ""
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)


class MemoryManager:
    """记忆管理器 — 唯一中介。

    职责：
    1. 为角色组装上下文（短期滚动 + 中期检索 + 长期档案）。
    2. 按 provider 窗口大小动态裁剪。
    3. 空闲时触发 AutoDream（去重、抽取事实、更新图谱）。
    4. 手动 ``/summarize`` 触发总结。
    5. 与 AutoGit 的 checkpoint 联动。
    """

    # 滚动窗口阈值
    SHORT_TERM_WINDOW: int = 100
    # MicroCompact 保留最近消息数
    COMPACT_KEEP: int = 50

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._init_db()
        self._short_term: list[Message] = []
        self._mid_term: list[MemoryEntry] = []
        self._long_term: list[MemoryEntry] = []
        self._autodream_running = False
        self._context_builder = context_builder or ContextBuilder()

    def _init_db(self) -> None:
        """初始化数据库表。"""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tier TEXT NOT NULL,
                role TEXT,
                content TEXT NOT NULL,
                tags TEXT,
                timestamp REAL,
                embedding TEXT
            );
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_hash TEXT,
                role TEXT,
                timestamp REAL,
                state TEXT
            );
        """)
        self._conn.commit()

    # ── 短期记忆 ──────────────────────────────────────────────────

    def add_short_term(self, msg: Message) -> None:
        """添加短期记忆消息。"""
        self._short_term.append(msg)
        if len(self._short_term) > self.SHORT_TERM_WINDOW:
            self._compact_short_term()

    def _compact_short_term(self) -> None:
        """MicroCompact（借鉴 Claude Code 三层压缩第一层）。"""
        old = self._short_term[: self.COMPACT_KEEP]
        summary = f"[压缩] {len(old)}条消息摘要: " + " | ".join(
            f"{m.role}:{m.content[:20]}" for m in old[:5]
        )
        self._short_term = [Message(role="system", content=summary)] + self._short_term[
            self.COMPACT_KEEP :
        ]
        logger.debug("Short-term compacted: %d -> %d", len(old), len(self._short_term))

    # ── 中期记忆 ──────────────────────────────────────────────────

    def add_mid_term(self, entry: MemoryEntry) -> None:
        """添加中期记忆条目。"""
        self._mid_term.append(entry)
        self._conn.execute(
            "INSERT INTO memories (tier, role, content, tags, timestamp) VALUES (?,?,?,?,?)",
            (entry.tier.value, entry.role, entry.content, ",".join(entry.tags), entry.timestamp),
        )
        self._conn.commit()

    # ── 长期记忆 ──────────────────────────────────────────────────

    def add_long_term(self, entry: MemoryEntry) -> None:
        """添加长期记忆条目。"""
        self._long_term.append(entry)
        self._conn.execute(
            "INSERT INTO memories (tier, role, content, tags, timestamp) VALUES (?,?,?,?,?)",
            (entry.tier.value, entry.role, entry.content, ",".join(entry.tags), entry.timestamp),
        )
        self._conn.commit()

    # ── 上下文组装（核心：单一中介）────────────────────────────────

    def assemble_context(
        self,
        role_name: str,
        max_tokens: int = 8192,
    ) -> list[Message]:
        """为角色组装上下文，按 provider 窗口动态裁剪。

        Args:
            role_name: 角色名。
            max_tokens: 最大 token 数（按字符数 / 4 估算）。

        Returns:
            裁剪后的上下文消息列表。
        """
        # 短期记忆：委托 ContextBuilder 做 L0/L1/L2 分层组装 + 严格预算裁剪
        context = self._context_builder.build(
            list(self._short_term),
            query=role_name,
            max_tokens=max_tokens,
        )
        # 中期/长期记忆是 MemoryManager 特有数据源，在通用组装结果上追加，
        # 保持 ContextBuilder 通用性的同时保留特有角色标记。
        for entry in self._mid_term[-5:]:
            context.append(
                Message(
                    role=f"[记忆·{entry.tier.value}]",
                    content=entry.content,
                )
            )
        for entry in self._long_term[-3:]:
            context.append(
                Message(
                    role=f"[档案·{entry.tier.value}]",
                    content=entry.content,
                )
            )
        return context

    # ── 总结（手动 + 自动）────────────────────────────────────────

    def summarize(
        self,
        kind: Literal["daily", "stage"] = "daily",
        force: bool = False,
    ) -> str:
        """触发总结。

        Args:
            kind: ``daily`` 当日总结 | ``stage`` 阶段总结。
            force: ``True`` 跳过 skip 条件（手动触发入口）。

        Returns:
            总结内容。
        """
        if not force and len(self._short_term) < 10:
            return "消息不足 10 条，跳过总结（使用 force=True 可强制触发）"

        messages = self._short_term if kind == "daily" else self._short_term[-20:]
        summary = f"[{kind}总结] 共{len(messages)}条消息。关键点：\n"
        for msg in messages[:10]:
            summary += f"  - {msg.role}: {msg.content[:50]}\n"

        self.add_mid_term(
            MemoryEntry(
                tier=MemoryTier.MID,
                content=summary,
                role="summarizer",
                tags=[kind],
            )
        )
        self._conn.execute(
            "INSERT INTO summaries (kind, content, created_at) VALUES (?,?,?)",
            (kind, summary, time.time()),
        )
        self._conn.commit()
        logger.info("Summary generated: kind=%s, msgs=%d", kind, len(messages))
        return summary

    # ── AutoDream（空闲记忆固化）──────────────────────────────────

    async def autodream(self, idle_seconds: int = 30) -> None:
        """空闲时后台整理记忆（借鉴 Claude Code AutoDream）。

        Args:
            idle_seconds: 空闲多少秒后触发。
        """
        if self._autodream_running:
            return
        self._autodream_running = True
        try:
            await asyncio.sleep(idle_seconds)
            if self._mid_term:
                facts = [e for e in self._mid_term if "fact" in e.tags]
                if facts:
                    self.add_long_term(
                        MemoryEntry(
                            tier=MemoryTier.LONG,
                            content=f"AutoDream 抽取 {len(facts)} 条事实",
                            role="autodream",
                            tags=["autodream", "fact"],
                        )
                    )
                    logger.info("AutoDream extracted %d facts", len(facts))
        finally:
            self._autodream_running = False

    # ── Checkpoint 联动 ──────────────────────────────────────────

    def save_checkpoint(self, commit_hash: str = "", role: str = "") -> int:
        """保存 checkpoint（与 AutoGit 联动）。

        Args:
            commit_hash: 关联的 Git commit hash。
            role: 触发角色。

        Returns:
            checkpoint ID。
        """
        state = json.dumps(
            [{"role": m.role, "content": m.content[:100]} for m in self._short_term[-20:]]
        )
        cursor = self._conn.execute(
            "INSERT INTO checkpoints (commit_hash, role, timestamp, state) VALUES (?,?,?,?)",
            (commit_hash, role, time.time(), state),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def list_checkpoints(self) -> list[dict[str, object]]:
        """列出最近的 checkpoint。"""
        rows = self._conn.execute(
            "SELECT id, commit_hash, role, timestamp FROM checkpoints ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()
        return [{"id": r[0], "commit_hash": r[1], "role": r[2], "timestamp": r[3]} for r in rows]

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()
