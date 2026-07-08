"""
角色意图生成 Prompt - 角色只决定"想去哪、想做什么"
对话和互动由世界模拟层处理，不在此阶段产出
"""

from __future__ import annotations

from models.schemas import CharacterState, MemoryEntry, WorldEvent


def _build_affected_section(affected_events: list[str]) -> str:
    """P0: 构建受影响事件差异化提示"""
    if not affected_events:
        return ""
    events_text = "；".join(affected_events[:3])  # 最多 3 个事件
    return f"""
【⚠️ 你被以下事件直接影响】
{events_text}
这些事件可能影响你的情绪和行动。请在你的意图中反映这些事件对你的影响。
"""


def build_character_action_prompt(
    character: CharacterState,
    memories: list[MemoryEntry],
    relationship_summary: str,
    world_events: list[WorldEvent],
    time_label: str,
    scratchpad: str = "",
    world_snapshot: str = "",
    current_scheduled_event: str = "",
    character_arc_outline: str = "",
    current_day: int = 1,
    current_hour: int = 8,
    current_minute: int = 0,
    affected_events: list[str] = None,
) -> list[dict]:
    """
    构建角色意图生成的 prompt。
    角色只输出意图（想去哪、想做什么），不直接产出对话和互动。
    返回 OpenAI 格式的 messages 列表。
    """
    from engine.character import get_character_profile_text
    from engine.memory import format_memories_for_prompt
    from engine.world_event import format_world_events_for_prompt

    world_events_text = format_world_events_for_prompt(world_events)

    # 当前调度事件
    scheduled_section = ""
    if current_scheduled_event:
        scheduled_section = f"""
【当前时段事件】
{current_scheduled_event}
（这个事件正在发生/即将发生，你的行动应该与之相关）
"""
    else:
        scheduled_section = """
【当前时段事件】
（当前没有特定事件，自由行动）
"""

    # 标准化地点列表
    from config import LOCATIONS_DEFAULT
    location_list = "、".join(LOCATIONS_DEFAULT)

    # Scratchpad 部分
    scratchpad_section = ""
    if scratchpad:
        scratchpad_section = f"""
【你的行动计划】
{scratchpad}
"""
    else:
        scratchpad_section = f"""
【你的长期目标】
{character.config.motivation or "（未设定）"}
"""

    # 角色弧光大纲
    arc_section = ""
    if character_arc_outline:
        arc_section = f"""
【角色弧光大纲（你的成长方向参考）】
{character_arc_outline}
你的行动可以自然地朝这个方向推进，但不需要刻意。
"""

    system_prompt = f"""你是一个故事角色模拟器。根据角色设定、你的行动计划和当前情境，决定该角色在这个时间段想做什么。
你只需要输出意图，不需要写对话或与其他角色互动的详细描写。

【角色身份】
{get_character_profile_text(character)}

【当前情境】
时间：{time_label}
当前位置：{character.current_location}
当前心情：{character.current_mood}
身体状态：{character.physical_condition}
{scratchpad_section}
{scheduled_section}
【世界状态快照】
{world_snapshot or "（初始状态）"}

【相关记忆】
{format_memories_for_prompt(memories)}

【与其他角色的关系】
{relationship_summary}

【当前世界事件】
{world_events_text}
{_build_affected_section(affected_events or [])}
{arc_section}
【输出格式】
请输出 JSON：
{{
  "intent": "你这个时间段想做什么（一句话描述，如'去图书室查资料'、'在教室独自复习'）",
  "destination": "你打算去哪里（必须从以下地点中选择：{location_list}。与当前位置相同时填当前位置）",
  "mood": "做这件事时的心情（1-2个词，如'平静'、'焦躁'、'期待'）",
  "thoughts": "你对当前局势的想法或内心独白（1-2句话）",
  "importance": "（根据行动重要性填1-10）",
  "updated_plan": "根据当前局势，你对接下来时段的计划调整（如果没有变化则填null）",
  "next_event_day": "（绝对日期，当前是第{current_day}天，下一个活动在第几天，填数字如1、2）",
  "next_event_hour": "（绝对小时，必须晚于当前时间{current_hour:02d}:{current_minute:02d}，填0-23）",
  "next_event_minute": "（绝对分钟，填0-59）",
  "next_event_duration": "（根据活动性质自行判断持续几分钟，用常识判断，考虑路程时间）"
}}

注意：
- intent 必须符合角色性格和当前计划，只做一件事
- 不要写对话、不要写与其他角色的互动细节（世界系统会自动处理碰撞）
- destination 必须从提供的标准地点列表中选择，不可自创地点名
- importance 表示这个行动的重要性 1-10，根据行动对角色和故事的实际影响判断
- updated_plan 应反映你根据最新局势的打算
- next_event_day/next_event_hour/next_event_minute 都是绝对时间（不是相对偏移），系统会自动校验是否晚于当前时间
- next_event_duration：根据活动的性质和实际情况自行判断，不要用固定范围
  例如：喝杯咖啡30分钟，上两节课90分钟，逛书店60分钟，和朋友吃午饭90分钟
- next_event 描述你下一个时段打算做什么，会被加入你的个人时间表"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请按照要求输出 JSON。next_event 使用绝对时间（day/hour/minute），必须晚于当前时间。"},
    ]

    return messages
