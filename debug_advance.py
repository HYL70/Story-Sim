"""
单步推进诊断脚本
不经过 Gradio，直接在命令行运行一个完整的时间步，记录所有中间数据到日志文件。

用法：
    python debug_advance.py

日志输出到 story-sim/debug_log.txt，同时显示在控制台。
"""

import sys
import os
import json
import logging
import asyncio
import traceback
from pathlib import Path
from datetime import datetime

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from models.schemas import (
    StorySetting, CharacterConfig, StoryState, StoryEvent, WorldEvent,
)
from engine import llm_client, character, memory, relationship, world_event
from engine.llm_client import chat, chat_async, parse_json_response
from prompts import (
    character_action as prompt_action,
    narrative as prompt_narrative,
    conflict_resolve as prompt_conflict,
    reflection as prompt_reflection,
    world_event_judge as prompt_event_judge,
    story_init as prompt_init,
)

# ============================================================
# 日志配置：同时输出到控制台和文件
# ============================================================
LOG_FILE = PROJECT_ROOT / "debug_log.txt"

logger = logging.getLogger("debug_advance")
logger.setLevel(logging.DEBUG)
logger.handlers.clear()

# 文件 handler - DEBUG 级别，记录一切
file_handler = logging.FileHandler(str(LOG_FILE), mode="w", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
))
logger.addHandler(file_handler)

# 控制台 handler - INFO 级别，关键信息
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(console_handler)

# 让子模块也输出到这个 logger
logging.getLogger("engine").handlers = logger.handlers
logging.getLogger("engine.story_engine").handlers = logger.handlers
logging.getLogger("engine.llm_client").handlers = logger.handlers


# ============================================================
# 预设数据
# ============================================================
PRESET_CHARACTERS = [
    {
        "name": "苏婉",
        "role": "婉嫔",
        "age": 22,
        "gender": "女",
        "personality": "表面温婉大方，实则心思缜密，善于隐忍，但一旦出手绝不留情",
        "background": "出身江南书香门第，父亲为翰林院侍读学士，因家族获罪被送入宫中",
        "motivation": "洗清家族冤屈，在后宫站稳脚跟，最终保护家人平安",
        "speaking_style": "语气柔和，说话留三分，常用隐喻",
        "secret": "入宫前已与青梅竹马私定终身",
        "fear": "被揭发身世秘密后连累整个家族",
        "initial_location": "永和宫",
        "initial_mood": "平静中带着一丝警觉",
    },
    {
        "name": "李贵妃",
        "role": "贵妃",
        "age": 28,
        "gender": "女",
        "personality": "傲慢强势，城府极深，手段毒辣但不失分寸，极度护短",
        "background": "将门之女，兄长手握兵权，入宫八年育有一子",
        "motivation": "让自己的儿子成为太子，掌控后宫大权",
        "speaking_style": "居高临下，言辞锋利，喜怒不形于色",
        "secret": "暗中与朝中大臣勾结干政",
        "fear": "失去皇帝宠爱和儿子太子的位置",
        "initial_location": "翊坤宫",
        "initial_mood": "从容",
    },
    {
        "name": "陈贵人",
        "role": "贵人",
        "age": 18,
        "gender": "女",
        "personality": "天真烂漫但直觉敏锐，不懂得宫廷规则但经常歪打正着",
        "background": "地方小官之女，因容貌出众被选入宫，对宫廷斗争一无所知",
        "motivation": "想找到真心对自己好的人，过安稳日子",
        "speaking_style": "说话直来直去，经常无意中说出关键信息",
        "secret": "其实非常聪慧，装傻是为了保护自己",
        "fear": "被别人利用后抛弃",
        "initial_location": "钟粹宫",
        "initial_mood": "好奇又紧张",
    },
    {
        "name": "皇后赵氏",
        "role": "皇后",
        "age": 32,
        "gender": "女",
        "personality": "端庄持重，处事公允但内心疲惫，对权力已无太多执念但必须维护皇后面子",
        "background": "名门望族嫡女，入宫十年，育有一女，夫妻关系冷淡",
        "motivation": "维持后宫秩序，保护女儿的平安，在各方势力间保持平衡",
        "speaking_style": "沉稳得体，言简意赅，偶尔流露出疲惫",
        "secret": "早已知道皇帝宠爱新妃的事实，但选择装作不知",
        "fear": "女儿被卷入宫廷斗争",
        "initial_location": "坤宁宫",
        "initial_mood": "平静",
    },
]


