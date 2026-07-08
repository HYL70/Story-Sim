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
        "name": "程野",
        "role": "6-309寝室长 / 大三机械系",
        "age": 22,
        "gender": "男",
        "personality": "表面不修边幅，整天打游戏，但寝室里水电费、值日表这类杂事都是他在兜底。嘴上说麻烦，实际上什么事都管",
        "background": "本地人，周末回家带好吃的回来分。高考超常发挥考进这所学校，至今觉得自己是运气好混进来的",
        "motivation": "这学期不被辅导员约谈，以及把囤了三天的外卖盒扔掉",
        "speaking_style": "边打游戏边说话，头也不回，语速慢且沙哑，常用'啊？''行行行'应付人",
        "secret": "其实他在偷偷攒钱买一套新的机械键盘，但不想让室友觉得他乱花钱",
        "fear": "寝室卫生检查被通报批评",
        "initial_location": "靠门的下铺，对着电脑屏幕",
        "initial_mood": "懒散",
    },
    {
        "name": "沈一鸣",
        "role": "6-309成员 / 大三金融系",
        "age": 21,
        "gender": "男",
        "personality": "洁癖，有点龟毛，每周要拖两遍地。说话爱挑刺但心不坏，是整个寝室唯一坚持去食堂吃早饭的人",
        "background": "独生子，从小被妈妈打理得干干净净，上了大学才发现原来有人可以一周不洗袜子",
        "motivation": "让309的卫生水平达到人类可居住的标准",
        "speaking_style": "语气略带嫌弃，但内容往往是关心，常以'我说你们啊'开头",
        "secret": "他把所有室友的生日都记在手机备忘录里，每次都偷偷准备小礼物，但从来不承认",
        "fear": "被分到一个比他更爱干净的新室友，会让他失去唯一的优越感",
        "initial_location": "阳台门口，正戴着橡胶手套准备拖地",
        "initial_mood": "无奈",
    },
    {
        "name": "李骁",
        "role": "6-309成员 / 大三体育系",
        "age": 22,
        "gender": "男",
        "personality": "精力过剩，爱接话茬，谁说话他都能接两句。嗓门大，笑声响，经常在阳台上跟女朋友视频外放",
        "background": "篮球特长生进校，高中谈的女朋友在隔壁城市，每周末坐高铁去见一面，来回要六个小时",
        "motivation": "这周末比赛打赢，以及找到一个不查寝的借口去见女朋友",
        "speaking_style": "中气十足，喜欢拍大腿，说话带感叹号，口头禅是'兄弟我跟你说'",
        "secret": "每次跟女朋友视频前会偷偷去阳台刮一下胡子，其他室友都知道，但没人拆穿",
        "fear": "比赛受伤，或者女朋友跟他提分手",
        "initial_location": "寝室中央，正举着哑铃做弯举",
        "initial_mood": "精力充沛",
    },
    {
        "name": "江一苇",
        "role": "6-309成员 / 大三建筑系",
        "age": 23,
        "gender": "男",
        "personality": "存在感最低的一个，成天戴着耳机画画或做模型。话少但语出惊人，属于那种一开口就让全寝室笑半天的类型",
        "background": "复读过一年，比同届大一岁。平时昼伏夜出，凌晨两三点才是他的活跃时间，室友都习惯了他台灯亮到天亮",
        "motivation": "熬过这学期的设计大作业，以及别被室友投诉他半夜磨铅笔的声音",
        "speaking_style": "戴着耳机说话，声音忽大忽小，经常叫别人三次才应一次",
        "secret": "他的衣柜角落里藏着一小瓶伏特加，压力大的时候半夜抿一口，室友谁都不知道",
        "fear": "图纸被水打湿，或者模型被碰坏",
        "initial_location": "靠窗的上铺，台灯亮着，在画手稿",
        "initial_mood": "专注",
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
        title="6-309日常",
        era="现代中国",
        location="梧桐大学·学生公寓6号楼·309室",
        description="一个普通的四人男生寝室。发生在这里的一切无非是：打游戏、拖地、举哑铃、画图——互相嫌弃又互相习惯。",
        tone="轻松 · 日常 · 带点幽默",
        starting_date="10月下旬",
        starting_date_iso="2024-10-25",
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
