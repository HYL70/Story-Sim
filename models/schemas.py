"""
数据模型定义 - 所有 Pydantic BaseModel
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================
# 枚举类型
# ============================================================

class TimeSlot(str, Enum):
    """旧三段式时段，仅用于旧存档兼容"""
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


class ImportanceLevel(str, Enum):
    TRIVIAL = "trivial"       # 1-3
    NORMAL = "normal"         # 4-6
    SIGNIFICANT = "significant"  # 7-9
    CRITICAL = "critical"     # 10


class EventType(str, Enum):
    PLOT_EVENT = "plot_event"
    ENVIRONMENT = "environment"


class EventSource(str, Enum):
    PLAYER = "player"
    SYSTEM_AUTO = "system_auto"


# ============================================================
# 故事背景设定
# ============================================================

class StorySetting(BaseModel):
    """故事世界设定"""
    title: str = Field(default="未命名故事", description="故事标题")
    era: str = Field(default="架空古代", description="时代背景")
    location: str = Field(default="皇宫", description="主要场景")
    description: str = Field(default="", description="背景描述（自由文本）")
    tone: str = Field(default="暗流涌动", description="故事基调")
    starting_date: str = Field(default="永平元年 春", description="故事起始时间（模糊描述，UI 显示用）")
    starting_date_iso: str = Field(default="2024-10-05", description="故事起始精确日期（YYYY-MM-DD，用于 time_label）")


# ============================================================
# 角色配置（设定阶段，游戏开始后锁定）
# ============================================================

class CharacterConfig(BaseModel):
    """角色人格配置 - 设定阶段确定，游戏中不可修改"""
    character_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = Field(description="姓名")
    role: str = Field(default="", description="身份/头衔")
    age: int = Field(default=20, description="年龄")
    gender: str = Field(default="女", description="性别")
    personality: str = Field(default="", description="性格描述（2-3句话）")
    background: str = Field(default="", description="过往经历（2-3句话）")
    motivation: str = Field(default="", description="核心动机/欲望")
    speaking_style: str = Field(default="", description="说话风格（如：温婉、尖锐、话少）")
    secret: str = Field(default="", description="不为人知的秘密")
    fear: str = Field(default="", description="最害怕的事")
    initial_location: str = Field(default="", description="初始位置")
    initial_mood: str = Field(default="平静", description="初始心情")


# ============================================================
# 角色运行时状态
# ============================================================

class CharacterState(BaseModel):
    """角色运行时状态 - 每步更新"""
    character_id: str
    config: CharacterConfig

    # === 基础状态 ===
    current_location: str = ""
    current_mood: str = "平静"
    physical_condition: str = Field(default="精神不错", description="身体状态文字描述，如'精神不错'、'有些疲惫'、'感冒了'")
    last_action: str = ""
    step_count: int = 0

    # === Stanford Scratchpad 扩展 ===
    long_term_goal: str = Field(default="", description="长期目标（从motivation派生，反思可更新）")
    daily_plan: str = Field(default="", description="当日计划（每天开始时生成/更新）")
    current_plan: str = Field(default="", description="当前时段计划（每时段更新）")
    recent_actions: list[str] = Field(default_factory=list, description="最近3步的行动记录")
    movement_path: list[str] = Field(default_factory=list, description="当前时段的移动路径（供未来地图使用）")

    # === 个人时间表（per-agent schedule）===
    personal_schedule: list[PersonalEvent] = Field(default_factory=list, description="个人日程，按 (day, hour) 排序")


# ============================================================
# 记忆系统
# ============================================================

class MemoryEntry(BaseModel):
    """单条记忆"""
    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    step: int = Field(description="发生在第几步")
    timestamp: str = Field(default="", description="故事内时间")
    description: str = Field(description="记忆内容（1-2句话）")
    importance: int = Field(default=5, ge=1, le=10, description="重要性 1-10")
    is_reflection: bool = Field(default=False, description="是否为反思生成的高层洞察")
    involved_characters: list[str] = Field(default_factory=list, description="涉及的其他角色ID")
    tags: list[str] = Field(default_factory=list, description="关键词标签，用于检索")


# ============================================================
# 关系系统
# ============================================================

class Relationship(BaseModel):
    """两个角色之间的关系"""
    character_a: str = Field(description="角色A的ID")
    character_b: str = Field(description="角色B的ID")
    trust: int = Field(default=50, ge=-100, le=100, description="信任度 -100到100")
    affection: int = Field(default=50, ge=-100, le=100, description="好感度 -100到100")
    description: str = Field(default="普通关系", description="关系描述")


# ============================================================
# 世界事件
# ============================================================

class WorldEvent(BaseModel):
    """世界事件 - 玩家添加或系统自动生成"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    event_type: EventType = Field(description="事件类型")
    description: str = Field(description="事件描述")
    source: EventSource = Field(description="事件来源")
    triggered_at_step: int = Field(description="在哪一步插入")
    active_until_step: Optional[int] = Field(default=None, description="持续到哪一步")
    affected_characters: list[str] = Field(default_factory=list, description="被卷入的角色ID")
    impact_description: str = Field(default="", description="对角色的实际影响描述")


