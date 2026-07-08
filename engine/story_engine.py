"""
故事引擎 - 核心控制器（四层流水线架构）
协调：事件调度 → 角色决策(意图) → 世界模拟(碰撞/对话/旁观) → 叙事编排(讲述+伏笔)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.schemas import (
    StoryState, StorySetting, CharacterConfig, CharacterState,
    MemoryEntry, Relationship, WorldEvent, StoryEvent, TimeStep,
    WorldSnapshot, EventType, EventSource, TimeSlot, ScheduledEvent,
    Interaction, Encounter, EncounterType, PersonalEvent,
)
from engine import llm_client, character, memory, relationship, world_event, world_sim
from prompts import (
    character_action as prompt_action,
    narrative as prompt_narrative,
    conflict_resolve as prompt_conflict,
    reflection as prompt_reflection,
    world_event_judge as prompt_event_judge,
    story_init as prompt_init,
)

import config

logger = logging.getLogger(__name__)

# --- Bug 日志文件（同时写入 data/saves/debug.log） ---
_log_path = Path(__file__).parent.parent / "data" / "saves" / "debug.log"
_log_path.parent.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(_log_path, encoding="utf-8", mode="a")
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
)
logger.addHandler(_file_handler)
logger.setLevel(logging.DEBUG)


# output-problems #3: activity → location 映射表
_ACTIVITY_LOCATION_MAP = {
    "上课": "教室", "听课": "教室", "课堂": "教室", "自习": "教室",
    "午餐": "食堂", "吃饭": "食堂", "便当": "食堂", "午饭": "食堂", "午餐": "食堂",
    "社团": "社团活动室", "部活": "社团活动室", "运动": "操场",
    "跑步": "操场", "打球": "体育馆", "比赛": "体育馆",
    "借书": "图书馆", "看书": "图书馆", "图书": "图书馆",
    "保健": "保健室", "医务": "保健室",
    "天台": "屋顶", "屋顶": "屋顶", "楼顶": "屋顶",
    "放学": "校门口", "回家": "校门口", "登校": "校门口",
    "课间": "走廊", "休息": "走廊",
}
def _infer_location_from_activity(activity: str, fallback: str) -> str:
    """根据活动描述关键词推断合理位置，找不到则返回 fallback"""
    for keyword, loc in _ACTIVITY_LOCATION_MAP.items():
        if keyword in activity:
            return loc
    return fallback


class StoryEngine:
    """故事引擎 - 四层流水线架构"""

    def __init__(self):
        self.state: Optional[StoryState] = None
        self._running = False
        # N8: LLM 并发控制 — 最多 6 个并行调用，防止 API 限流
        self._llm_semaphore = asyncio.Semaphore(6)

    # ========================================================
    # 故事初始化
    # ========================================================

    def init_story(
        self,
        setting: StorySetting,
        characters: list[CharacterConfig],
    ) -> str:
        """
        初始化故事，生成开场白和初始关系。
        返回开场叙事文本。
        """
        # 创建初始状态
        self.state = StoryState(
            setting=setting,
            characters={c.character_id: c for c in characters},
            current_hour=config.DEFAULT_START_HOUR,
        )

        # 创建角色状态
        for c in characters:
            self.state.character_states[c.character_id] = character.create_character(c)
            self.state.memories[c.character_id] = []

        # 初始化关系矩阵
        char_ids = [c.character_id for c in characters]
        self.state.relationships = relationship.init_relationships(char_ids)

        # 调用 LLM 生成开场白和初始关系
        chars_data = [c.model_dump() for c in characters]
        messages = prompt_init.build_story_init_prompt(
            setting_description=f"{setting.era} - {setting.location}\n{setting.description}",
            character_configs=chars_data,
            tone=setting.tone or "",
            character_arc_outline=self.state.character_arc_outline or "",
        )

        result = llm_client.parse_json_response(
            llm_client.chat(messages, max_tokens=4096)
        )

        # 保存开场白
        opening = result.get("opening_narrative", "故事开始了...")
        time_label = self.state.get_time_label()
        self.state.timeline.append(
            TimeStep(
                step=0,
                day=1,
                hour=config.DEFAULT_START_HOUR,
                time_label=f"{time_label} 开场",
                narrative=opening,
            )
        )

        # 应用 LLM 生成的初始关系
        for rel_data in result.get("initial_relationships", []):
            name_a = rel_data.get("character_a", "")
            name_b = rel_data.get("character_b", "")
            id_a = self._find_char_id_by_name(name_a)
            id_b = self._find_char_id_by_name(name_b)
            if id_a and id_b:
                relationship.update_relationship(
                    self.state.relationships, id_a, id_b,
                    trust_delta=rel_data.get("trust", 50) - 50,
                    affection_delta=rel_data.get("affection", 50) - 50,
                    description=rel_data.get("description", ""),
                )

        # 初始化叙事合集文件
        self._write_narrative_file(opening)

        return opening

    async def init_story_schedule(self) -> None:
        """初始化角色个人时间表（异步，在 init_story 之后调用）"""
        if self.state is None:
            return
        await self._initialize_personal_schedules()

    def _find_char_id_by_name(self, name: str) -> Optional[str]:
        for cid, cfg in self.state.characters.items():
            if cfg.name == name:
                return cid
        return None

    # ========================================================
    # 核心时间步推进（四层流水线）
    # ========================================================

    async def advance_one_step(self) -> Optional[str]:
        """
        推进一个时间步（世界时钟 + per-agent schedule）。
        核心：世界时间 = 所有人 schedule 中最早的时间点，跳过去。

        弧追踪状态机：normal → cooldown → check → normal
        - normal: 正常叙事
        - cooldown: 高压事件后余韵期（跳过 importance 判定，始终叙事）
        - check: cooldown 结束，做调节回判定
          - Type A: 轻量叙事（低 importance 也写一段短的）
          - Type B: 伏笔留白（存入 foreshadow_buffer，不叙事）
          - 纯跳过: 无碰撞无世界事件，纯跳过

        返回叙事文本（str），如果本步被跳过则返回 None。
        """
        if self.state is None:
            raise RuntimeError("故事未初始化，请先调用 init_story()")

        import time as _time
        _t0 = _time.time()

        # ===== [步骤1] 世界时钟推进：找到下一个时间点 =====
        next_time = self._get_next_world_time()
        if next_time is None:
            logger.warning("[步骤1] 所有角色时间表为空，尝试补充日程")
            await self._initialize_personal_schedules()
            next_time = self._get_next_world_time()

        if next_time is None:
            logger.warning("[步骤1] 日程补充后仍为空，跳过本次推进")
            return None

        day, hour, minute = next_time
        self.state.current_step += 1
        self.state.current_day = day
        self.state.current_hour = hour
        self.state.current_minute = minute
        step = self.state.current_step
        time_label = self.state.get_time_label()

        # 先获取活跃角色（必须在 _pop 之前，否则事件已被移除）
        active_char_ids = self._get_active_characters(day, hour, minute)
        # 再取出该时间点的调度事件（取出后会从 schedule 中移除）
        scheduled_events = self._pop_scheduled_events(day, hour, minute)

        logger.info(f"=== 推进时间步 {step} | {time_label} | 活跃角色: {active_char_ids} ===")

        # --- P0-1: Occupancy Model ---
        # 清理过期的占用状态
        if hasattr(self.state, 'occupancy'):
            expired = []
            for cid, occ in self.state.occupancy.items():
                busy = occ.get("busy_until", (day, hour, minute + 1))
                if (busy[0], busy[1], busy[2]) <= (day, hour, minute):
                    expired.append(cid)
            for cid in expired:
                occ = self.state.occupancy[cid]
                logger.debug(f"[Occupancy] {cid} 占用已过期，释放")
                # N2: 占用结束后自动写入"恢复自由"事件，防止角色从调度系统消失
                busy_until = occ.get("busy_until", (day, hour, minute))
                # output-problems #8: 时间不能倒退 — 取 busy_until+1 和当前世界时间的最大值
                recovery_minute = busy_until[2] + 1
                recovery_hour = busy_until[1] + recovery_minute // 60
                recovery_day = busy_until[0] + recovery_hour // 24
                recovery_hour = recovery_hour % 24
                recovery_minute = recovery_minute % 60
                recovery_total = recovery_day * 1440 + recovery_hour * 60 + recovery_minute
                world_total = day * 1440 + hour * 60 + minute
                if recovery_total < world_total:
                    # 恢复时间早于当前 → 用当前时间 + 1 分钟
                    recovery_day = day
                    recovery_hour = hour
                    recovery_minute = minute + 1
                    logger.debug(f"[Occupancy] N2 恢复时间被世界时钟超越，修正为当前时间 d{day} {hour:02d}:{minute+1:02d}")
                self.state.character_states[cid].personal_schedule.append(PersonalEvent(
                    day=recovery_day,
                    hour=recovery_hour,
                    minute=recovery_minute,
                    duration=60,
                    description="自由活动",
                    importance=3,
                    source="auto",
                ))
                self.state.character_states[cid].personal_schedule.sort(
                    key=lambda e: (e.day, e.hour, e.minute)
                )
                del self.state.occupancy[cid]

        # 为活跃角色的调度事件写入/更新 occupancy
        for cid in active_char_ids:
            evt = scheduled_events.get(cid, {})
            dur = evt.get("duration", 0)
            if dur > 0:
                # 计算 busy_until (总分钟)
                total_m = hour * 60 + minute + dur
                busy_day = day + total_m // 1440
                busy_hour = (total_m % 1440) // 60
                busy_min = (total_m % 1440) % 60
                # output-problems #3: 根据 activity 推断合理位置，而非只用 current_location
                activity_desc = evt.get("description", "")
                locked_loc = _infer_location_from_activity(
                    activity_desc,
                    self.state.character_states[cid].current_location,
                )
                self.state.occupancy[cid] = {
                    "busy_until": (busy_day, busy_hour, busy_min),
                    "locked_location": locked_loc,
                    "activity": activity_desc,
                    "importance": evt.get("importance", 5),
                }
                logger.debug(f"[Occupancy] {cid} 占用至 d{busy_day} {busy_hour:02d}:{busy_min:02d}, loc={locked_loc}, {activity_desc}")

        # --- 处理世界事件 ---
        newly_active = world_event.process_pending_events(
            self.state.active_world_events,
            self.state.pending_player_events,
            step,
        )

        active_events = world_event.get_active_events(self.state.active_world_events, step)
        for ev in newly_active:
            logger.info(f"判定事件影响: {ev.description}")
            await self._judge_event_impact(ev)
        active_events = world_event.get_active_events(self.state.active_world_events, step)

        # --- 更新世界状态快照 ---
        world_snapshot = self._build_world_snapshot(step, active_events)

        # --- [hook] 感知检查 ---
        await self._perception_check(step, time_label, active_events)

        # ===== [步骤2] 角色决策：活跃角色并行生成"意图" =====
        char_ids = list(self.state.characters.keys())
        char_names = {cid: cfg.name for cid, cfg in self.state.characters.items()}
        logger.info(f"[步骤2] 为 {len(active_char_ids)} 个活跃角色生成意图（并行）...")

        intent_tasks = []
        task_cids = []  # 追踪哪些 cid 实际发起了 LLM 调用

        # P0: 构建角色受影响的事件索引（affected_characters → 差异化提示）
        char_affected_events: dict[str, list[str]] = {cid: [] for cid in char_ids}
        for ev in active_events:
            for aff_cid in ev.affected_characters:
                if aff_cid in char_affected_events:
                    char_affected_events[aff_cid].append(ev.description)

        for cid in active_char_ids:
            # P0-1: Occupancy check — 被占用的角色跳过 LLM，直接使用 locked intent
            if cid in self.state.occupancy:
                occ = self.state.occupancy[cid]
                logger.debug(f"[步骤2] {cid} 正被占用（{occ.get('activity', '')}），跳过 LLM 意图生成")
                continue  # 不加入 intent_tasks，在收集阶段用占位 intent

            evt = scheduled_events.get(cid, {})
            scheduled_desc = evt.get("description", "") if isinstance(evt, dict) else str(evt)
            affected_desc = char_affected_events.get(cid, [])
            intent_tasks.append(
                self._generate_character_intent(
                    cid, active_events, time_label, world_snapshot, scheduled_desc,
                    affected_events=affected_desc,
                )
            )
            task_cids.append(cid)

        intent_results = await asyncio.gather(*intent_tasks, return_exceptions=True)
        logger.info(f"[步骤2] 角色意图生成完毕，耗时 {_time.time()-_t0:.1f}s")

        # 收集意图结果
        intents: dict[str, dict] = {}
        for i, result in enumerate(intent_results):
            cid = task_cids[i]
            if isinstance(result, Exception):
                logger.error(f"角色 {cid} 意图生成失败: {result}")
                intents[cid] = {
                    "intent": "留在原地",
                    "destination": self.state.character_states[cid].current_location,
                    "importance": 3,
                }
                continue
            result["character_id"] = cid
            intents[cid] = result

            # 将 LLM 返回的 next_event 写入角色个人时间表
            self._update_character_schedule_from_intent(cid, result, day, hour, minute)

        # P0-1: 为被占用角色生成占位意图（使用 locked_location + activity）
        for cid in active_char_ids:
            if cid not in intents:
                occ = self.state.occupancy.get(cid, {})
                state = self.state.character_states.get(cid)
                locked_loc = occ.get("locked_location", state.current_location if state else "")
                activity = occ.get("activity", "继续当前活动")
                # output-problems #5: 截断 importance 上限，防止 routine 事件触发 cooldown
                raw_imp = occ.get("importance", 5)
                imp = min(int(raw_imp), 6)
                intents[cid] = {
                    "intent": activity,
                    "destination": locked_loc,
                    "importance": imp,
                    "mood": state.current_mood if state else "平静",
                    "thoughts": "",
                    "mood_change": "",
                    "condition_change": "",
                }
                # 占用角色不需要更新 time schedule（已经在占用中）
                logger.debug(f"[Occupancy] 角色 {cid} 使用占用占位意图: {activity}")

        # 非活跃角色：无意图，保持原位
        for cid in char_ids:
            if cid not in intents:
                intents[cid] = {
                    "intent": "继续日常",
                    "destination": self.state.character_states[cid].current_location,
                    "importance": 2,
                }

        # P1-5: 意图交叉校验 — 检测"找某人但目标不在同地"的意图失败
        intent_failures = world_sim._cross_validate_intents(
            intents, self.state.character_states, self.state.characters
        )
        for cid, reason in intent_failures.items():
            if cid in intents:
                intents[cid]["intent"] = f"{intents[cid].get('intent', '')}（{reason}）"
                # 降级 importance：意图失败意味着重要性降低
                intents[cid]["importance"] = max(3, intents[cid].get("importance", 5) - 2)

        # ===== [步骤3] 世界模拟：碰撞检测 → 对话生成 → 旁观判定 =====
        logger.info("[步骤3] 世界模拟：碰撞检测...")
        encounters = world_sim.detect_encounters(
            intents=intents,
            relationships=self.state.relationships,
            character_states=self.state.character_states,
            characters=self.state.characters,
        )

        # 为 DIALOGUE 类型的碰撞生成对话（调 LLM）
        dialogue_encounters = [e for e in encounters if e.encounter_type == EncounterType.DIALOGUE]
        if dialogue_encounters:
            logger.info(f"[步骤3] 为 {len(dialogue_encounters)} 组碰撞生成对话...")
            dialogue_tasks = []
            for enc in dialogue_encounters:
                dialogue_tasks.append(
                    world_sim.generate_dialogue(
                        encounter=enc,
                        character_states=self.state.character_states,
                        characters=self.state.characters,
                        intents=intents,
                        time_label=time_label,
                        relationships=self.state.relationships,
                    )
                )
            dialogue_results = await asyncio.gather(*dialogue_tasks, return_exceptions=True)
            # N4: 显式检查 gather 结果，记录异常而非静默吞没
            for i, dr in enumerate(dialogue_results):
                if isinstance(dr, Exception):
                    enc = dialogue_encounters[i]
                    logger.error(f"[步骤3] 对话生成异常 {enc.character_a}↔{enc.character_b}: {dr}")
                    enc.outcome = "两人短暂对视后各自离开。"

        # 处理旁观事件
        observation_encounters = [e for e in encounters if e.encounter_type == EncounterType.OBSERVATION]
        for enc in observation_encounters:
            observer_id = enc.observer
            observed_id = enc.character_b if observer_id == enc.character_a else enc.character_a
            observed_name = char_names.get(observed_id, observed_id)
            if observer_id and observer_id in self.state.memories:
                memory.add_memory(
                    self.state.memories[observer_id],
                    step=step,
                    timestamp=time_label,
                    description=f"在{enc.location}看到了{observed_name}（没有上前搭话）",
                    importance=3,
                    involved_characters=[observed_id],
                    tags=[observer_id, observed_id, "observation"],
                )

            # P0 关系闭环: 应用对话产生的关系变化
            for enc in dialogue_encounters:
                dd = enc.dialogue_data or {}
                delta = dd.get("relationship_delta", {})
                if not delta and enc.outcome:
                    # 兜底：LLM 未返回 relationship_delta，从 outcome 启发式推断
                    outcome_lower = enc.outcome.lower()
                    positive_words = ["缓和", "理解", "鼓励", "安慰", "亲近", "友好", "和解", "拉近", "愉快"]
                    negative_words = ["冲突", "争吵", "疏远", "冷淡", "误解", "对峙", "不满", "受伤", "失望"]
                    has_pos = any(w in outcome_lower for w in positive_words)
                    has_neg = any(w in outcome_lower for w in negative_words)
                    if has_pos and not has_neg:
                        delta = {"trust": 2, "affection": 3}
                    elif has_neg and not has_pos:
                        delta = {"trust": -3, "affection": -2}
                    logger.debug(f"[关系Δ 推断] {enc.character_a}↔{enc.character_b}: outcome='{enc.outcome[:30]}' → {delta}")
                trust_d = delta.get("trust", 0)
                affection_d = delta.get("affection", 0)
                if trust_d or affection_d:
                    relationship.update_relationship(
                        self.state.relationships,
                        enc.character_a, enc.character_b,
                        trust_delta=int(trust_d),
                        affection_delta=int(affection_d),
                    )
                    logger.debug(
                        f"[关系Δ] {enc.character_a}↔{enc.character_b}: "
                        f"trust {trust_d:+d}, affection {affection_d:+d}"
                    )

        # 构建 Interaction 列表（只包含活跃角色）
        interactions = world_sim.build_interactions(
            intents=intents,
            encounters=encounters,
            character_states=self.state.character_states,
        )
        active_interactions = [ia for ia in interactions if ia.character_id in active_char_ids]

        logger.info(f"[步骤3] 世界模拟完成，{len(encounters)} 次碰撞，耗时 {_time.time()-_t0:.1f}s")

        # ===== 状态更新 + 记忆写入 =====
        step_memories = {cid: [] for cid in char_ids}
        for ia in active_interactions:
            cid = ia.character_id
            state = self.state.character_states[cid]
            dest = ia.destination if ia.destination else state.current_location
            character.update_character_after_action(
                state, action=ia.intent, new_location=dest,
                mood_change=ia.mood_change or None,
                condition_change=ia.condition_change,
            )
            intent_data = intents.get(cid, {})
            if intent_data.get("updated_plan"):
                state.current_plan = intent_data["updated_plan"]
            mem_desc = ia.intent
            if ia.internal_thought:
                mem_desc += f"，想到：{ia.internal_thought}"
            for enc in ia.encounters:
                if enc.encounter_type == EncounterType.DIALOGUE and enc.dialogue:
                    other_id = enc.character_b if enc.character_a == cid else enc.character_a
                    other_name = char_names.get(other_id, other_id)
                    lines = [d.get("line", "") for d in enc.dialogue]
                    mem_desc += f"，与{other_name}对话：" + "；".join(lines[:2])
            involved = [enc.character_b if enc.character_a == cid else enc.character_a for enc in ia.encounters]
            mem = memory.add_memory(
                self.state.memories[cid], step=step, timestamp=time_label,
                description=mem_desc, importance=ia.importance,
                involved_characters=involved, tags=[cid] + involved,
            )
            step_memories[cid].append(mem.memory_id)
        for cid in char_ids:
            self.state.character_states[cid].movement_path = []

        # ===== 叙事节奏判定（简化：仅 importance + 碰撞）=====
        max_importance = max((ia.importance for ia in active_interactions), default=0)
        has_active_world_events = len(active_events) > 0
        # 只统计活跃角色参与的碰撞
        active_cids = set(active_char_ids)
        has_encounters = any(
            e.character_a in active_cids or e.character_b in active_cids
            for e in encounters
        )

        # 简化 skip 逻辑：importance 低 + 无碰撞 + 无事件 + 未达连续上限 → 跳过
        if (max_importance < config.NARRATIVE_IMPORTANCE_THRESHOLD
                and not has_encounters
                and not has_active_world_events
                and self.state.consecutive_skipped < config.MAX_SKIPPED_STEPS):
            self.state.consecutive_skipped += 1
            logger.info(f"时间步 {step} 被跳过（快进），连续跳过 {self.state.consecutive_skipped} 步，importance={max_importance}")

            self.state.timeline.append(TimeStep(
                step=step, day=day, hour=hour,
                time_label=f"{time_label} [快进]",
                interactions=active_interactions,
                active_world_events=active_events,
                narrative="",
                memories_added=step_memories,
                skipped=True,
            ))
            self.state.world_snapshots.append(world_snapshot)
            self.state.updated_at = datetime.now().isoformat()
            return None

        self.state.consecutive_skipped = 0

        # ===== [步骤4] 叙事编排 =====
        logger.info(f"[步骤4] 叙事编排（importance={max_importance}）...")

        narrative_text, _ = await self._generate_narrative_with_foreshadowing(
            active_interactions, active_events, time_label, world_snapshot, char_names,
            foreshadow_content="",
            light_mode=False,
        )

        if narrative_text:
            self._write_narrative_file(f"【第{step}步】{time_label}\n{narrative_text}\n\n---\n")
            self.state.narrative_step_count += 1

        # --- 反思检查 ---
        should_reflect = (
            self.state.narrative_step_count > 0
            and self.state.narrative_step_count % config.REFLECTION_INTERVAL == 0
        )
        if should_reflect:
            # v3 修复: 反思覆盖所有角色（非仅活跃角色），确保配角认知发展
            all_char_ids = list(self.state.character_states.keys())
            logger.info(f"[反思] 叙事步 {self.state.narrative_step_count}，触发反思（{len(all_char_ids)} 个角色）...")
            await self._run_reflections(all_char_ids, step, time_label)

        # --- 保存时间步 ---
        self.state.timeline.append(
            TimeStep(
                step=step, day=day, hour=hour,
                time_label=time_label,
                interactions=active_interactions,
                active_world_events=active_events,
                narrative=narrative_text,
                memories_added=step_memories,
            )
        )
        self.state.world_snapshots.append(world_snapshot)
        self.state.updated_at = datetime.now().isoformat()
        logger.info(f"时间步 {step} 完成，总耗时 {_time.time()-_t0:.1f}s，叙事 {len(narrative_text)} 字")

        return narrative_text

    # ========================================================
    # 个人时间表管理（per-agent schedule，替代全局 event_queue）
    # ========================================================

    def _get_next_world_time(self) -> Optional[tuple[int, int, int]]:
        """
        获取所有角色个人时间表中最早的时间点（精确到分钟）。
        返回 (day, hour, minute)，如果所有时间表都空则返回 None。
        """
        earliest: Optional[tuple[int, int, int]] = None
        for cid, state in self.state.character_states.items():
            if state.personal_schedule:
                first = state.personal_schedule[0]
                candidate = (first.day, first.hour, first.minute)
                if earliest is None or candidate < earliest:
                    earliest = candidate
        return earliest

    def _get_active_characters(self, day: int, hour: int, minute: int = 0) -> list[str]:
        """获取在该时间窗口内有计划的角色 ID 列表（±TIME_WINDOW_MINUTES）"""
        active = []
        # 计算当前时间 + 窗口的最小时间（总分钟）
        t_min = day * 1440 + hour * 60 + minute
        t_max = t_min + config.TIME_WINDOW_MINUTES
        for cid, state in self.state.character_states.items():
            for evt in state.personal_schedule:
                evt_total = evt.day * 1440 + evt.hour * 60 + evt.minute
                if t_min <= evt_total <= t_max:
                    active.append(cid)
                    break
        return active

    def _pop_scheduled_events(self, day: int, hour: int, minute: int = 0) -> dict[str, dict]:
        """从各角色个人时间表中取出精确时间点的事件，返回 {character_id: {description, duration, importance}}
        
        N5: 同角色同时刻有多个事件时，只取第一个，其余丢弃
        """
        events: dict[str, dict] = {}
        for cid, state in self.state.character_states.items():
            remaining = []
            taken = False
            for evt in state.personal_schedule:
                if evt.day == day and evt.hour == hour and evt.minute == minute:
                    if not taken:
                        events[cid] = {
                            "description": evt.description,
                            "duration": evt.duration,
                            "importance": evt.importance,
                            "location_hint": evt.description,
                        }
                        taken = True
                    else:
                        logger.warning(
                            f"[步骤1] 重复事件丢弃: {cid} d{evt.day} {evt.hour:02d}:{evt.minute:02d} '{evt.description}'"
                        )
                else:
                    remaining.append(evt)
            state.personal_schedule = remaining
        return events

    async def _initialize_personal_schedules(self) -> None:
        """
        初始化所有角色的个人时间表（Stanford 方案：层级计划 + 自然时长）。
        通过 LLM 为每个角色生成当天的日程（3-5 个时间段），
        每个事件包含 hour, minute, duration，LLM 自行判断合理时长。
        """
        char_ids = list(self.state.characters.keys())
        time_label = self.state.get_time_label()
        base_hour = self.state.current_hour

        for cid in char_ids:
            state = self.state.character_states[cid]
            schedule_prompt = f"""Based on the character profile, arrange this character's schedule for today (after {time_label}).