# ============================================================
# 诊断函数
# ============================================================

def log_separator(title: str):
    logger.info("=" * 60)
    logger.info(f"  {title}")
    logger.info("=" * 60)


def log_data(label: str, data):
    """安全地记录任意数据（dict/list 会格式化为 JSON）"""
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception:
        text = str(data)
    logger.debug(f"[{label}]\n{text}")


def log_llm_io(label: str, messages: list[dict], raw_response: str, parsed: dict):
    """记录 LLM 调用的输入和输出"""
    logger.debug(f"[{label}] === 发送给 LLM 的 Messages ===")
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # 只记录前 500 字，避免日志过大
        if len(content) > 500:
            content = content[:500] + "\n... (截断，共 {} 字)".format(len(content))
        logger.debug(f"  [{role}]: {content}")

    logger.debug(f"[{label}] === LLM 原始返回 (前 800 字) ===")
    logger.debug(raw_response[:800])

    logger.debug(f"[{label}] === 解析后的 JSON ===")
    try:
        logger.debug(json.dumps(parsed, ensure_ascii=False, indent=2, default=str))
    except Exception:
        logger.debug(str(parsed))


async def debug_advance():
    """运行一次完整的单步推进，记录所有中间数据"""

    log_separator("诊断开始")

    # ============================
    # Phase 0: 初始化故事
    # ============================
    log_separator("Phase 0: 初始化故事")

    setting = StorySetting(
        title="凤鸣宫",
        era="架空永平年间",
        location="皇宫",
        description="永平帝即位三年，朝堂暗流涌动。后宫之中，贵妃李氏独大，皇后赵氏名存实亡。",
        tone="暗流涌动",
        starting_date="永平三年 春",
    )

    characters = [CharacterConfig.model_validate(c) for c in PRESET_CHARACTERS]

    # 打印角色 ID 映射（关键调试信息）
    id_map = {}
    for c in characters:
        id_map[c.character_id] = c.name
        logger.info(f"  角色注册: ID={c.character_id}  名字={c.name}")

    # 创建状态
    state = StoryState(
        setting=setting,
        characters={c.character_id: c for c in characters},
    )
    for c in characters:
        state.character_states[c.character_id] = character.create_character(c)
        state.memories[c.character_id] = []

    char_ids = list(state.characters.keys())
    char_names = {cid: cfg.name for cid, cfg in state.characters.items()}
    name_to_id = {name: cid for cid, name in char_names.items()}

    state.relationships = relationship.init_relationships(char_ids)

    # 调用 LLM 生成开场白
    chars_data = [c.model_dump() for c in characters]
    init_messages = prompt_init.build_story_init_prompt(
        setting_description=f"{setting.era} - {setting.location}\n{setting.description}",
        character_configs=chars_data,
    )
    init_raw = chat(init_messages, max_tokens=4096)
    init_parsed = parse_json_response(init_raw)
    log_llm_io("init_story", init_messages, init_raw, init_parsed)

    opening = init_parsed.get("opening_narrative", "故事开始了...")
    logger.info(f"  开场白: {opening[:200]}...")

    # 应用初始关系
    for rel_data in init_parsed.get("initial_relationships", []):
        name_a = rel_data.get("character_a", "")
        name_b = rel_data.get("character_b", "")
        id_a = name_to_id.get(name_a)
        id_b = name_to_id.get(name_b)
        if id_a and id_b:
            relationship.update_relationship(
                state.relationships, id_a, id_b,
                trust_delta=rel_data.get("trust", 50) - 50,
                affection_delta=rel_data.get("affection", 50) - 50,
                description=rel_data.get("description", ""),
            )
        else:
            logger.warning(f"  初始关系匹配失败: name_a={name_a}(id={id_a}), name_b={name_b}(id={id_b})")

    state.current_step = 0

    # ============================
    # Phase 1: 推进时间
    # ============================
    log_separator("Phase 1: 推进时间")
    state.current_step += 1
    step = state.current_step
    day = state.current_day
    hour = state.current_hour
    time_label = f"{setting.starting_date} {hour:02d}:00"
    logger.info(f"  step={step}, day={day}, hour={hour}, label={time_label}")

    # ============================
    # Phase 2: 处理世界事件
    # ============================
    log_separator("Phase 2: 处理世界事件")

    newly_active = world_event.process_pending_events(
        state.active_world_events, state.pending_player_events, step,
    )
    log_data("pending_events (处理后)", newly_active)
    logger.info(f"  新激活事件数: {len(newly_active)}")

    active_events = world_event.get_active_events(state.active_world_events, step)
    log_data("active_events", [e.description for e in active_events])

    # ============================
    # Phase 3: 为每个角色生成行动（并行）
    # ============================
    log_separator("Phase 3: 角色行动生成 (并行)")

    action_tasks = []
    for cid in char_ids:
        action_tasks.append(debug_generate_character_action(
            cid, state, active_events, time_label, char_names, name_to_id, step
        ))

    action_results = await asyncio.gather(*action_tasks, return_exceptions=True)

    events = []
    for i, result in enumerate(action_results):
        if isinstance(result, Exception):
            logger.error(f"  角色 {char_ids[i]} ({id_map[char_ids[i]]}) 行动生成失败:")
            logger.error(f"  {traceback.format_exc()}")
            continue
        events.append(result)

    log_data("所有角色行动结果", events)
    logger.info(f"  成功生成 {len(events)}/{len(char_ids)} 个角色行动")

    # ============================
    # Phase 4: 冲突协调
    # ============================
    log_separator("Phase 4: 冲突协调")

    has_interactions = any(e.get("target") for e in events)
    logger.info(f"  存在互动: {has_interactions}")

    if has_interactions and len(events) > 1:
        events = await debug_resolve_conflicts(events, char_names, name_to_id, state)
    log_data("冲突协调后的事件列表", events)

    # ============================
    # Phase 5: 更新状态 + 写入记忆
    # ============================
    log_separator("Phase 5: 更新状态 + 写入记忆")

    step_memories = {cid: [] for cid in char_ids}
    for idx, event_data in enumerate(events):
        cid = event_data.get("character_id", "???")
        logger.info(f"  [{idx+1}] character_id={cid} (type={type(cid).__name__})")

        # 关键检查：cid 是否在 character_states 中
        if cid not in state.character_states:
            logger.error(f"  [ERROR] character_id='{cid}' 不在 character_states 中!")
            logger.error(f"  可用的 keys: {list(state.character_states.keys())}")
            logger.error(f"  事件数据: {json.dumps(event_data, ensure_ascii=False, default=str)}")
            continue

        state_obj = state.character_states[cid]
        logger.info(f"  [{idx+1}] 名字={state_obj.config.name}, location={state_obj.current_location}")

        # 更新角色状态
        character.update_character_after_action(
            state_obj,
            action=event_data.get("action", ""),
            new_location=event_data.get("new_location"),
            mood_change=event_data.get("mood_change", ""),
            condition_change=event_data.get("condition_change", ""),
        )

        # 写入记忆
        mem_desc = event_data.get("action", "")
        if event_data.get("dialogue"):
            mem_desc += f"，说道：{event_data['dialogue']}"
        target_id = event_data.get("target")
        involved = [target_id] if target_id else []

        # 构建 tags，过滤 None 和空字符串
        raw_tags = [cid, event_data.get("target")]
        tags = [t for t in raw_tags if t is not None and t != ""]
        logger.debug(f"  [{idx+1}] raw_tags={raw_tags} -> filtered_tags={tags}")

        try:
            mem = memory.add_memory(
                state.memories[cid],
                step=step,
                timestamp=time_label,
                description=mem_desc,
                importance=event_data.get("importance", 5),
                involved_characters=involved,
                tags=tags,
            )
            step_memories[cid].append(mem.memory_id)
            logger.info(f"  [{idx+1}] 记忆写入成功: memory_id={mem.memory_id}")
        except Exception as e:
            logger.error(f"  [{idx+1}] 记忆写入失败: {e}")
            logger.error(f"  数据快照: cid={cid}, tags={tags}, involved={involved}")
            logger.error(traceback.format_exc())
            continue

        # 观察者记忆
        if target_id and target_id in state.memories:
            target_state_obj = state.character_states.get(target_id)
            if target_state_obj:
                observer_desc = (
                    f"{state_obj.config.name}对自己做了什么：{event_data.get('action', '')}"
                )
                if event_data.get("dialogue"):
                    observer_desc += f"，说道：{event_data['dialogue']}"
                try:
                    memory.add_memory(
                        state.memories[target_id],
                        step=step,
                        timestamp=time_label,
                        description=observer_desc,
                        importance=max(3, event_data.get("importance", 5) - 1),
                        involved_characters=[cid],
                        tags=[cid],
                    )
                    logger.info(f"  [{idx+1}] 观察者记忆写入成功: target={target_id}")
                except Exception as e:
                    logger.error(f"  [{idx+1}] 观察者记忆写入失败: {e}")
                    logger.error(traceback.format_exc())

    # ============================
    # Phase 6: 生成叙事
    # ============================
    log_separator("Phase 6: 生成叙事")

    story_events = []
    for e in events:
        try:
            se = StoryEvent(
                character_id=e["character_id"],
                action=e.get("action", ""),
                dialogue=e.get("dialogue"),
                internal_thought=e.get("internal_thought"),
                target=e.get("target"),
                mood_change=e.get("mood_change", ""),
                importance=e.get("importance", 5),
            )
            story_events.append(se)
        except Exception as ex:
            logger.error(f"  StoryEvent 构建失败: {ex}")
            logger.error(f"  原始数据: {json.dumps(e, ensure_ascii=False, default=str)}")
            logger.error(traceback.format_exc())

    log_data("story_events", [se.model_dump() for se in story_events])

    recent_narrative = ""
    narrative_text = ""
    if story_events:
        narrative_messages = prompt_narrative.build_narrative_prompt(
            story_setting=f"{setting.era} - {setting.location}。{setting.description}",
            recent_narrative=recent_narrative,
            world_events=active_events,
            events=story_events,
            char_names=char_names,
        )
        narrative_raw = await chat_async(narrative_messages, max_tokens=2048)
        narrative_text = narrative_raw.strip()
        log_llm_io("narrative", narrative_messages, narrative_raw, {"narrative": narrative_text})
    else:
        logger.warning("  story_events 为空，跳过叙事生成")

    logger.info(f"  叙事文本 ({len(narrative_text)} 字): {narrative_text[:300]}...")

    # ============================
    # Phase 7: 反思检查
    # ============================
    log_separator("Phase 7: 反思检查")
    should_reflect = memory.should_reflect(step)
    logger.info(f"  step={step}, should_reflect={should_reflect}")
    # 跳过实际反思调用，避免日志过长

    # ============================
    # 完成
    # ============================
    log_separator("诊断完成")
    logger.info(f"  总角色数: {len(characters)}")
    logger.info(f"  成功生成行动: {len(events)}")
    logger.info(f"  叙事长度: {len(narrative_text)} 字")
    logger.info(f"  日志已保存到: {LOG_FILE}")