class WorldSnapshot(BaseModel):
    """每个时间步结束后的结构化状态摘要（轻量版真相文件）"""
    step: int = Field(description="对应的时间步")
    character_briefs: dict[str, str] = Field(
        default_factory=dict, description="{角色ID: '位置/心情/最近行动'}"
    )
    active_events_summary: str = Field(default="", description="活跃事件简要")
    key_relationship_changes: list[str] = Field(default_factory=list, description="关系大幅变动摘要")
    unresolved_threads: list[str] = Field(default_factory=list, description="未解决的剧情线索")


# ============================================================
# 事件调度（独立事件调度时间系统）— 保留用于旧存档兼容
# ============================================================

class PersonalEvent(BaseModel):
    """角色个人日程条目 - 按时间排序，支持中间插入"""
    day: int = Field(ge=1, description="事件发生在第几天")
    hour: int = Field(ge=0, le=23, description="事件发生的小时 (0-23)")
    minute: int = Field(default=0, ge=0, le=59, description="事件发生的分钟 (0-59)")
    duration: int = Field(default=60, ge=10, description="事件持续分钟数（不少于10分钟）")
    description: str = Field(description="事件简述")
    importance: int = Field(default=5, ge=1, le=10, description="预估重要性")
    source: str = Field(default="schedule", description="来源: schedule/character/player/auto")


# ============================================================
# 事件调度（保留旧模型，新逻辑用 PersonalEvent）
# ============================================================

