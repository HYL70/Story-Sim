"""
冲突协调 Prompt - 处理多个角色行动冲突
"""

from __future__ import annotations

from models.schemas import StoryEvent


def build_conflict_resolve_prompt(
    events: list[StoryEvent],
    char_names: dict[str, str],
    story_setting: str,
) -> list[dict]:
    """
    当多个角色的行动存在冲突时，调用 LLM 协调生成合理的事件序列。
    """
    events_text = []
    for e in events:
        name = char_names.get(e.character_id, e.character_id)
        events_text.append(f"- {name}：{e.action}")
        if e.target:
            target_name = char_names.get(e.target, e.target)
            events_text.append(f"  互动目标：{target_name}")
        if e.dialogue:
            events_text.append(f'  对话："{e.dialogue}"')

    system_prompt = f"""你是一位故事协调员。以下多个角色在同一时间段产生了行动，请判断这些行动是否存在冲突，并协调生成最终的事件序列。

【故事背景】
{story_setting}

【原始行动】
{chr(10).join(events_text)}

【冲突判断标准】
- 时间冲突：多个角色需要同一资源且无法同时使用（如同一时间都需要使用同一个场地）
- 空间冲突：角色在物理上不可能同时出现在两个地方（如一个在图书馆一个在体育馆，却被安排对话）
- 逻辑冲突：行动之间存在因果矛盾（如A的行动假设B在场，但B的实际行动是离开）
- 注意：角色在同一地点偶遇不属于冲突，而是正常的社交互动

【任务】
1. 按上述标准判断行动之间是否存在冲突
2. 如果存在冲突，调整行动顺序或修改部分行动，使其合理
3. 如果没有冲突，保持原样
4. 可以增加一些连接性事件使叙事更流畅

请输出 JSON：
{{
  "has_conflict": true/false,
  "conflict_description": "冲突描述（如果没有则为空字符串）",
  "resolved_events": [
    {{
      "character_id": "角色ID",
      "action": "最终行动描述",
      "dialogue": "说的话（null如果没有）",
      "internal_thought": "内心独白（null如果没有）",
      "target": "目标角色ID（null如果没有）",
      "mood_change": "心情变化",
      "importance": "重要性1-10"
    }}
  ]
}}

注意：resolved_events 中每个角色必须有且仅有一个事件。"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请按照要求输出 JSON。"},
    ]
