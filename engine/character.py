"""
角色系统 - 角色配置加载、状态管理、角色摘要生成
"""

from __future__ import annotations

import logging
from typing import Optional

from models.schemas import CharacterConfig, CharacterState

logger = logging.getLogger(__name__)


def create_character(config: CharacterConfig) -> CharacterState:
    """根据配置创建角色状态，初始化 Scratchpad"""
    return CharacterState(
        character_id=config.character_id,
        config=config,
        current_location=config.initial_location or config.role,
        current_mood=config.initial_mood,
        physical_condition="精神不错",
        step_count=0,
        long_term_goal=config.motivation or "",
    )


def load_characters_from_json(data: list[dict]) -> list[CharacterConfig]:
    """从 JSON 列表加载角色配置"""
    configs = []
    for item in data:
        config = CharacterConfig.model_validate(item)
        configs.append(config)
    return configs


def get_character_summary(state: CharacterState, all_characters: dict[str, CharacterState]) -> str:
    """
    生成角色的简要摘要，用于注入到其他角色的 prompt 中。
    只包含外部可观察的信息，不包含内心想法。
    """
    c = state.config
    lines = [
        f"姓名：{c.name}",
        f"身份：{c.role}",
        f"位置：{state.current_location}",
        f"状态：{state.current_mood}",
        f"身体：{state.physical_condition}",
    ]
    if state.last_action:
        lines.append(f"最近行动：{state.last_action}")
    return "\n".join(lines)


def get_character_profile_text(state: CharacterState) -> str:
    """
    生成角色完整档案文本，用于注入到该角色自身的 prompt 中。
    """
    c = state.config
    lines = [
        f"姓名：{c.name}",
        f"身份：{c.role}",
        f"年龄：{c.age}",
        f"性格：{c.personality}",
        f"背景：{c.background}",
        f"核心动机：{c.motivation}",
        f"说话风格：{c.speaking_style}",
        f"身体状态：{state.physical_condition}",
    ]
    if c.secret:
        lines.append(f"秘密：{c.secret}")
    if c.fear:
        lines.append(f"恐惧：{c.fear}")
    return "\n".join(lines)


def get_all_characters_brief(states: dict[str, CharacterState]) -> str:
    """
    生成所有角色的简要列表，用于世界事件影响判定。
    """
    lines = []
    for cid, state in states.items():
        c = state.config
        lines.append(
            f"- {c.name}（{c.role}）：位置={state.current_location}，"
            f"心情={state.current_mood}，身体={state.physical_condition}"
        )
    return "\n".join(lines)


def update_character_after_action(
    state: CharacterState,
    action: str,
    new_location: Optional[str] = None,
    mood_change: Optional[str] = None,
    condition_change: str = "",
) -> None:
    """
    角色执行行动后更新状态。
    condition_change: 身体状态变化文字，如"开始头疼"、"恢复精神"，非空时覆盖 physical_condition
    """
    state.last_action = action
    state.step_count += 1

    # 更新 recent_actions（保留最近 N 条）
    import config as cfg
    state.recent_actions.append(action)
    if len(state.recent_actions) > cfg.RECENT_ACTIONS_KEEP:
        state.recent_actions = state.recent_actions[-cfg.RECENT_ACTIONS_KEEP:]

    # 记录移动路径
    if new_location and new_location != state.current_location:
        state.movement_path.append(state.current_location)
        state.movement_path.append(new_location)

    if new_location:
        state.current_location = new_location

    if mood_change:
        state.current_mood = mood_change

    # 身体状态变化（文字覆盖）
    if condition_change:
        state.physical_condition = condition_change


def get_character_scratchpad_text(state: CharacterState) -> str:
    """
    生成角色 Scratchpad 摘要，注入到行动 prompt 中。
    确定性读取，不涉及 LLM 调用。
    """
    lines = []
    if state.long_term_goal:
        lines.append(f"长期目标：{state.long_term_goal}")
    if state.daily_plan:
        lines.append(f"今日计划：{state.daily_plan}")
    if state.current_plan:
        lines.append(f"当前时段计划：{state.current_plan}")
    if state.recent_actions:
        # 用步骤编号展示
        start_step = state.step_count - len(state.recent_actions)
        for i, act in enumerate(state.recent_actions):
            step_num = start_step + i + 1
            lines.append(f"第{step_num}步做了：{act}")
    if state.movement_path:
        path_str = " → ".join(state.movement_path[-6:])  # 最近3次移动
        lines.append(f"移动轨迹：{path_str}")
    return "\n".join(lines)
