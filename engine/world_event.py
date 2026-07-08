"""
世界事件系统 - 管理玩家事件和系统自动事件
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import config
from models.schemas import WorldEvent, EventType, EventSource

logger = logging.getLogger(__name__)


def add_player_event(
    pending_events: list[WorldEvent],
    event_type: str,
    description: str,
    current_step: int,
    active_until_step: Optional[int] = None,
) -> tuple[Optional[WorldEvent], str]:
    """
    玩家添加一个世界事件到待处理队列。
    事件将在下一个时间步生效。
    返回 (event_or_None, message)：去重失败时 event 为 None。
    """
    stripped = description.strip()

    # 精确去重：待处理队列中已有完全相同描述的事件
    for existing in pending_events:
        if existing.description.strip() == stripped:
            logger.info(f"事件去重拦截: [{event_type}] {stripped}")
            return None, f"⚠️ 该事件已存在待处理队列中，请勿重复添加。"

    event = WorldEvent(
        event_type=EventType.PLOT_EVENT if event_type == "plot_event" else EventType.ENVIRONMENT,
        description=stripped,
        source=EventSource.PLAYER,
        triggered_at_step=current_step,
        active_until_step=active_until_step,
    )
    pending_events.append(event)
    logger.info(f"玩家添加事件: [{event_type}] {stripped}")
    return event, format_event_for_display(event)


def get_active_events(
    active_events: list[WorldEvent],
    current_step: int,
) -> list[WorldEvent]:
    """获取当前生效的世界事件"""
    return [
        e for e in active_events
        if e.active_until_step is None or e.active_until_step >= current_step
    ]


def process_pending_events(
    active_events: list[WorldEvent],
    pending_events: list[WorldEvent],
    current_step: int,
) -> list[WorldEvent]:
    """
    将待处理事件移入活跃事件列表。
    默认玩家事件持续 5 步（约 1-2 天）。
    返回本次新激活的事件。
    """
    newly_active = []
    for event in pending_events[:]:
        event.triggered_at_step = current_step
        if event.active_until_step is None:
            # 玩家大事件持续 5 步，环境变化持续 3 步
            if event.event_type == EventType.PLOT_EVENT:
                event.active_until_step = current_step + 5
            else:
                event.active_until_step = current_step + 3
        active_events.append(event)
        newly_active.append(event)
        pending_events.remove(event)
    return newly_active


def should_trigger_auto_event(steps_since_last: int) -> bool:
    """判断是否需要触发系统自动事件"""
    return steps_since_last >= config.AUTO_EVENT_INTERVAL


def format_world_events_for_prompt(events: list[WorldEvent]) -> str:
    """将活跃的世界事件格式化为 prompt 文本"""
    if not events:
        return "（当前没有特殊事件）"

    lines = []
    for e in events:
        source_tag = "[玩家设定]" if e.source == EventSource.PLAYER else "[系统事件]"
        lines.append(f"- {source_tag} {e.description}")
        if e.impact_description:
            lines.append(f"  影响：{e.impact_description}")
    return "\n".join(lines)


def get_past_events_text(active_events: list[WorldEvent], char_names: dict[str, str] = None) -> str:
    """获取已发生事件列表（用于自动事件生成时避免重复）"""
    if not active_events:
        return "（暂无）"
    lines = []
    for e in active_events:
        lines.append(f"- {e.description}")
    return "\n".join(lines)


def format_event_for_display(event: WorldEvent) -> str:
    """格式化事件用于前端显示"""
    source = "玩家" if event.source == EventSource.PLAYER else "系统"
    type_name = "大事件" if event.event_type == EventType.PLOT_EVENT else "环境"
    return f"[{source}{type_name}] {event.description}"
