"""
反思 Prompt - 角色从近期记忆中提炼高层洞察
"""

from __future__ import annotations

from models.schemas import MemoryEntry, CharacterState


def build_reflection_prompt(
    character: CharacterState,
    recent_memories: list[MemoryEntry],
) -> list[dict]:
    """构建角色反思的 prompt"""
    from engine.character import get_character_profile_text

    memories_text = "\n".join(
        f"- 第{m.step}步：{m.description}"
        for m in recent_memories
    )

    system_prompt = f"""{get_character_profile_text(character)}正在回忆近期发生的事情。
请根据角色的性格和视角，从以下近期记忆中提炼出 1-2 条高层洞察或感悟。
同时思考：基于当前局势，角色接下来应该关注什么、做什么？

【近期记忆】
{memories_text}

请输出 JSON：
{{
  "reflections": [
    {{
      "content": "反思/洞察内容（1-2句话，从角色第一人称视角）",
      "importance": 7,
      "tags": ["关键词1", "关键词2"]
    }}
  ],
  "updated_goal": "基于反思后的目标更新（如果没有变化则填null）",
  "suggested_plan": "基于反思后的近期行动建议（如果没有则填null）"
}}

注意：
- 反思必须从角色的性格和立场出发
- 洞察要有深度，不要简单复述记忆
- importance 根据反思深度判断（通常较高 6-10，因为反思本身意味着事件有影响）
- updated_goal 是角色对自己长期目标的重新审视，比如发现新威胁后调整优先级
- suggested_plan 是接下来1-2步的具体打算"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请按照要求输出 JSON，反思要从角色本人视角出发。"},
    ]
