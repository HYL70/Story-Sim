"""
系统自动事件生成 Prompt
事件应推动角色成长与互动，而非强制制造矛盾
"""

from __future__ import annotations


def build_auto_event_prompt(
    time_label: str,
    story_setting: str,
    recent_narrative: str,
    relationship_dynamics: str,
    past_events: str,
    character_arc_outline: str = "",
) -> list[dict]:
    """构建系统自动事件生成的 prompt"""

    arc_guidance = ""
    if character_arc_outline:
        arc_guidance = f"""
【角色弧光大纲（参考方向）】
{character_arc_outline}
事件应有助于推动角色沿弧光方向成长，但不需要每一步都直接相关。
"""

    system_prompt = f"""你是一位故事编剧助手。当前故事发展到了 {time_label}，需要你根据故事背景和当前局势，生成一个合理的自动事件来丰富故事内容。

【故事背景】
{story_setting}

【当前故事走向】
{recent_narrative or "（故事刚刚开始）"}

【当前角色关系动态】
{relationship_dynamics or "（暂无特殊动态）"}

【已经发生过的事件】（避免重复）
{past_events or "（暂无）"}
{arc_guidance}
请生成1个自动事件。输出 JSON：
{{
  "event_type": "plot_event 或 environment",
  "description": "事件描述（如'转校生第一天来报到'或'放学后突然下雨'）",
  "rationale": "为什么在这个时刻发生这个事件（基于故事逻辑和角色状态）",
  "expected_impact": "预计对角色的影响（1-2句话，关注角色成长/关系变化/新视角）"
}}

要求：
1. 事件必须符合故事背景和当前时间线
2. 事件应促进角色互动与成长（可以包含小矛盾、误会、合作机会等日常摩擦）
3. 避免与近期已发生的事件重复
4. 事件的烈度适中——不要每一步都是惊天大事，日常中的小波澜同样有意义
5. event_type: plot_event（情节事件，涉及角色互动）或 environment（环境变化，提供新场景或条件）"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请按照要求输出 JSON。"},
    ]
