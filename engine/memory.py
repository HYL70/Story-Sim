"""
记忆系统 - 存储角色记忆，加权检索，反思机制
"""

from __future__ import annotations

import logging
from typing import Optional

import config
from models.schemas import MemoryEntry

logger = logging.getLogger(__name__)


def add_memory(
    memories: list[MemoryEntry],
    step: int,
    timestamp: str,
    description: str,
    importance: int = 5,
    is_reflection: bool = False,
    involved_characters: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
) -> MemoryEntry:
    """
    添加一条记忆，如果超出上限则淘汰最不重要的旧记忆。
    """
    entry = MemoryEntry(
        step=step,
        timestamp=timestamp,
        description=description,
        importance=importance,
        is_reflection=is_reflection,
        involved_characters=involved_characters or [],
        tags=tags or [],
    )
    memories.append(entry)

    # 淘汰逻辑：超出上限时，使用加权评分替代二元排序
    # 反思记忆有固定加分而非绝对优先，避免低重要性反思挤掉高重要性普通记忆
    max_memories = config.MAX_MEMORIES_PER_CHARACTER
    if len(memories) > max_memories:
        REFLECTION_BONUS = 30  # 反思固定加分（相当于普通记忆 3 点 importance 的提升）
        def _score(m: MemoryEntry) -> float:
            s = m.importance * 10.0  # 重要性权重 x10
            s += m.step * 0.5         # 近期性加权
            if m.is_reflection:
                s += REFLECTION_BONUS
            return s
        memories.sort(key=_score, reverse=True)
        del memories[max_memories:]

    return entry


def retrieve_memories(
    memories: list[MemoryEntry],
    current_step: int,
    query_keywords: Optional[list[str]] = None,
    max_results: int = 10,
) -> list[MemoryEntry]:
    """
    加权检索记忆，返回最相关的记忆列表。

    权重公式：
    - 近期性：越近的记忆权重越高（× config.MEMORY_RECENT_WEIGHT）
    - 重要性：直接使用 importance 字段
    - 相关性：关键词匹配数
    """
    if not memories:
        return []

    scored = []
    total_steps = max(current_step, 1)
    keywords = set(k.lower() for k in (query_keywords or []))

    for memory in memories:
        # 近期性得分：越近分越高
        recency = (memory.step / total_steps) * config.MEMORY_RECENT_WEIGHT

        # 重要性得分：归一化到 0-1
        importance_score = memory.importance / 10.0

        # 关键词相关性得分
        relevance = 0.0
        if keywords:
            memory_text = (memory.description + " " + " ".join(memory.tags)).lower()
            matched = sum(1 for k in keywords if k in memory_text)
            relevance = matched / len(keywords) if keywords else 0

        # 反思记忆加权：使用固定 importance floor
        reflection_bonus = config.REFLECTION_IMPORTANCE_FLOOR / 10.0 if memory.is_reflection else 0

        total_score = recency + importance_score + relevance + reflection_bonus
        scored.append((total_score, memory))

    # 按得分排序，取 top N
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:max_results]]


def format_memories_for_prompt(memories: list[MemoryEntry]) -> str:
    """将记忆列表格式化为 prompt 文本"""
    if not memories:
        return "（暂无相关记忆）"

    lines = []
    for m in memories:
        prefix = "【反思】" if m.is_reflection else ""
        importance_tag = f"[重要度:{m.importance}]" if m.importance >= 7 else ""
        lines.append(f"- {prefix}第{m.step}步（{m.timestamp}）：{m.description} {importance_tag}")

    return "\n".join(lines)


def should_reflect(current_step: int, interval: Optional[int] = None) -> bool:
    """判断是否需要触发反思"""
    interval = interval or config.REFLECTION_INTERVAL
    return interval > 0 and current_step % interval == 0


def get_recent_memories(memories: list[MemoryEntry], last_n_steps: int = 6) -> list[MemoryEntry]:
    """获取最近 N 步的记忆（用于反思输入）"""
    if not memories:
        return []
    min_step = max(0, memories[-1].step - last_n_steps) if memories else 0
    return [m for m in memories if m.step >= min_step and not m.is_reflection]
