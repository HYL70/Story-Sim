"""
世界模拟层 - 碰撞检测 + 对话生成 + 旁观判定
纯规则碰撞检测（不调 LLM），仅在需要对话生成时调 LLM
"""

from __future__ import annotations

import logging
from typing import Optional

from models.schemas import (
    Encounter, EncounterType, Interaction,
    CharacterState, Relationship,
)
from engine import llm_client
from engine import relationship as rel_module
from prompts import world_sim as prompt_world_sim

import config

logger = logging.getLogger(__name__)


def _cross_validate_intents(
    intents: dict[str, dict],
    character_states: dict[str, CharacterState],
    characters: dict,
) -> dict[str, str]:
    """
    P1-5: 意图交叉校验 — 检测"目标指向型意图"（找/见/等/约 + 角色名）
    如果角色 A 的意图指向角色 B，但 B 的 destination ≠ A 的 destination → 意图失败
    返回 {cid: failure_reason}，仅包含失败的 cid
    """
    failures: dict[str, str] = {}
    char_names = {cid: cfg.name for cid, cfg in characters.items()}
    # 构建名字→cid 反向映射
    name_to_cid = {cfg.name: cid for cid, cfg in characters.items()}

    # 目标指向型关键词
    target_keywords = ["找", "见", "等", "约", "遇到", "见面"]

    for cid_a, intent_a in intents.items():
        dest_a = intent_a.get("destination", "")
        intent_text = intent_a.get("intent", "")
        # 检查是否包含目标指向关键词 + 角色名
        target_cid = None
        for kw in target_keywords:
            for name, cid_b in name_to_cid.items():
                if cid_b == cid_a:
                    continue
                if kw in intent_text and name in intent_text:
                    target_cid = cid_b
                    break
            if target_cid:
                break

        if not target_cid:
            continue

        # 检查目标角色的 destination
        intent_b = intents.get(target_cid, {})
        dest_b = intent_b.get("destination", "")
        state_b = character_states.get(target_cid)
        current_b = state_b.current_location if state_b else ""

        # 如果 B 的目的地与 A 的目的地不同，且 B 不是留在原地 → 意图失败
        if dest_b and dest_b != dest_a and dest_b != current_b:
            name_a = char_names.get(cid_a, cid_a)
            name_b = char_names.get(target_cid, target_cid)
            failures[cid_a] = f"意图失败：{name_a}打算去{dest_a}找{name_b}，但{name_b}去了{dest_b}"
            logger.info(f"[意图校验] {failures[cid_a]}")

    return failures


def detect_encounters(
    intents: dict[str, dict],
    relationships: list[Relationship],
    character_states: dict[str, CharacterState],
    characters: dict,
) -> list[Encounter]:
    """
    碰撞检测（纯规则，不调 LLM）。
    按目标位置分组，检查同位置角色之间的关系，判定碰撞类型。

    Args:
        intents: {character_id: {"intent": ..., "destination": ...}}
        relationships: 关系列表
        character_states: 角色状态字典
        characters: 角色配置字典

    Returns:
        碰撞事件列表
    """
    # 按目标位置分组
    location_groups: dict[str, list[str]] = {}
    for cid, intent_data in intents.items():
        dest = intent_data.get("destination", "")
        if not dest:
            # 没有移动意图，使用当前位置
            state = character_states.get(cid)
            dest = state.current_location if state else ""
        if dest not in location_groups:
            location_groups[dest] = []
        location_groups[dest].append(cid)

    # output-problems #6: 纳入非活跃角色 — 同位置的角色即使不在 intents 中也参与碰撞
    for cid, state in character_states.items():
        if cid in intents:
            continue  # 已在分组中
        loc = state.current_location
        if loc and loc in location_groups:
            location_groups[loc].append(cid)
            logger.debug(f"[碰撞] 非活跃角色 {cid} 纳入 {loc} 分组")

    # 构建关系查询表 {frozenset(a,b): Relationship}
    rel_map: dict[frozenset, Relationship] = {}
    for rel in relationships:
        key = frozenset([rel.character_a, rel.character_b])
        rel_map[key] = rel

    encounters: list[Encounter] = []

    for loc, cids in location_groups.items():
        if len(cids) < 2:
            continue

        # 对同位置的所有角色对进行碰撞判定
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                a_id, b_id = cids[i], cids[j]
                key = frozenset([a_id, b_id])
                rel = rel_map.get(key)

                encounter_type = _judge_encounter_type(rel)
                if encounter_type == EncounterType.PASSING:
                    continue  # 擦肩而过，不产生碰撞

                encounter = Encounter(
                    character_a=a_id,
                    character_b=b_id,
                    location=loc,
                    encounter_type=encounter_type,
                    observer="",  # 由后续流程填充
                )

                if encounter_type == EncounterType.OBSERVATION:
                    # 中等关系：一方观察到另一方，需要判断谁是观察者
                    # 规则：主动移动的一方是观察者
                    a_state = character_states.get(a_id)
                    b_state = character_states.get(b_id)
                    a_dest = intents.get(a_id, {}).get("destination", "")
                    b_dest = intents.get(b_id, {}).get("destination", "")
                    a_moving = a_dest and a_dest != (a_state.current_location if a_state else "")
                    b_moving = b_dest and b_dest != (b_state.current_location if b_state else "")
                    if a_moving and not b_moving:
                        encounter.observer = a_id
                    elif b_moving and not a_moving:
                        encounter.observer = b_id
                    else:
                        encounter.observer = a_id  # 默认

                encounters.append(encounter)
                logger.info(
                    f"碰撞检测: {characters.get(a_id, type('', (), {'name': a_id})).name}"
                    f" vs {characters.get(b_id, type('', (), {'name': b_id})).name}"
                    f" @ {loc} → {encounter_type.value}"
                )

    return encounters


