"""
时间推进控制器 - 封装时间推进逻辑。
当前实现为离散时间步（step），未来可替换为连续时间。
替换时只需实现相同的接口方法即可。
"""

from __future__ import annotations

import config
from models.schemas import TimeSlot


class TimeController:
    """
    时间推进控制器。

    当前为离散时间步实现（morning → afternoon → evening → 换天）。
    未来可替换为连续时间实现（如每小时推进），只需实现相同接口。
    """

    def __init__(self):
        self.current_step: int = 0
        self.current_day: int = 1
        self.current_slot_index: int = 0

    def get_time_slot(self) -> TimeSlot:
        """获取当前时段"""
        slots = [TimeSlot.MORNING, TimeSlot.AFTERNOON, TimeSlot.EVENING]
        return slots[self.current_slot_index % 3]

    def advance(self) -> TimeSlot:
        """推进一个时间步，返回新的时段"""
        self.current_slot_index += 1
        if self.current_slot_index % 3 == 0:
            self.current_day += 1
        self.current_step += 1
        return self.get_time_slot()

    def get_time_label(self, starting_date: str) -> str:
        """生成时间显示标签"""
        slot = self.get_time_slot()
        slot_label = config.TIME_SLOT_LABELS.get(slot.value, slot.value)
        return f"{starting_date} 第{self.current_day}天 {slot_label}"

    def is_new_day(self) -> bool:
        """判断当前步是否为新的一天开始（清晨）"""
        return self.current_slot_index % 3 == 0

    def get_slots_per_day(self) -> int:
        """每天有多少个时段"""
        return len(config.TIME_SLOTS)

    def reset(self) -> None:
        """重置时间"""
        self.current_step = 0
        self.current_day = 1
        self.current_slot_index = 0

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "current_step": self.current_step,
            "current_day": self.current_day,
            "current_slot_index": self.current_slot_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimeController":
        """从字典反序列化"""
        tc = cls()
        tc.current_step = data.get("current_step", 0)
        tc.current_day = data.get("current_day", 1)
        tc.current_slot_index = data.get("current_slot_index", 0)
        return tc
