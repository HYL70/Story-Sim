"""
故事初始化 Prompt - 根据玩家提供的背景和角色生成初始状态
无预设冲突，根据 tone（故事基调）动态调整开场氛围
"""

from __future__ import annotations


def build_story_init_prompt(
    setting_description: str,
    character_configs: list[dict],
    tone: str = "",
    character_arc_outline: str = "",
) -> list[dict]:
    """构建故事初始化的 prompt，生成开场白和初始关系"""

    chars_text = []
    for c in character_configs:
        chars_text.append(
            f"- {c.get('name', '?')}（{c.get('role', '?')}）："
            f"{c.get('personality', '')}，动机：{c.get('motivation', '未知')}"
        )

    # 动态氛围指导（根据 tone 调整）
    tone_guidance = ""
    if tone and "欢乐" in tone or "日常" in tone or "喜剧" in tone:
        tone_guidance = "- 开场应营造轻松愉快的氛围，展现角色的日常互动\n- 角色之间的关系可以从有趣的相遇或日常场景出发"
    elif tone and "悬疑" in tone or "暗流" in tone:
        tone_guidance = "- 开场可以暗示潜在的紧张关系或未解之谜\n- 角色之间的关系可以有微妙的张力"
    else:
        tone_guidance = "- 开场应自然地建立故事世界和角色之间的初步联系"

    # 角色弧光大纲
    arc_section = ""
    if character_arc_outline:
        arc_section = f"""
【角色弧光大纲（参考方向）】
{character_arc_outline}
注意：这只是参考方向，开场白中不需要强行推进弧光，只需自然地铺陈即可。
"""

    system_prompt = f"""你是一位故事编剧。根据以下设定和角色，为这个故事写一个开场。

【故事设定】
{setting_description}

【故事基调】{tone or "（未指定）"}

【角色列表】
{chr(10).join(chars_text)}
{arc_section}
请输出 JSON：
{{
  "opening_narrative": "开场叙事（300-500字，介绍故事背景、主要角色和初始氛围）",
  "initial_relationships": [
    {{
      "character_a": "角色A的姓名",
      "character_b": "角色B的姓名",
      "trust": 50,
      "affection": 50,
      "description": "关系描述"
    }}
  ]
}}

要求：
- opening_narrative 要有画面感，用第三人称
- 初始关系应该有差异，不要所有关系都是 50
- 根据角色性格和背景设定合理的初始关系
{tone_guidance}
"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请按照要求输出 JSON，为这个故事写一个开场。"},
    ]