class ScheduledEvent(BaseModel):
    """事件调度队列元素 - 定义某个时刻会发生什么"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    hour: int = Field(ge=0, le=23, description="事件发生的小时 (0-23)")
    day: int = Field(default=1, description="事件发生在第几天")
    description: str = Field(description="事件简述，如'晨会开始'")
    source: str = Field(default="schedule", description="来源: schedule/character/player/auto")
    importance: int = Field(default=5, ge=1, le=10, description="预估重要性")


# ============================================================
# 故事事件（角色行动产生的事件）
# ============================================================

class StoryEvent(BaseModel):
    """单次角色行动产生的事件"""
    character_id: str = Field(description="执行者角色ID")
    action: str = Field(description="行动描述")
    dialogue: Optional[str] = Field(default=None, description="说的话")
    internal_thought: Optional[str] = Field(default=None, description="内心独白")
    target: Optional[str] = Field(default=None, description="互动目标角色ID")
    mood_change: str = Field(default="", description="心情变化")
    condition_change: str = Field(default="", description="身体状态变化，如'开始头疼'、'感冒加重'")
    importance: int = Field(default=5, ge=1, le=10)

    @field_validator("mood_change", "condition_change", mode="before")
    @classmethod
    def _none_to_empty(cls, v: Any) -> str:
        return v if v else ""


# ============================================================
# 世界模拟（碰撞检测 + 互动）
# ============================================================

class EncounterType(str, Enum):
    """碰撞类型"""
    DIALOGUE = "dialogue"        # 对话互动（极端关系）
    OBSERVATION = "observation"  # 旁观（中等关系，看到但没搭话）
    PASSING = "passing"          # 擦肩而过（无关系记录）


class Encounter(BaseModel):
    """碰撞事件：两个角色在同一位置相遇"""
    character_a: str = Field(description="角色A的ID")
    character_b: str = Field(description="角色B的ID")
    location: str = Field(description="相遇地点")
    encounter_type: EncounterType = Field(description="碰撞类型")
    # dialogue 类型专用字段
    dialogue: list[dict] = Field(default_factory=list, description="对话列表 [{'speaker': '角色名', 'line': '台词'}, ...]")
    outcome: str = Field(default="", description="对话后的结果描述")
    # P0 关系闭环: LLM 返回的完整数据（含 relationship_delta），存档时 exclude
    dialogue_data: Optional[dict] = Field(default=None, exclude=True, description="LLM 对话生成的完整结果数据")
    # observation 类型专用字段
    observer: str = Field(default="", description="旁观者角色ID")


class Interaction(BaseModel):
    """完整互动记录（角色意图 + 世界模拟产出的结构化结果）"""
    character_id: str = Field(description="角色ID")
    intent: str = Field(default="", description="角色意图（想去哪、想做什么）")
    destination: str = Field(default="", description="目标位置")
    actual_action: str = Field(default="", description="实际发生的事（经世界模拟后）")
    location: str = Field(default="", description="最终位置")
    encounters: list[Encounter] = Field(default_factory=list, description="本步涉及的碰撞")
    mood_change: str = Field(default="")
    condition_change: str = Field(default="")
    importance: int = Field(default=5, ge=1, le=10)
    internal_thought: str = Field(default="")

    @field_validator("mood_change", "condition_change", mode="before")
    @classmethod
    def _none_to_empty(cls, v: Any) -> str:
        return v if v else ""


# ============================================================
# 时间步状态
# ============================================================

class TimeStep(BaseModel):
    """单个时间步的完整状态快照"""
    step: int = Field(description="步骤编号，从1开始")
    day: int = Field(description="第几天")
    hour: int = Field(default=8, description="事件发生的小时")
    time_slot: Optional[TimeSlot] = Field(default=None, description="时段（仅旧存档兼容）")
    time_label: str = Field(default="", description="时间显示标签，如'2024年10月5日 08:00'")
    events: list[StoryEvent] = Field(default_factory=list, description="本步发生的事件")
    interactions: list[Interaction] = Field(default_factory=list, description="本步的互动记录（世界模拟结果）")
    active_world_events: list[WorldEvent] = Field(default_factory=list, description="本步生效的世界事件")
    narrative: str = Field(default="", description="LLM生成的叙事文本")
    memories_added: dict[str, list[str]] = Field(default_factory=dict, description="本步为各角色新增的记忆ID")
    skipped: bool = Field(default=False, description="是否被跳过（日常流水账，不生成叙事）")
    scheduled_event: Optional[ScheduledEvent] = Field(default=None, description="触发本步的调度事件")


# ============================================================
# 故事全局状态
# ============================================================

class StoryState(BaseModel):
    """故事完整状态 - 可序列化为 JSON 存档"""
    setting: StorySetting = Field(default_factory=StorySetting)
    characters: dict[str, CharacterConfig] = Field(default_factory=dict, description="角色配置 {id: config}")
    character_states: dict[str, CharacterState] = Field(default_factory=dict, description="角色状态 {id: state}")
    memories: dict[str, list[MemoryEntry]] = Field(default_factory=dict, description="角色记忆 {id: [memory]}")
    relationships: list[Relationship] = Field(default_factory=list, description="关系列表")
    timeline: list[TimeStep] = Field(default_factory=list, description="时间线")
    world_snapshots: list[WorldSnapshot] = Field(default_factory=list, description="每步世界状态快照")
    active_world_events: list[WorldEvent] = Field(default_factory=list, description="当前活跃的世界事件")
    pending_player_events: list[WorldEvent] = Field(default_factory=list, description="玩家待处理事件队列")
    event_queue: list[ScheduledEvent] = Field(default_factory=list, description="事件调度队列（按时间排序）")
    current_step: int = Field(default=0, description="当前步骤")
    current_day: int = Field(default=1, description="当前天数")
    current_hour: int = Field(default=8, ge=0, le=23, description="当前小时 (0-23)")
    current_minute: int = Field(default=0, ge=0, le=59, description="当前分钟 (0-59)")
    steps_since_auto_event: int = Field(default=0, description="距上次自动事件的步数")
    consecutive_skipped: int = Field(default=0, description="连续被快进跳过的步数")
    narrative_step_count: int = Field(default=0, description="有叙事的步数计数")
    occupancy: dict[str, dict] = Field(default_factory=dict, description="角色占用状态 {cid: {busy_until_day/hour/minute, locked_location, activity}}")

    # === 叙事上下文 ===
    narrative_summary: str = Field(default="", description="压缩后的全量叙事摘要")
    character_arc_outline: str = Field(default="", description="角色弧光大纲（可选）")
    is_finished: bool = Field(default=False, description="故事是否已结束")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="创建时间")
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="最后更新时间")

    def sort_event_queue(self) -> None:
        """对事件队列按 (day, hour) 排序"""
        self.event_queue.sort(key=lambda e: (e.day, e.hour))

    def add_scheduled_event(self, event: ScheduledEvent) -> None:
        """向事件队列插入一个事件并自动排序"""
        self.event_queue.append(event)
        self.sort_event_queue()

    def pop_next_event(self) -> Optional[ScheduledEvent]:
        """取出并移除队列中的下一个事件"""
        if not self.event_queue:
            return None
        self.sort_event_queue()
        return self.event_queue.pop(0)

    def get_time_label(self) -> str:
        """生成当前时间标签，如 '2024-10-05 08:30'"""
        try:
            base = datetime.strptime(self.setting.starting_date_iso, "%Y-%m-%d")
            actual = base + timedelta(days=self.current_day - 1)
            date_str = actual.strftime("%Y-%m-%d")
        except (ValueError, OSError):
            date_str = self.setting.starting_date_iso
        return f"{date_str} {self.current_hour:02d}:{self.current_minute:02d}"

    def to_save_dict(self) -> dict:
        """导出为可保存的字典"""
        return self.model_dump()

    @classmethod
    def from_save_dict(cls, data: dict) -> "StoryState":
        """从保存的字典加载，兼容旧存档"""
        # 旧存档兼容：current_slot_index → current_hour
        if "current_slot_index" in data and "current_hour" not in data:
            slot = data["current_slot_index"] % 3
            data["current_hour"] = [8, 14, 19][slot]
        # 旧存档兼容：无 event_queue
        if "event_queue" not in data:
            data["event_queue"] = []
        # 旧存档兼容：无 starting_date_iso
        if "starting_date_iso" not in data.get("setting", {}):
            if isinstance(data.get("setting"), dict):
                data["setting"]["starting_date_iso"] = "2024-10-05"
        # 旧存档兼容：TimeStep 中无 hour 字段，从 time_slot 推算
        for ts_data in data.get("timeline", []):
            if "hour" not in ts_data and "time_slot" in ts_data:
                slot_map = {"morning": 8, "afternoon": 14, "evening": 19}
                ts_data["hour"] = slot_map.get(ts_data["time_slot"], 8)
            if "scheduled_event" not in ts_data:
                ts_data["scheduled_event"] = None
            if "interactions" not in ts_data:
                ts_data["interactions"] = []
            if "day" not in ts_data:
                ts_data["day"] = 1
        return cls.model_validate(data)