async def debug_generate_character_action(
    character_id: str, state: StoryState,
    active_events: list[WorldEvent], time_label: str,
    char_names: dict, name_to_id: dict, step: int,
) -> dict:
    """生成单个角色行动，记录完整调试信息"""
    name = char_names[character_id]
    logger.info(f"  --- 生成行动: {name} (ID={character_id}) ---")

    state_obj = state.character_states[character_id]
    char_memories = state.memories[character_id]

    # 检索记忆
    retrieved = memory.retrieve_memories(char_memories, state.current_step, max_results=8)
    log_data(f"{name} - 检索到的记忆", [m.description for m in retrieved])

    # 关系摘要
    rel_summary = relationship.get_relationship_summary(
        state.relationships, character_id, char_names
    )
    logger.debug(f"[{name}] 关系摘要: {rel_summary[:300]}...")

    # 构建 prompt
    messages = prompt_action.build_character_action_prompt(
        character=state_obj,
        memories=retrieved,
        relationship_summary=rel_summary,
        world_events=active_events,
        time_label=time_label,
    )

    # 调用 LLM
    raw_response = await chat_async(messages, json_mode=True)
    parsed = parse_json_response(raw_response)

    log_llm_io(f"character_action_{name}", messages, raw_response, parsed)

    # 设置 character_id
    parsed["character_id"] = character_id
    logger.info(f"  [{name}] character_id 强制设置为: {character_id}")

    # 修复 target：名字 → ID
    raw_target = parsed.get("target")
    if raw_target:
        logger.info(f"  [{name}] target 原始值: '{raw_target}' (type={type(raw_target).__name__})")
        if raw_target in name_to_id:
            parsed["target"] = name_to_id[raw_target]
            logger.info(f"  [{name}] target 名字→ID 映射: '{raw_target}' -> '{name_to_id[raw_target]}'")
        elif raw_target not in state.character_states:
            logger.warning(f"  [{name}] target='{raw_target}' 既不是名字也不是有效ID，保持原样")

    # 检查所有字段的类型
    for key, value in parsed.items():
        if value is None:
            logger.warning(f"  [{name}] 字段 '{key}' 值为 None")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if item is None:
                    logger.warning(f"  [{name}] 字段 '{key}[{i}]' 值为 None")

    return parsed


