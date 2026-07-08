"""
叙事渲染器 - 将角色行动转换为输出格式。
当前实现为纯文本 Markdown 叙事。
未来可替换为：场景脚本格式、可视化指令、语音合成文本等。
"""

from __future__ import annotations

from models.schemas import StoryEvent, WorldEvent, WorldSnapshot


class NarrativeRenderer:
    """
    叙事渲染器基类。

    当前 render() 方法返回纯文本 Markdown。
    子类可覆盖为其他格式。
    """

    def render(
        self,
        narrative_text: str,
        events: list[StoryEvent],
        world_snapshot: WorldSnapshot,
        world_events: list[WorldEvent],
        char_names: dict[str, str],
        time_label: str,
    ) -> str:
        """
        将叙事渲染为输出格式。
        当前实现：返回 Markdown 文本。

        Args:
            narrative_text: LLM 生成的原始叙事文本
            events: 本步的角色行动事件
            world_snapshot: 世界状态快照
            world_events: 活跃世界事件
            char_names: 角色ID→名字映射
            time_label: 时间标签

        Returns:
            渲染后的文本（当前为 Markdown）
        """
        return narrative_text

    def render_section_header(self, day: int, slot_label: str) -> str:
        """渲染段落标题"""
        return f"\n\n---\n\n### 📍 第{day}天 {slot_label}\n\n"

    def render_error(self, error_msg: str) -> str:
        """渲染错误信息"""
        return f"\n\n❌ 推进失败: {error_msg}\n"
