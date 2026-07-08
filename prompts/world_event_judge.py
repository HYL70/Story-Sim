"""
世界事件影响判定 Prompt
"""

from __future__ import annotations


def build_world_event_judge_prompt(
    event_description: str,
    event_type: str,
    story_setting: str,
    characters_brief: str,
    recent_narrative: str,
) -> list[dict]:
    """构建世界事件影响判定的 prompt"""

    type_label = "大事件" if event_type == "plot_event" else "环境变化"

    system_prompt = f"""有一个世界事件即将发生，需要判断它对故事中各角色的影响。

【事件描述】
类型：{type_label}
描述：{event_description}

【故事背景】
{story_setting}

【当前所有角色状态】
{characters_brief}

【已发生的故事摘要】
{recent_narrative or "（故事刚刚开始）"}

请判断这个事件对每个角色的影响。输出 JSON：
{{
  "event_impact": "事件对整体剧情的影响概述（1-2句话）",
  "affected_characters": [
    {{
      "character_id": "角色ID",
      "would_be_involved": true,
      "how_affected": "该角色会如何被卷入或受影响（1-2句话）",
      "likely_reaction": "根据性格可能做出的反应倾向"
    }}
  ],
  "unaffected_characters": [
    {{
      "character_id": "角色ID",
      "would_be_involved": false,
      "reason": "为何不受影响"
    }}
  ]
}}

注意：
- 判断基于角色性格、当前位置、当前目标和人物关系
- 不是所有角色都需要被卷入
- 大事件（如宴会）通常影响范围大，环境变化（如天气）主要影响在场角色"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请按照要求输出 JSON。"},
    ]
