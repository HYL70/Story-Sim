"""
关系系统 - 角色之间的关系矩阵管理
"""

from __future__ import annotations

import logging
from typing import Optional

from models.schemas import Relationship

logger = logging.getLogger(__name__)


def init_relationships(character_ids: list[str]) -> list[Relationship]:
    """初始化所有角色对之间的关系"""
    relationships = []
    for i, a in enumerate(character_ids):
        for j, b in enumerate(character_ids):
            if i < j:  # 只存一对（A-B），不用存 B-A
                relationships.append(
                    Relationship(character_a=a, character_b=b)
                )
    return relationships


def get_relationship(
    relationships: list[Relationship],
    char_a: str,
    char_b: str,
) -> Optional[Relationship]:
    """获取两个角色之间的关系"""
    for r in relationships:
        if (r.character_a == char_a and r.character_b == char_b) or \
           (r.character_a == char_b and r.character_b == char_a):
            return r
    return None


def update_relationship(
    relationships: list[Relationship],
    char_a: str,
    char_b: str,
    trust_delta: int = 0,
    affection_delta: int = 0,
    description: Optional[str] = None,
) -> Relationship:
    """
    更新两个角色之间的关系。
    如果关系不存在则创建。
    """
    r = get_relationship(relationships, char_a, char_b)
    if r is None:
        r = Relationship(character_a=char_a, character_b=char_b)
        relationships.append(r)

    r.trust = max(-100, min(100, r.trust + trust_delta))
    r.affection = max(-100, min(100, r.affection + affection_delta))

    if description:
        r.description = description

    return r


def get_relationship_summary(
    relationships: list[Relationship],
    character_id: str,
    char_names: dict[str, str],
) -> str:
    """
    生成某角色与所有其他角色的关系摘要，用于注入 prompt。
    """
    lines = []
    for r in relationships:
        if r.character_a == character_id:
            other_id = r.character_b
        elif r.character_b == character_id:
            other_id = r.character_a
        else:
            continue

        other_name = char_names.get(other_id, other_id)

        # 生成关系描述
        trust_desc = _describe_value(r.trust, "信任", ["极度不信任", "不信任", "一般", "信任", "极度信任"])
        affection_desc = _describe_value(r.affection, "好感", ["极度厌恶", "冷淡", "普通", "亲近", "深爱"])
        lines.append(f"- 与{other_name}：{affection_desc}，{trust_desc}（{r.description}）")

    return "\n".join(lines) if lines else "（暂无关系记录）"


def get_all_relationships_text(
    relationships: list[Relationship],
    char_names: dict[str, str],
) -> str:
    """生成所有关系的动态描述，用于世界事件影响判定"""
    lines = []
    for r in relationships:
        name_a = char_names.get(r.character_a, r.character_a)
        name_b = char_names.get(r.character_b, r.character_b)
        if r.trust != 50 or r.affection != 50:
            lines.append(f"- {name_a} 与 {name_b}：信任{r.trust}，好感{r.affection}（{r.description}）")
    return "\n".join(lines) if lines else "（所有角色关系正常）"


def _describe_value(value: int, prefix: str, labels: list[str]) -> str:
    """将 -100~100 的数值转为描述"""
    if value <= -60:
        return labels[0]
    elif value <= -20:
        return labels[1]
    elif value <= 20:
        return labels[2]
    elif value <= 60:
        return labels[3]
    else:
        return labels[4]
