"""上下文组装器 — L0/L1/L2 三层分级上下文。

集中管理上下文组装逻辑，替代散落在 ``Orchestrator._build_prompt``、
``CLIReuseAdapter``、``MemoryManager.assemble_context`` 中的硬编码
``context[-N:]`` / ``content[:N]`` 截断。

三层设计：

- **L0 活跃窗口**：最近若干轮对话，原样保留，最新优先填充预算。
- **L1 关键帧 + 事实抽取**：从更早的历史轮次中识别任务关键帧
  （"请实现登录功能" 这类任务意图），并抽取 "系统→JWT认证" 式事实关系。
- **L2 相关检索**：对历史做字符 bigram 相关性检索，补充与当前任务
  相关的旧轮次（轻量实现，不依赖外部向量库；``sqlite-vss`` 可在
  上层 ``MemoryManager`` 中替换检索后端）。

token 预算：

- 使用 :func:`estimate_tokens`（CJK 每字 ≈1 token，ASCII ≈4 字符/token）
  严格裁剪，预算耗尽即停止。
- **不设"安全地板"** —— 预算为 0 时返回空列表是诚实行为：
  宁可明确告诉调用方"什么都放不下"，也不偷偷超发。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field, replace

from multimind.core.types import Message

__all__ = [
    "DEFAULT_ACTIVE_TURNS",
    "DEFAULT_MAX_FACTS",
    "DEFAULT_MAX_KEYFRAMES",
    "DEFAULT_MAX_RELEVANT",
    "ContextBuilder",
    "ContextStats",
    "Fact",
    "Turn",
    "count_char_classes",
    "estimate_tokens",
    "split_turns",
]

logger = logging.getLogger(__name__)

DEFAULT_ACTIVE_TURNS = 3
"""L0 活跃窗口保留的最近轮次数。"""

DEFAULT_MAX_KEYFRAMES = 5
"""L1 最多注入的关键帧数。"""

DEFAULT_MAX_FACTS = 8
"""L2 最多注入的事实条数。"""

DEFAULT_MAX_RELEVANT = 2
"""L2 最多注入的相关历史轮数。"""

# CJK 统一表意文字 + 全角符号（这些字符按 1 token/字估算）
_CJK_RE = re.compile("[一-鿿㐀-䶿豈-﫿　-〿＀-￯]")

# 显式事实箭头：A→B / A->B / A=>B
_ARROW_RE = re.compile(
    r"([A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿/ .-]{0,24}?)"
    r"\s*(?:→|⇒|->|=>)\s*"
    r"([A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿/ .-]{0,40})"
)

# 任务意图关键词（关键帧识别）
_TASK_KEYWORDS: tuple[str, ...] = (
    # 中文
    "请",
    "帮我",
    "实现",
    "修复",
    "完成",
    "设计",
    "开发",
    "优化",
    "重构",
    "分析",
    "编写",
    "创建",
    "部署",
    "排查",
    "解决",
    # 英文
    "please",
    "implement",
    "fix",
    "create",
    "design",
    "build",
    "refactor",
    "deploy",
    "debug",
)

# 事实关系动词（事实抽取：主语 + 动词 + 宾语）
_FACT_VERBS: tuple[str, ...] = (
    "使用",
    "采用",
    "依赖",
    "需要",
    "通过",
    "基于",
    "调用",
    "连接",
)

# 动词型事实模式：主语(2-12字) + 关系动词 + 宾语(2-24字)
_VERB_FACT_RES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"([A-Za-z0-9_一-鿿]{{2,12}}?){verb}([A-Za-z0-9_一-鿿]{{2,24}})")
    for verb in _FACT_VERBS
)


def count_char_classes(text: str) -> tuple[int, int]:
    """统计文本中的 CJK 字符数与 ASCII 字符数。

    Args:
        text: 输入文本。

    Returns:
        ``(cjk_count, ascii_count)`` 二元组。
        非 ASCII 且非 CJK 的字符按 CJK 计（保守 1 token/字）。
    """
    cjk = 0
    ascii_count = 0
    for ch in text:
        if ord(ch) < 128 and not _CJK_RE.match(ch):
            ascii_count += 1
        else:
            cjk += 1
    return cjk, ascii_count


def estimate_tokens(text: str) -> int:
    """估算文本 token 数：CJK 每字 1 token，ASCII 每 4 字符 1 token。

    Args:
        text: 输入文本。

    Returns:
        估算的 token 数（向上取整）。
    """
    cjk, ascii_count = count_char_classes(text)
    return cjk + math.ceil(ascii_count / 4)


@dataclass(slots=True)
class Turn:
    """一轮对话（一条开场消息 + 后续同轮回复）。

    Attributes:
        messages: 本轮消息（按时间序）。
        index: 轮次序号（从 0 开始）。
    """

    messages: list[Message] = field(default_factory=list)
    index: int = 0

    @property
    def text(self) -> str:
        """本轮全部文本（用于关键词/相关性匹配）。"""
        return "\n".join(m.content for m in self.messages)

    @property
    def tokens(self) -> int:
        """本轮估算 token 数。"""
        return sum(estimate_tokens(m.content) for m in self.messages)

    @property
    def opener(self) -> str:
        """本轮开场角色名。"""
        return self.messages[0].role if self.messages else ""


def split_turns(messages: list[Message]) -> list[Turn]:
    """把消息流切分为对话轮次。

    规则：

    - ``user`` 消息开启新一轮（其后的 agent 回复归入该轮）。
    - ``system`` 消息**单独成轮**（前后消息都不并入）。
    - 其余消息并入当前轮；没有当前轮时自成一轮。

    Args:
        messages: 原始消息流。

    Returns:
        轮次列表（按时间序）。
    """
    turns: list[Turn] = []
    for msg in messages:
        if msg.role == "system" or (
            msg.role == "user" or not turns or turns[-1].opener == "system"
        ):
            turns.append(Turn(messages=[msg], index=len(turns)))
        else:
            turns[-1].messages.append(msg)
    return turns


@dataclass(frozen=True, slots=True)
class Fact:
    """抽取的事实关系（主语 → 宾语）。

    Attributes:
        subject: 主语。
        obj: 宾语。
        relation: 关系动词（显式箭头时为 ``"→"``）。
        source_turn: 来源轮次序号。
    """

    subject: str
    obj: str
    relation: str = "→"
    source_turn: int = -1

    def render(self) -> str:
        """渲染为 ``主语→宾语`` 紧凑形式。"""
        return f"{self.subject}→{self.obj}"


@dataclass(slots=True)
class ContextStats:
    """一次 :meth:`ContextBuilder.build` 的诊断统计。

    Attributes:
        total_turns: 输入消息切分出的总轮数。
        l0_messages: L0 活跃窗口实际注入的消息数。
        l1_keyframes: L1 识别出的关键帧数。
        l2_facts: L2 抽取的事实数。
        l2_relevant: L2 注入的相关历史轮数。
        token_budget: 本次构建的 token 预算。
        tokens_used: 实际使用的 token 数。
    """

    total_turns: int = 0
    l0_messages: int = 0
    l1_keyframes: int = 0
    l2_facts: int = 0
    l2_relevant: int = 0
    token_budget: int = 0
    tokens_used: int = 0


class ContextBuilder:
    """三层分级上下文组装器。

    用法::

        builder = ContextBuilder()
        context = builder.build(messages, query=task, max_tokens=4096)

    Attributes:
        active_turns: L0 活跃窗口保留的最近轮数。
        max_keyframes: L1 最多注入的关键帧数。
        max_facts: L2 最多注入的事实数。
        max_relevant: L2 最多注入的相关历史轮数。
    """

    def __init__(
        self,
        active_turns: int = DEFAULT_ACTIVE_TURNS,
        max_keyframes: int = DEFAULT_MAX_KEYFRAMES,
        max_facts: int = DEFAULT_MAX_FACTS,
        max_relevant: int = DEFAULT_MAX_RELEVANT,
    ) -> None:
        self.active_turns = max(1, active_turns)
        self.max_keyframes = max(0, max_keyframes)
        self.max_facts = max(0, max_facts)
        self.max_relevant = max(0, max_relevant)
        self.last_stats = ContextStats()

    # ── 轮次切分 ────────────────────────────────────────────────

    def split_turns(self, messages: list[Message]) -> list[Turn]:
        """切分轮次（模块级 :func:`split_turns` 的方法形式）。"""
        return split_turns(messages)

    # ── L1：关键帧识别 ──────────────────────────────────────────

    def is_keyframe(self, turn: Turn) -> bool:
        """判断一轮是否为任务关键帧（含任务意图关键词）。"""
        text = turn.text.lower()
        return any(kw in text for kw in _TASK_KEYWORDS)

    def find_keyframes(self, turns: list[Turn]) -> list[Turn]:
        """从历史轮次中找出所有关键帧（保持时间序）。"""
        return [t for t in turns if self.is_keyframe(t)]

    # ── L2：事实抽取 + 相关检索 ─────────────────────────────────

    def extract_facts(self, turns: list[Turn]) -> list[Fact]:
        """从历史轮次中抽取事实关系，按 (主语, 宾语) 去重、保持时间序。"""
        facts: list[Fact] = []
        seen: set[tuple[str, str]] = set()
        for turn in turns:
            for fact in self._facts_from_text(turn.text, turn.index):
                key = (fact.subject, fact.obj)
                if key not in seen:
                    seen.add(key)
                    facts.append(fact)
        return facts

    @staticmethod
    def _facts_from_text(text: str, turn_index: int) -> list[Fact]:
        """从单段文本中抽取事实（显式箭头 + 关系动词两种模式）。"""
        out: list[Fact] = []
        for m in _ARROW_RE.finditer(text):
            subject, obj = m.group(1).strip(), m.group(2).strip()
            if subject and obj:
                out.append(Fact(subject=subject, obj=obj, source_turn=turn_index))
        for pattern in _VERB_FACT_RES:
            for m in pattern.finditer(text):
                subject, obj = m.group(1).strip(), m.group(2).strip()
                if subject and obj and subject != obj:
                    out.append(
                        Fact(
                            subject=subject,
                            obj=obj,
                            relation="verb",
                            source_turn=turn_index,
                        )
                    )
        return out

    def rank_relevant(self, turns: list[Turn], query: str) -> list[Turn]:
        """按与 query 的字符 bigram 重叠度，对历史轮次降序排序。

        字符 bigram 对中英文都有效，且零外部依赖。
        重叠度为 0 的轮次被过滤。
        """
        query_grams = _bigrams(query)
        if not query_grams:
            return []
        scored: list[tuple[float, Turn]] = []
        for turn in turns:
            grams = _bigrams(turn.text)
            if not grams:
                continue
            overlap = len(query_grams & grams) / len(query_grams | grams)
            if overlap > 0:
                scored.append((overlap, turn))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [turn for _, turn in scored]

    # ── 组装 ────────────────────────────────────────────────────

    def build(
        self,
        messages: list[Message],
        *,
        query: str = "",
        max_tokens: int = 8192,
    ) -> list[Message]:
        """组装 L1 + L2 + L0 分层上下文，严格按 token 预算裁剪。

        输出顺序：``[L1 关键帧] [L2 事实] [L2 相关历史] [L0 活跃窗口…]``。
        L0 最新优先填充预算；单条消息超过剩余预算即跳过（诚实裁剪，
        无安全地板）。

        Args:
            messages: 原始消息流。
            query: 当前任务/问题（用于 L2 相关性检索）。
            max_tokens: token 预算（≤0 时返回空列表）。

        Returns:
            组装后的上下文消息列表。每条消息的 ``metadata`` 标注了
            ``layer``（L0/L1/L2）与 ``tokens``（估算值）。
        """
        stats = ContextStats(token_budget=max(0, max_tokens))
        if max_tokens <= 0 or not messages:
            self.last_stats = stats
            return []

        turns = split_turns(messages)
        stats.total_turns = len(turns)
        active = turns[-self.active_turns :]
        history = turns[: len(turns) - len(active)]

        out: list[Message] = []
        budget = max_tokens

        # ── L1 关键帧摘要 ──
        keyframes = self.find_keyframes(history)
        stats.l1_keyframes = len(keyframes)
        if keyframes:
            digest = "；".join(self._turn_headline(t) for t in keyframes[-self.max_keyframes :])
            msg = self._layer_message("[关键帧]", f"历史关键任务: {digest}")
            budget -= self._try_append(out, msg, budget)

        # ── L2 事实 + 相关历史 ──
        facts = self.extract_facts(history)
        stats.l2_facts = len(facts)
        if facts:
            digest = "；".join(f.render() for f in facts[: self.max_facts])
            msg = self._layer_message("[事实]", f"已抽取事实: {digest}")
            budget -= self._try_append(out, msg, budget)

        if query:
            relevant = self.rank_relevant(history, query)[: self.max_relevant]
            stats.l2_relevant = len(relevant)
            for turn in relevant:
                msg = self._layer_message(
                    "[相关历史]",
                    f"{turn.opener}: {self._clip(turn.text, 120)}",
                )
                budget -= self._try_append(out, msg, budget)

        # ── L0 活跃窗口（最新优先填充，保持时间序输出）──
        l0: list[Message] = []
        for turn in reversed(active):
            for msg in reversed(turn.messages):
                cost = estimate_tokens(msg.content)
                if cost > budget:
                    continue
                l0.insert(0, self._annotate(msg, "L0", cost))
                budget -= cost
        stats.l0_messages = len(l0)
        out.extend(l0)

        stats.tokens_used = max_tokens - budget
        self.last_stats = stats
        logger.debug(
            "ContextBuilder: turns=%d L0=%d L1=%d L2(facts=%d,rel=%d) tokens=%d/%d",
            stats.total_turns,
            stats.l0_messages,
            stats.l1_keyframes,
            stats.l2_facts,
            stats.l2_relevant,
            stats.tokens_used,
            stats.token_budget,
        )
        return out

    # ── 内部工具 ────────────────────────────────────────────────

    @staticmethod
    def _annotate(msg: Message, layer: str, tokens: int) -> Message:
        """为消息附加 layer / tokens 元数据（``Message`` 不可变，用 replace）。"""
        return replace(msg, metadata={**msg.metadata, "layer": layer, "tokens": tokens})

    def _layer_message(self, role: str, content: str) -> Message:
        """构造一条合成层消息（L1/L2 摘要）。"""
        layer = {"[关键帧]": "L1", "[事实]": "L2", "[相关历史]": "L2"}.get(role, "L2")
        return Message(
            role=role,
            content=content,
            metadata={"layer": layer, "tokens": estimate_tokens(content)},
        )

    @staticmethod
    def _try_append(out: list[Message], msg: Message, budget: int) -> int:
        """预算允许则追加，返回消耗的 token 数（未追加返回 0）。"""
        raw = msg.metadata.get("tokens")
        cost = raw if isinstance(raw, int) else estimate_tokens(msg.content)
        if cost > budget:
            return 0
        out.append(msg)
        return cost

    @staticmethod
    def _turn_headline(turn: Turn) -> str:
        """关键帧标题：开场角色 + 首条消息截断。"""
        head = turn.messages[0]
        return f"{head.role}: {ContextBuilder._clip(head.content, 40)}"

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        """单行截断（去换行，超限加省略号）。"""
        flat = " ".join(text.split())
        return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _bigrams(text: str) -> set[str]:
    """提取字符 bigram 集合（含单字，避免短文本为空）。"""
    chars = [ch for ch in text.lower() if not ch.isspace()]
    if len(chars) < 2:
        return set(chars)
    return {"".join(chars[i : i + 2]) for i in range(len(chars) - 1)}