【Character】{state.config.name}
【Personality】{state.config.personality}
【Motivation】{state.config.motivation}
【Current location】{state.current_location}

Please output 3-5 time slots, JSON format:
{{"schedule": [
  {{"hour": {base_hour + 2}, "minute": 30, "duration": 60, "description": "what to do", "importance": 5}},
  {{"hour": {base_hour + 4}, "minute": 0, "duration": 90, "description": "what to do", "importance": 4}}
]}}

Notes:
- hour: 0-23, must be > current hour {base_hour} today, or use next day hour (next day = same hour number, e.g. 1 for 1am next day)
- minute: 0-59, the specific start minute within the hour
- duration: event duration in minutes (at least 10, typically 30-120)
- Different events for the same character should be naturally separated by their duration (no hard minimum interval needed; use common sense for travel time)
- importance: 1-10
- Each arrangement fits the character's personality"""

            try:
                messages = [{"role": "user", "content": schedule_prompt}]
                async with self._llm_semaphore:
                    response = await llm_client.chat_async(messages, json_mode=True)
                result = llm_client.parse_json_response(response)

                for item in result.get("schedule", []):
                    h = item.get("hour", base_hour + 2)
                    m = item.get("minute", 0)
                    dur = item.get("duration", 60)
                    desc = item.get("description", "")
                    imp = item.get("importance", 5)
                    if not desc:
                        continue
                    # Clamp values
                    h = int(h) % 24
                    m = max(0, min(59, int(m)))
                    dur = max(10, int(dur))
                    imp = max(1, min(10, int(imp)))
                    # N7: 使用总分钟数比较替代简单的小时<=判断
                    actual_hour = h
                    actual_day = self.state.current_day
                    target_total = h * 60 + m
                    current_total = base_hour * 60 + self.state.current_minute
                    if target_total <= current_total:
                        actual_day += 1
                        logger.debug(
                            f"Schedule cross-day: {h:02d}:{m:02d} <= "
                            f"current {base_hour:02d}:{self.state.current_minute:02d} → day {actual_day}"
                        )
                    logger.debug(
                        f"Schedule parsed: raw_h={item.get('hour')}, m={m}, "
                        f"dur={dur}, actual={actual_day}d {actual_hour:02d}:{m:02d}, "
                        f"desc={desc[:20]}"
                    )
                    state.personal_schedule.append(PersonalEvent(
                        day=actual_day,
                        hour=actual_hour,
                        minute=m,
                        duration=dur,
                        description=desc,
                        importance=imp,
                        source="schedule",
                    ))

                # Sort by (day, hour, minute)
                state.personal_schedule.sort(key=lambda e: (e.day, e.hour, e.minute))
                logger.info(f"Character {state.config.name} schedule initialized: {len(state.personal_schedule)} entries")
            except Exception as e:
                logger.error(f"Character {cid} schedule init failed: {e}")
                # Fallback: simple schedule
                for offset, m, desc, dur, imp in [(2, 0, "free activity", 60, 3), (4, 30, "class/activity", 90, 4), (7, 0, "break", 60, 3), (10, 0, "school ends", 60, 5)]:
                    h = base_hour + offset
                    state.personal_schedule.append(PersonalEvent(
                        day=self.state.current_day + (h // 24),
                        hour=h % 24,
                        minute=m,
                        duration=dur,
                        description=desc,
                        importance=imp,
                        source="auto",
                    ))
                state.personal_schedule.sort(key=lambda e: (e.day, e.hour, e.minute))

    # ========================================================
    # 叙事合集文件
    # ========================================================

    def _get_narrative_filepath(self) -> Path:
        return config.SAVES_DIR / "narrative_full.txt"

    def _write_narrative_file(self, text: str) -> None:
        filepath = self._get_narrative_filepath()
        config.SAVES_DIR.mkdir(parents=True, exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def rebuild_narrative_file(self) -> None:
        if self.state is None:
            return
        filepath = self._get_narrative_filepath()
        config.SAVES_DIR.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            for ts in self.state.timeline:
                if ts.narrative:
                    step_label = f"【第{ts.step}步】{ts.time_label}"
                    f.write(f"{step_label}\n{ts.narrative}\n\n---\n")

    # ========================================================
    # 内部方法
    # ========================================================

    def _build_world_snapshot(self, step: int, active_events: list[WorldEvent]) -> WorldSnapshot:
        """构建世界状态快照"""
        character_briefs = {}
        for cid, state in self.state.character_states.items():
            name = state.config.name
            recent = "、".join(state.recent_actions[-2:]) if state.recent_actions else state.last_action or "无"
            character_briefs[cid] = f"{name}：{state.current_location}，心情{state.current_mood}，身体{state.physical_condition}，近期{recent}"

        active_summary = ""
        if active_events:
            parts = []
            for e in active_events:
                src = "玩家" if e.source == EventSource.PLAYER else "系统"
                parts.append(f"[{src}]{e.description}")
            active_summary = "；".join(parts)

        key_rel_changes = []
        for r in self.state.relationships:
            if abs(r.trust) > 70 or abs(r.trust) < 30 or abs(r.affection) > 70 or abs(r.affection) < 30:
                name_a = self.state.characters.get(r.character_a)
                name_b = self.state.characters.get(r.character_b)
                if name_a and name_b:
                    key_rel_changes.append(f"{name_a.name}↔{name_b.name}：信任{r.trust} 好感{r.affection}")

        return WorldSnapshot(
            step=step,
            character_briefs=character_briefs,
            active_events_summary=active_summary,
            key_relationship_changes=key_rel_changes[:5],
            unresolved_threads=[],
        )

    async def _perception_check(
        self, step: int, time_label: str, active_events: list[WorldEvent]
    ) -> None:
        """[hook] 感知检查 - 预留扩展点。"""

    def _recent_narrative_text(self) -> str:
        """获取最近一步的叙事文本（用于世界事件判定等）"""
        if not self.state or not self.state.timeline:
            return ""
        last = self.state.timeline[-1]
        if last.narrative:
            return f"[{last.time_label}]: {last.narrative}"
        return ""

    def _extract_query_keywords(
        self, cid: str, state: CharacterState, char_names: dict[str, str]
    ) -> list[str]:
        """P0: 从当前情境自动提取记忆检索关键词"""
        keywords = []
        # 1. 当前地点
        loc = state.current_location
        if loc:
            keywords.append(loc)
        # 2. 当前心情
        if state.current_mood:
            keywords.append(state.current_mood)
        # 3. 最近行动关键词(取前 2 条)
        for action in state.recent_actions[-2:]:
            if action:
                # 取行动描述的前 2 个词
                words = action.split()[:2]
                keywords.extend(words)
        # 4. 关系密切的角色名（trust > 60 或 trust < 30）
        for rel in self.state.relationships:
            if rel.character_a == cid or rel.character_b == cid:
                other_id = rel.character_b if rel.character_a == cid else rel.character_a
                if abs(rel.trust - 50) > 20 or abs(rel.affection - 50) > 20:
                    other_name = char_names.get(other_id, "")
                    if other_name:
                        keywords.append(other_name)
        # 5. 当前计划中的关键词
        if state.current_plan:
            keywords.extend(state.current_plan.split()[:3])
        # 去重，限制 15 个关键词
        seen = set()
        result = []
        for k in keywords:
            if k not in seen and len(k) > 0:
                seen.add(k)
                result.append(k)
        return result[:15]

    def _build_story_summary(self) -> str:
        """
        构建压缩后的全量叙事摘要。
        从所有时间步中提取叙事文本，如果步数过多则截取最近的。
        """
        if not self.state or not self.state.timeline:
            return ""
        narratives = []
        max_steps = config.STORY_SUMMARY_MAX_STEPS
        for ts in self.state.timeline:
            if ts.narrative:
                narratives.append(f"[{ts.time_label}] {ts.narrative[:200]}")
        if len(narratives) > max_steps:
            narratives = narratives[-max_steps:]
        return "\n".join(narratives)

    def _snapshot_to_prompt_text(self, snapshot: WorldSnapshot, char_names: dict[str, str]) -> str:
        lines = ["【世界状态快照】"]
        for cid, brief in snapshot.character_briefs.items():
            lines.append(f"- {brief}")
        if snapshot.active_events_summary:
            lines.append(f"【活跃事件】{snapshot.active_events_summary}")
        if snapshot.key_relationship_changes:
            lines.append("【关键关系】")
            lines.extend(f"- {c}" for c in snapshot.key_relationship_changes)
        if snapshot.unresolved_threads:
            lines.append("【未了线索】")
            lines.extend(f"- {t}" for t in snapshot.unresolved_threads)
        return "\n".join(lines)

    async def _generate_character_intent(
        self, character_id: str, active_events: list[WorldEvent],
        time_label: str, world_snapshot: WorldSnapshot,
        current_scheduled_event: str = "",
        affected_events: list[str] = None,
    ) -> dict:
        """为单个角色生成意图"""
        state = self.state.character_states[character_id]
        char_memories = self.state.memories[character_id]

        # P0: 从当前情境自动提取检索关键词
        char_names = {cid: cfg.name for cid, cfg in self.state.characters.items()}
        query_keywords = self._extract_query_keywords(character_id, state, char_names)
        retrieved = memory.retrieve_memories(
            char_memories, self.state.current_step,
            query_keywords=query_keywords,
            max_results=8,
        )

        char_names = {cid: cfg.name for cid, cfg in self.state.characters.items()}
        rel_summary = relationship.get_relationship_summary(
            self.state.relationships, character_id, char_names
        )

        scratchpad_text = character.get_character_scratchpad_text(state)
        snapshot_text = self._snapshot_to_prompt_text(world_snapshot, char_names)

        messages = prompt_action.build_character_action_prompt(
            character=state,
            memories=retrieved,
            relationship_summary=rel_summary,
            world_events=active_events,
            time_label=time_label,
            scratchpad=scratchpad_text,
            world_snapshot=snapshot_text,
            current_scheduled_event=current_scheduled_event,
            character_arc_outline=self.state.character_arc_outline or "",
            current_day=self.state.current_day,
            current_hour=self.state.current_hour,
            current_minute=self.state.current_minute,
            affected_events=affected_events or [],
        )

        async with self._llm_semaphore:  # N8: 并发控制
            response = await llm_client.chat_async(messages, json_mode=True)
        result = llm_client.parse_json_response(response)
        # 防御：LLM 可能对字符串字段返回 null，统一转为空字符串
        for key in ("intent", "destination", "mood", "thoughts", "mood_change", "condition_change"):
            if result.get(key) is None:
                result[key] = ""
        if result.get("importance") is None:
            result["importance"] = 5
        return result

    def _update_character_schedule_from_intent(
        self, character_id: str, intent_data: dict, current_day: int, current_hour: int, current_minute: int = 0
    ) -> None:
        """将 LLM 意图中的 next_event 写入角色个人时间表（使用绝对时间，含防倒退校验）"""
        state = self.state.character_states[character_id]

        # 提取绝对时间参数
        next_day = intent_data.get("next_event_day")
        next_hour = intent_data.get("next_event_hour")
        next_minute = intent_data.get("next_event_minute", 0)
        duration = intent_data.get("next_event_duration", 60)

        # 兼容旧格式：next_event_day 可能是 dict {"day": N, "description": "..."}
        if isinstance(next_day, dict):
            desc = next_day.get("description", "")
            imp = next_day.get("importance", 5)
            next_day = next_day.get("day", current_day)
        else:
            desc = intent_data.get("intent", "自由活动")
            imp = intent_data.get("importance", 5)

        if not desc or next_day is None or next_hour is None:
            return

        try:
            new_day = int(next_day)
            new_hour = int(next_hour)
            new_minute = int(next_minute)
            dur = max(10, int(duration))
        except (ValueError, TypeError):
            logger.warning(f"角色 {character_id} next_event 时间参数无法解析: day={next_day}, hour={next_hour}")
            return

        # P0-2: 防倒退校验 — 确保新事件不早于当前世界时间
        current_total = current_day * 1440 + current_hour * 60 + current_minute
        new_total = new_day * 1440 + new_hour * 60 + new_minute
        if new_total <= current_total:
            logger.warning(
                f"[防倒退] 角色 {character_id} next_event 时间倒退: "
                f"当前 d{current_day} {current_hour:02d}:{current_minute:02d}, "
                f"事件 d{new_day} {new_hour:02d}:{new_minute:02d}。"
                f"自动修正为 +{config.ANTI_REVERSE_MIN_MINUTES}min"
            )
            # 自动修正：当前时间 + 最小偏移
            new_total = current_total + config.ANTI_REVERSE_MIN_MINUTES
            new_day = new_total // 1440
            new_hour = (new_total % 1440) // 60
            new_minute = (new_total % 1440) % 60

        new_event = PersonalEvent(
            day=new_day,
            hour=new_hour,
            minute=new_minute,
            duration=dur,
            description=desc,
            importance=imp,
            source="character",
        )
        state.personal_schedule.append(new_event)
        state.personal_schedule.sort(key=lambda e: (e.day, e.hour, e.minute))

    async def _generate_narrative_with_foreshadowing(
        self,
        interactions: list[Interaction],
        world_events: list[WorldEvent],
        time_label: str,
        world_snapshot: WorldSnapshot,
        char_names: dict[str, str],
        foreshadow_content: str = "",
        light_mode: bool = False,
    ) -> tuple[str, list[str]]:
        """
        P1-5 修复：统一单次 LLM 调用生成所有场景叙事。
        在 prompt 中按角色时间线排序，LLM 有全局视角可保证时序正确性和场景间过渡。
        返回 (narrative_text, foreshadowing_list)
        """
        snapshot_text = self._snapshot_to_prompt_text(world_snapshot, char_names)
        story_summary = self._build_story_summary()

        # 构建涉及角色的 profile 列表（防混淆）
        char_profiles = []
        seen_cids = set()
        for ia in interactions:
            cid = ia.character_id
            if cid in seen_cids:
                continue
            seen_cids.add(cid)
            cfg = self.state.characters.get(cid)
            if cfg:
                char_profiles.append({
                    "name": cfg.name,
                    "gender": cfg.gender,
                    "role": cfg.role,
                    "personality": cfg.personality,
                    "background": cfg.background,
                    "speaking_style": cfg.speaking_style,
                })

        narrative_style = self.state.setting.tone if self.state.setting.tone else ""

        # P1-5: 统一单次 LLM 调用 —— 所有场景一次性传入
        # 按场景分组用于叙事内的位置标记，但 prompt 中提供时间线顺序指导
        loc_groups: dict[str, list[Interaction]] = {}
        for ia in interactions:
            loc = ia.location if ia.location else "未知位置"
            if loc not in loc_groups:
                loc_groups[loc] = []
            loc_groups[loc].append(ia)

        all_narrative_parts = []
        all_foreshadowing = []

        try:
            messages = prompt_narrative.build_narrative_prompt(
                story_setting=f"{self.state.setting.era} - {self.state.setting.location}。{self.state.setting.description}",
                time_label=time_label,
                story_summary=story_summary,
                world_snapshot=snapshot_text,
                world_events=world_events,
                interactions=interactions,  # 全部传入，不按场景过滤
                char_names=char_names,
                foreshadow_content=foreshadow_content,
                char_profiles=char_profiles,
                narrative_style=narrative_style,
                loc_groups=loc_groups,  # P1-5: 传入场景分组信息供排序指导
            )

            async with self._llm_semaphore:
                response = await llm_client.chat_async(messages, json_mode=True, max_tokens=4096)
            result = llm_client.parse_json_response(response)

            nar = result.get("narrative", "")
            fs = result.get("foreshadowing", [])

            if nar:
                # 如果 LLM 已经按场景标记好了，直接使用；否则加前缀
                if "【" in nar:
                    all_narrative_parts.append(nar)
                else:
                    all_narrative_parts.append(nar)
            all_foreshadowing.extend(fs)
        except Exception as e:
            logger.error(f"叙事生成失败: {e}")
            # 兜底：按场景简单拼接
            for loc, loc_interactions in loc_groups.items():
                briefs = []
                for ia in loc_interactions:
                    name = char_names.get(ia.character_id, ia.character_id)
                    briefs.append(f"{name}{ia.intent}")
                all_narrative_parts.append(f"【{loc}】\n" + "；".join(briefs))

        return "\n\n".join(all_narrative_parts), all_foreshadowing

    async def _run_reflections(self, char_ids: list[str], step: int, time_label: str):
        for cid in char_ids:
            try:
                state = self.state.character_states[cid]
                recent_mem = memory.get_recent_memories(self.state.memories[cid], last_n_steps=6)
                if not recent_mem:
                    continue

                messages = prompt_reflection.build_reflection_prompt(state, recent_mem)
                async with self._llm_semaphore:
                    response = await llm_client.chat_async(messages, json_mode=True)
                result = llm_client.parse_json_response(response)

                for ref in result.get("reflections", []):
                    importance = max(config.REFLECTION_IMPORTANCE_FLOOR, ref.get("importance", 6))
                    memory.add_memory(
                        self.state.memories[cid],
                        step=step,
                        timestamp=time_label,
                        description=ref.get("content", ""),
                        importance=importance,
                        is_reflection=True,
                        tags=ref.get("tags", []),
                    )

                new_goal = result.get("updated_goal")
                if new_goal:
                    state.long_term_goal = new_goal

                new_plan = result.get("suggested_plan")
                if new_plan:
                    state.daily_plan = new_plan

            except Exception as e:
                logger.error(f"角色 {cid} 反思失败: {e}")

    async def _judge_event_impact(self, event: WorldEvent):
        char_names = {cid: cfg.name for cid, cfg in self.state.characters.items()}
        char_brief = character.get_all_characters_brief(self.state.character_states)
        recent = self._recent_narrative_text()

        messages = prompt_event_judge.build_world_event_judge_prompt(
            event_description=event.description,
            event_type=event.event_type.value,
            story_setting=f"{self.state.setting.era} - {self.state.setting.location}",
            characters_brief=char_brief,
            recent_narrative=recent,
        )

        async with self._llm_semaphore:
            response = await llm_client.chat_async(messages, json_mode=True)
        result = llm_client.parse_json_response(response)

        event.impact_description = result.get("event_impact", "")
        event.affected_characters = []

        for affected in result.get("affected_characters", []):
            if affected.get("would_be_involved"):
                event.affected_characters.append(affected["character_id"])

    # ========================================================
    # 玩家干预
    # ========================================================

    def add_player_event(self, event_type: str, description: str, hour: Optional[int] = None) -> str:
        if self.state is None:
            raise RuntimeError("故事未初始化")

        if hour is not None:
            # 兼容旧逻辑：同时写入 event_queue 和所有角色的 personal_schedule
            self.state.add_scheduled_event(ScheduledEvent(
                hour=int(hour) % 24,
                day=self.state.current_day,
                description=f"[玩家] {description}",
                source="player",
                importance=8,
            ))
            # 写入所有角色的个人时间表
            for cid, state in self.state.character_states.items():
                state.personal_schedule.append(PersonalEvent(
                    day=self.state.current_day,
                    hour=int(hour) % 24,
                    description=f"[玩家] {description}",
                    importance=8,
                    source="player",
                ))
                state.personal_schedule.sort(key=lambda e: (e.day, e.hour))
            return f"已安排事件：{description}（将在 {hour:02d}:00 发生）"

        event, msg = world_event.add_player_event(
            self.state.pending_player_events,
            event_type=event_type,
            description=description,
            current_step=self.state.current_step,
        )
        return msg

    # ========================================================
    # 存档 / 读档
    # ========================================================

    def save_story(self, filepath: str) -> None:
        if self.state is None:
            raise RuntimeError("故事未初始化")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.state.to_save_dict(), f, ensure_ascii=False, indent=2)

    def load_story(self, filepath: str) -> None:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.state = StoryState.from_save_dict(data)
        self.rebuild_narrative_file()