def _judge_encounter_type(rel: Optional[Relationship]) -> EncounterType:
    """根据关系判定碰撞类型"""
    if rel is None:
        return EncounterType.PASSING

    trust = rel.trust
    affection = rel.affection

    # 极端关系 → 对话
    if (trust > config.ENCOUNTER_EXTREME_THRESHOLD
            or affection > config.ENCOUNTER_EXTREME_THRESHOLD
            or trust < 100 - config.ENCOUNTER_EXTREME_THRESHOLD
            or affection < 100 - config.ENCOUNTER_EXTREME_THRESHOLD):
        return EncounterType.DIALOGUE

    # 中等关系（信任和好感都在 PASSING~EXTREME 之间）→ 旁观
    if (trust >= config.ENCOUNTER_PASSING_THRESHOLD
            and affection >= config.ENCOUNTER_PASSING_THRESHOLD):
        return EncounterType.OBSERVATION

    # 无关系记录/弱关系 → 擦肩
    return EncounterType.PASSING


async def generate_dialogue(
    encounter: Encounter,
    character_states: dict[str, CharacterState],
    characters: dict,
    intents: dict[str, dict],
    time_label: str,
    relationships: list[Relationship] = None,
) -> Encounter:
    """
    为 DIALOGUE 类型的碰撞生成对话（调 LLM）。
    修改 encounter 的 dialogue 和 outcome 字段。
    """
    a_state = character_states.get(encounter.character_a)
    b_state = character_states.get(encounter.character_b)
    if not a_state or not b_state:
        return encounter

    intent_a = intents.get(encounter.character_a, {}).get("intent", "")
    intent_b = intents.get(encounter.character_b, {}).get("intent", "")

    # 构建两个角色之间的关系文本
    relationship_text = ""
    if relationships:
        char_names = {cid: cfg.name for cid, cfg in characters.items()}
        for r in relationships:
            a_match = (r.character_a == encounter.character_a and r.character_b == encounter.character_b)
            b_match = (r.character_a == encounter.character_b and r.character_b == encounter.character_a)
            if a_match or b_match:
                name_a = char_names.get(r.character_a, r.character_a)
                name_b = char_names.get(r.character_b, r.character_b)
                trust_desc = rel_module._describe_value(r.trust, "信任", ["极度不信任", "不信任", "一般", "信任", "极度信任"])
                affection_desc = rel_module._describe_value(r.affection, "好感", ["极度厌恶", "冷淡", "普通", "亲近", "深爱"])
                relationship_text = f"{name_a} ↔ {name_b}：{affection_desc}，{trust_desc}"
                if r.description:
                    relationship_text += f"（{r.description}）"
                break

    messages = prompt_world_sim.build_dialogue_prompt(
        char_a=a_state,
        char_b=b_state,
        encounter_location=encounter.location,
        time_label=time_label,
        intent_a=intent_a,
        intent_b=intent_b,
        relationship_text=relationship_text,
    )

    try:
        response = await llm_client.chat_async(messages, json_mode=True)
        result = llm_client.parse_json_response(response)

        encounter.dialogue = result.get("dialogue", [])
        encounter.outcome = result.get("outcome", "")
        # P0 关系闭环: 保存完整结果到模型字段（含 relationship_delta）
        encounter.dialogue_data = result
        logger.info(f"对话生成完成: {encounter.character_a} vs {encounter.character_b}, {len(encounter.dialogue)} 句")
    except Exception as e:
        logger.error(f"对话生成失败: {e}")
        encounter.outcome = "两人短暂对视后各自离开。"

    return encounter


def build_interactions(
    intents: dict[str, dict],
    encounters: list[Encounter],
    character_states: dict[str, CharacterState],
) -> list[Interaction]:
    """
    将意图和碰撞结果组合为 Interaction 列表。
    """
    interactions: list[Interaction] = []

    for cid, intent_data in intents.items():
        state = character_states.get(cid)
        if not state:
            continue

        dest = intent_data.get("destination") or ""
        actual_action = intent_data.get("intent") or ""

        # 找到涉及该角色的碰撞
        char_encounters = [
            e for e in encounters
            if e.character_a == cid or e.character_b == cid
        ]

        # 如果有对话碰撞，更新 actual_action
        dialogue_encounters = [e for e in char_encounters if e.encounter_type == EncounterType.DIALOGUE]
        if dialogue_encounters:
            outcomes = [e.outcome for e in dialogue_encounters if e.outcome]
            if outcomes:
                actual_action += "；" + "；".join(outcomes)

        interaction = Interaction(
            character_id=cid,
            intent=intent_data.get("intent") or "",
            destination=dest,
            actual_action=actual_action,
            location=dest or state.current_location,
            encounters=char_encounters,
            mood_change=intent_data.get("mood_change") or "",
            condition_change=intent_data.get("condition_change") or "",
            importance=intent_data.get("importance") or 5,
            internal_thought=intent_data.get("thoughts") or "",
        )
        interactions.append(interaction)

    return interactions
