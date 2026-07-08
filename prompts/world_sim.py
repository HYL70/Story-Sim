"""
世界模拟 Prompt - 碰撞后生成角色之间的对话
只在关系阈值触发对话时调用 LLM
注入角色关系数据和说话风格以提升对话质量
"""

from __future__ import annotations

from typing import Optional

from models.schemas import CharacterConfig, CharacterState


def build_dialogue_prompt(
    char_a: CharacterState,
    char_b: CharacterState,
    encounter_location: str,
    time_label: str,
    intent_a: str = "",
    intent_b: str = "",
    relationship_text: str = "",
) -> list[dict]:
    """
    构建对话生成的 prompt。
    两个角色在同一地点相遇，根据各自的意图、关系和说话风格生成自然对话。
    """
    from engine.character import get_character_profile_text

    # 角色关系段
    relationship_section = ""
    if relationship_text:
        relationship_section = f"""
【两人关系】
{relationship_text}
"""
    else:
        relationship_section = """
【两人关系】
（暂无特殊关系记录，按陌生人或点头之交处理）
"""

    system_prompt = f"""你是一位擅长角色对话的编剧。根据两个角色的设定、关系和各自的意图，生成他们在{encounter_location}自然发生的对话。

【当前时间】{time_label}

【角色A】
{get_character_profile_text(char_a)}
当前位置：{char_a.current_location}
当前心情：{char_a.current_mood}
此处的意图：{intent_a or "（未特别说明）"}

【角色B】
{get_character_profile_text(char_b)}
当前位置：{char_b.current_location}
当前心情：{char_b.current_mood}
此处的意图：{intent_b or "（未特别说明）"}
{relationship_section}
【输出格式】
请输出 JSON：
{{
  "dialogue": [
    {{"speaker": "角色名", "line": "台词"}},
    {{"speaker": "角色名", "line": "台词"}},
    ...
  ],
  "outcome": "对话后的结果或氛围变化（一句话描述，如'远山借到了资料，但感觉到藤原在观察他'）",
  "relationship_delta": {{"trust": 0, "affection": 0}}
}}

要求：
1. 对话要自然，符合各自的说话风格（如温婉、尖锐、话少等）
2. 对话应反映两个角色之间的关系（亲密/冷淡/疏远等）和当前心情
3. 句数根据场景需要灵活调整（日常寒暄2-3句，关键场景可到6-8句）
4. 不要写旁白或心理描写，只写对话
5. outcome 简短描述对话带来的实际影响
6. relationship_delta 表示对话导致双方关系的变化，范围 -10~+10：
   - 正面互动（鼓励/安慰/分享秘密）→ trust +1~3, affection +2~5
   - 负面互动（争吵/误解/冷漠）→ trust -1~5, affection -2~5
   - 日常寒暄 → trust 0, affection 0
7. 【一致性约束】角色在当前时间步可能正在或即将与其他人互动。请确保其在本段对话中的态度、心情和言论与角色设定一致，不与其在当前时间步的其他交流产生明显矛盾。"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请按照要求输出 JSON。"},  # N6: user trigger 提高 JSON 遵守率
    ]
