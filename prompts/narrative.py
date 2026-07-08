"""
叙事编排 Prompt - 将互动记录编排为故事文本
支持 Interaction 数据，风格由玩家在初始化时设定（StorySetting.tone）
"""

from __future__ import annotations

from typing import Optional

from models.schemas import Interaction, WorldEvent


def build_narrative_prompt(
    story_setting: str,
    time_label: str,
    world_snapshot: str,
    world_events: list[WorldEvent],
    interactions: list[Interaction],
    char_names: dict[str, str],
    story_summary: str = "",
    foreshadow_content: str = "",
    char_profiles: Optional[list[dict]] = None,
    narrative_style: str = "",
    loc_groups: Optional[dict[str, list[Interaction]]] = None,
) -> list[dict]:
    """构建叙事编排的 prompt（风格由 narrative_style 参数决定）
    
    P1-5: 接受 loc_groups 参数，在 prompt 中按场景提供时序指导。
    所有场景一次性传给 LLM，保证时序正确性和场景间过渡质量。
    """
    from engine.world_event import format_world_events_for_prompt

    world_events_text = format_world_events_for_prompt(world_events)

    # 格式化互动记录
    interactions_text = []
    for ia in interactions:
        name = char_names.get(ia.character_id, ia.character_id)
        parts = [f"{name}：{ia.actual_action}"]
        if ia.destination and ia.destination != ia.location:
            parts.append(f"（前往{ia.destination}）")
        if ia.internal_thought:
            parts.append(f"（{ia.internal_thought}）")
        # 附加对话内容
        for enc in ia.encounters:
            if enc.dialogue:
                other_id = enc.character_b if enc.character_a == ia.character_id else enc.character_a
                other_name = char_names.get(other_id, other_id)
                parts.append(f"\n  与{other_name}的对话：")
                for d in enc.dialogue:
                    parts.append(f"  {d.get('speaker', '?')}：{d.get('line', '')}")
            if enc.outcome:
                parts.append(f"（{enc.outcome}）")
        interactions_text.append("".join(parts))

    involved_names = ", ".join(set(char_names.get(ia.character_id, ia.character_id) for ia in interactions))

    # 场景概览（不作为写作格式约束，仅提供信息）
    scene_info = ""
    if loc_groups:
        scene_lines = ["【当前活跃的位置与角色】"]
        for loc, loc_ias in loc_groups.items():
            involved = [char_names.get(ia.character_id, ia.character_id) for ia in loc_ias]
            scene_lines.append(f"  {loc}：{'、'.join(involved)}")
        scene_info = "\n".join(scene_lines) + "\n"

    # 角色卡一览表（防混淆）— 包含完整信息
    char_profile_section = ""
    if char_profiles:
        profile_lines = ["【角色卡一览表 — 严禁混淆！】"]
        for p in char_profiles:
            parts = [f"- {p['name']}：{p['gender']}，{p['role']}，{p['personality']}"]
            if p.get('background'):
                parts.append(f"，背景：{p['background']}")
            if p.get('speaking_style'):
                parts.append(f"，说话风格：{p['speaking_style']}")
            profile_lines.append("".join(parts))
        profile_lines.append("⚠ 以上信息为绝对事实。叙述中严禁搞混任何角色的姓名、性别、身份/职位、性格。如有疑问以此表为准。")
        char_profile_section = "\n".join(profile_lines) + "\n"

    # 动态风格前缀（根据玩家设定的 narrative_style 生成）
    if narrative_style:
        style_prefix = f"""【写作风格要求 — {narrative_style}】
你是{narrative_style}风格的故事叙述者。请根据以下风格规则写作：
- 用第三人称叙事，文笔流畅有画面感
- 对话简短自然，符合角色性格和说话风格
- 用动作、环境、感官细节代替直接心理说明
- 段落之间过渡自然，不突然跳跃
"""
    else:
        style_prefix = """【写作风格要求】
你是一位擅长群像叙事的小说家。请用以下基本规则写作：
- 用第三人称叙事，文笔流畅有画面感
- 对话简短自然，符合角色性格和说话风格
- 用动作、环境、感官细节代替直接心理说明
- 段落之间过渡自然，不突然跳跃
"""

    system_prompt = f"""{style_prefix}

你正在将以下角色互动编排为连贯的故事段落。
只描写本段提供的角色（{involved_names}），不要引入或描写其他角色。
{char_profile_section}
{scene_info}【⚠️ 时间约束——必须严格遵守】
当前时间是：{time_label}
- 叙事中涉及的时间场景必须与此一致
- 不要在叙事里写出与此不符的时间点（如"三点五十七分"、"下午两点"等）
- 如需提及时间，只用模糊描述（"此刻"、"这个时候"）或不提时间

【故事背景】
{story_setting}

【故事进展摘要】
{story_summary or "（故事刚刚开始，这是第一段叙事）"}

{world_snapshot}

【本时间段的活跃世界事件】
{world_events_text}

【本时间段的互动记录（只写这些人）】
{chr(10).join(interactions_text)}

【输出格式】
请输出 JSON：
{{
  "narrative": "叙事文本（400-700字）"
}}

【写作要求 — 自然小说型叙事】
1. 从故事进展摘要自然衔接，不要突然跳跃或重复已有内容
2. 按小说家的方式写作——自由选择视角切入，不必按地点或时间顺序逐一叙述
3. 如果互动记录中有对话，自然地融入叙事，用引号标注
4. 将世界事件和角色状态变化自然融入叙事，不要单独列出
5. 段落之间过渡自然，场景切换用环境描写或视角转换来实现，不要用【场景X：位置】这类标记
6. 叙事应有主次——重要的互动详写，日常的细节一笔带过或跳过
7. 结尾自然收束
8. 不要输出标题或元数据，narrative 字段只输出纯叙事文本
9. 如果角色卡一览表存在，必须严格遵照其中的角色信息，不得擅自更改
10. **绝对禁止**混淆角色姓名、性别、身份/职位
11. 角色档案中的 fear / secret / background 是不可违反的设定
12. 如果本步与上一步场景相似，聚焦于新细节

请输出 JSON。"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请按照要求输出 JSON。"},
    ]