async def debug_resolve_conflicts(
    events: list[dict], char_names: dict, name_to_id: dict, state: StoryState,
) -> list[dict]:
    """冲突协调，记录完整调试信息"""
    logger.info("  --- 冲突协调 ---")
    log_data("输入事件列表", events)

    messages = prompt_conflict.build_conflict_resolve_prompt(
        events=[
            StoryEvent(**{k: v for k, v in e.items() if k in StoryEvent.model_fields})
            for e in events
        ],
        char_names=char_names,
        story_setting=f"{state.setting.era} - {state.setting.location}",
    )

    raw_response = await chat_async(messages, json_mode=True)
    parsed = parse_json_response(raw_response)

    log_llm_io("conflict_resolve", messages, raw_response, parsed)

    resolved = parsed.get("resolved_events", events)

    # 修复名字→ID
    for ev in resolved:
        raw_id = ev.get("character_id", "")
        if raw_id in name_to_id:
            logger.info(f"  冲突协调: character_id '{raw_id}' -> '{name_to_id[raw_id]}'")
            ev["character_id"] = name_to_id[raw_id]
        elif raw_id not in state.character_states:
            logger.warning(f"  冲突协调: character_id='{raw_id}' 无效！")

        raw_target = ev.get("target")
        if raw_target and raw_target in name_to_id:
            logger.info(f"  冲突协调: target '{raw_target}' -> '{name_to_id[raw_target]}'")
            ev["target"] = name_to_id[raw_target]
        elif raw_target and raw_target not in state.character_states:
            logger.warning(f"  冲突协调: target='{raw_target}' 无效！")

    return resolved


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    print(f"日志将保存到: {LOG_FILE}")
    print("正在运行单步诊断...\n")
    asyncio.run(debug_advance())
    print(f"\n诊断完成！请查看日志文件: {LOG_FILE}")
