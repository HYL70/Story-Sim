"""
Gradio 界面 - AI 群像故事游戏
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import gradio as gr

import config
from models.schemas import StorySetting, CharacterConfig
from engine.story_engine import StoryEngine
from engine import character as char_module

# ============================================================
# 初始化
# ============================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 推进锁（防止重复点击导致挂起）
_advancing = False

# Bug 日志文件
_log_path = Path(__file__).parent.parent / "data" / "saves" / "debug.log"
_log_path.parent.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(_log_path, encoding="utf-8", mode="a")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_file_handler)

engine = StoryEngine()

# 预设角色模板（大学寝室日常）
PRESET_CHARACTERS = """[
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
    "initial_mood": "懒散"
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
    "initial_mood": "无奈"
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
    "initial_mood": "精力充沛"
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
    "initial_mood": "专注"
  }
]"""

PRESET_SETTING = {
    "title": "6-309日常",
    "era": "现代中国",
    "location": "梧桐大学·学生公寓6号楼·309室",
    "description": "一个普通的四人男生寝室，朝南，窗外是校园围墙和一排杨树。四张床，两上两下，两张书桌拼在一起，上面堆着外卖盒、快递箱、课本和游戏外设。阳台门永远半开着透气，门口地上永远有一双刚踢掉的球鞋。寝室里发生的一切无非是：程野打游戏骂队友，沈一鸣拖地念叨你们能不能爱惜点，李骁在阳台跟女朋友腻歪，江一苇戴着耳机埋头画图，偶尔抬头来一句冷幽默把所有人逗笑。没有英雄，没有反派，没有感人肺腑的故事——只有四个男的住在一个房间里，互相嫌弃又互相习惯，就这样过完大三这一年。",
    "tone": "轻松 · 日常 · 带点幽默",
    "starting_date": "10月下旬",
    "starting_date_iso": "2024-10-25"
}


# ============================================================
# Gradio 界面
# ============================================================

def create_ui():
    with gr.Blocks(
        title="AI 群像故事",
    ) as app:
        gr.Markdown("# 🏫 AI 群像故事引擎", elem_classes="text-center")

        # --- 故事设定区域（游戏开始前显示） ---
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 📖 故事设定")
                setting_title = gr.Textbox(label="故事标题", value=PRESET_SETTING["title"])
                setting_era = gr.Textbox(label="时代背景", value=PRESET_SETTING["era"])
                setting_location = gr.Textbox(label="主要场景", value=PRESET_SETTING["location"])
                setting_desc = gr.Textbox(
                    label="背景描述", lines=4,
                    value=PRESET_SETTING["description"]
                )
                setting_tone = gr.Textbox(label="故事基调", value=PRESET_SETTING["tone"])
                setting_start = gr.Textbox(label="起始时间（显示用）", value=PRESET_SETTING["starting_date"])
                setting_start_iso = gr.Textbox(label="起始日期（YYYY-MM-DD）", value=PRESET_SETTING.get("starting_date_iso", "2024-10-05"))

            with gr.Column(scale=1):
                gr.Markdown("### 👥 角色设定（JSON格式）")
                chars_input = gr.Code(
                    label="角色配置",
                    value=PRESET_CHARACTERS,
                    language="json",
                    lines=18,
                )
                gr.Markdown("*角色设定确认后不可修改*", elem_classes="text-xs text-gray-500")

        init_btn = gr.Button("🎭 开始新故事", variant="primary", size="lg")
        init_status = gr.Textbox(label="状态", interactive=False)

        # --- 启动区域的加载存档（始终可见） ---
        gr.Markdown("---")
        load_file_setup = gr.File(label="📂 选择存档文件加载", file_types=[".json"])
        load_btn_setup = gr.Button("📂 读取存档并继续")
        load_setup_status = gr.Textbox(label="加载状态", interactive=False)

        # --- 故事主界面（游戏开始后显示） ---
        with gr.Row(visible=False) as game_row:
            # 左侧：角色状态 + 日程面板
            with gr.Column(scale=1):
                gr.Markdown("### 👥 角色状态")
                char_status = gr.Markdown("加载中...")
                gr.Markdown("---")
                gr.Markdown("### 📅 角色日程表")
                schedule_display = gr.Markdown("加载中...")

            # 右侧：故事叙事区
            with gr.Column(scale=2):
                gr.Markdown("### 📜 故事叙事")
                narrative_box = gr.Markdown(elem_id="narrative-box", elem_classes="story-text")

        # --- 控制区域 ---
        with gr.Row(visible=False) as control_row:
            with gr.Column():
                gr.Markdown("### 🌍 世界干预（下个时段生效）")
                gr.Markdown(
                    '<span style="font-size:0.75rem;color:#888">'
                    "事件格式要求：描述一个清晰的具体事件，包含人物/地点/事件本身。"
                    "<br>✅ 示例：\"学校突然宣布今年的学园祭预算被削减了一半，各班需要自行筹措经费\""
                    "<br>✅ 示例：\"台风预警发布，明天可能停课一天\""
                    "<br>❌ 避免模糊描述：\"发生了大事\"或\"学校出事了\""
                    "</span>",
                    elem_classes=["text-xs"],
                )
                with gr.Row():
                    event_type = gr.Radio(
                        choices=["plot_event", "environment"],
                        value="plot_event",
                        label="事件类型",
                    )
                event_input = gr.Textbox(
                    label="事件描述",
                    placeholder='如："学园祭执行委员会名单突然被更换" 或 "台风预警发布明天可能停课"',
                    lines=2,
                )
                add_event_btn = gr.Button("⚡ 插入事件", variant="secondary")
                event_feedback = gr.Markdown("", elem_classes=["text-xs"])
                pending_events_display = gr.Markdown("", elem_classes=["text-xs"])

            with gr.Column():
                gr.Markdown("### ⚙️ 控制")
                with gr.Row():
                    advance_btn = gr.Button("▶️ 推进一步", variant="primary")
                    auto_btn = gr.Button("⏩ 自动推进5步", variant="secondary")
                with gr.Row():
                    save_btn = gr.Button("💾 保存存档")
                    load_btn = gr.Button("📂 加载存档")
                    step_info = gr.Textbox(label="时间步", interactive=False)
                world_clock_display = gr.Markdown("", elem_classes="text-center")

        active_events_display = gr.Markdown(visible=False)

        # --- 存档文件 ---
        save_file = gr.File(label="存档文件", visible=False)

        # ============================================================
        # 事件处理
        # ============================================================

        async def on_init(
            title, era, location, description, tone, start_date, start_date_iso, chars_json
        ):
            try:
                # 解析角色配置
                chars_data = json.loads(chars_json)
                characters = [CharacterConfig.model_validate(c) for c in chars_data]

                if not characters:
                    return "错误：至少需要1个角色"

                # 初始化故事
                setting = StorySetting(
                    title=title, era=era, location=location,
                    description=description, tone=tone, starting_date=start_date,
                    starting_date_iso=start_date_iso or "2024-10-05",
                )

                opening = engine.init_story(setting, characters)

                # 异步生成初始日程
                await engine.init_story_schedule()

                # 生成角色状态文本
                status_text = _build_char_status()
                schedule_text = _build_schedule_display()
                clock_text = _build_world_clock()

                narrative_md = f"### 📖 {title}\n\n{opening}"
                step_text = f"第 {engine.state.current_step} 步 | 第 {engine.state.current_day} 天 | {engine.state.current_hour:02d}:00"

                return (
                    gr.update(visible=True),
                    gr.update(visible=True),
                    gr.update(visible=True),
                    status_text,
                    schedule_text,
                    narrative_md,
                    gr.update(value=step_text),
                    clock_text,
                    gr.update(visible=True),
                    "故事初始化成功！",
                )
            except Exception as e:
                logger.exception("初始化失败")
                return (
                    gr.update(visible=False),
                    gr.update(visible=False),
                    gr.update(visible=False),
                    "", "", "", "",
                    gr.update(visible=False),
                    gr.update(value=""),
                    f"错误: {e}",
                )

        def on_load_from_setup(file):
            """启动区域加载存档，加载成功后显示游戏界面"""
            if file is None:
                return (
                    gr.update(visible=False), gr.update(visible=False), gr.update(visible=False),
                    "", "", "", "",
                    gr.update(visible=False),
                    "⚠️ 请先选择存档文件",
                )
            try:
                filepath = file.name if hasattr(file, 'name') else str(file)
                engine.load_story(filepath)
                status_text = _build_char_status()
                schedule_text = _build_schedule_display()
                clock_text = _build_world_clock()

                # 重建叙事（跳过被跳过的步骤）
                narratives = []
                for ts in engine.state.timeline:
                    if ts.narrative and not getattr(ts, 'skipped', False):
                        narratives.append(ts.narrative)

                full_narrative = f"### 📖 {engine.state.setting.title}\n\n" + "\n\n---\n\n".join(narratives)
                step = engine.state.current_step
                day = engine.state.current_day
                hour = engine.state.current_hour
                step_text = f"第 {step} 步 | 第 {day} 天 | {hour:02d}:00"

                return (
                    gr.update(visible=True), gr.update(visible=True), gr.update(visible=True),
                    status_text, schedule_text, full_narrative,
                    gr.update(value=step_text),
                    clock_text,
                    gr.update(visible=True),
                    f"✅ 存档加载成功！故事已推进到第 {step} 步",
                )
            except Exception as e:
                logger.exception("启动加载失败")
                return (
                    gr.update(visible=False), gr.update(visible=False), gr.update(visible=False),
                    "", "", "", "",
                    gr.update(visible=False),
                    f"❌ 加载失败: {e}",
                )

        async def on_advance():
            global _advancing
            if _advancing:
                logger.warning("推进正在进行中，忽略重复点击")
                return (
                    gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
                    "⏳ 正在推进中，请稍候...",
                )
            _advancing = True
            try:
                narrative = await engine.advance_one_step()
                status_text = _build_char_status()
                schedule_text = _build_schedule_display()
                clock_text = _build_world_clock()
                step = engine.state.current_step
                day = engine.state.current_day
                hour = engine.state.current_hour
                step_text = f"第 {step} 步 | 第 {day} 天 | {hour:02d}:{engine.state.current_minute:02d}"

                # 活跃事件
                events_text = _build_events_text()

                # 快进判断：narrative 为 None 表示本步被跳过
                if narrative is None:
                    skipped_count = engine.state.consecutive_skipped
                    new_narrative = f"\n\n---\n\n### ⏩ 时间快进（第{step}步，连续快进{skipped_count}步）"
                    return status_text, schedule_text, new_narrative, step_text, clock_text, events_text

                # 追加叙事
                minute = engine.state.current_minute
                new_narrative = f"\n\n---\n\n### 📍 第{day}天 {hour:02d}:{minute:02d}\n\n{narrative}"

                return status_text, schedule_text, new_narrative, step_text, clock_text, events_text
            except Exception as e:
                logger.exception("推进失败")
                return (
                    f"错误: {e}",
                    "",
                    f"\n\n❌ 推进失败: {e}",
                    "",
                    "",
                    "",
                )
            finally:
                _advancing = False

        async def on_auto_advance():
            """自动推进5步"""
            global _advancing
            if _advancing:
                return (
                    gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
                    "⏳ 正在推进中，请稍候...",
                )
            _advancing = True
            try:
                results = []
                skipped_total = 0
                for _ in range(5):
                    try:
                        narrative = await engine.advance_one_step()
                        if narrative is None:
                            skipped_total += 1
                            continue
                        day = engine.state.current_day
                        hour = engine.state.current_hour
                        minute = engine.state.current_minute
                        results.append(f"\n\n---\n\n### 📍 第{day}天 {hour:02d}:{minute:02d}\n\n{narrative}")
                    except Exception as e:
                        results.append(f"\n\n❌ 推进失败: {e}")
                        break

                status_text = _build_char_status()
                schedule_text = _build_schedule_display()
                clock_text = _build_world_clock()
                step = engine.state.current_step
                day = engine.state.current_day
                hour = engine.state.current_hour
                step_text = f"第 {step} 步 | 第 {day} 天 | {hour:02d}:00"
                events_text = _build_events_text()

                full_narrative = ""
                if skipped_total > 0:
                    full_narrative += f"### ⏩ 时间快进（跳过了{skipped_total}步日常流水账）\n\n"
                full_narrative += "\n".join(results)

                return status_text, schedule_text, full_narrative, step_text, clock_text, events_text
            finally:
                _advancing = False

        def on_add_event(event_type_val, event_desc):
            if not event_desc.strip():
                return "⚠️ 请输入事件描述", "", event_desc
            try:
                msg = engine.add_player_event(event_type_val, event_desc.strip())
                events_text = _build_events_text()
                pending_text = _build_pending_events_text()
                feedback = f"**{msg}**" if "⚠️" in msg else f"✅ {msg}"
                # 清空输入框
                return feedback, pending_text, ""
            except Exception as e:
                return f"❌ 添加失败: {e}", "", event_desc

        def on_save():
            try:
                import tempfile
                filepath = config.SAVES_DIR / f"story_{engine.state.current_step}.json"
                config.SAVES_DIR.mkdir(parents=True, exist_ok=True)
                engine.save_story(str(filepath))
                return gr.update(value=str(filepath), visible=True)
            except Exception as e:
                return gr.update(visible=False)

        def on_load(file):
            if file is None:
                return "请选择存档文件", "", "", "", "", ""
            try:
                filepath = file.name if hasattr(file, 'name') else str(file)
                engine.load_story(filepath)
                status_text = _build_char_status()
                schedule_text = _build_schedule_display()
                clock_text = _build_world_clock()

                # 重建叙事
                narratives = []
                for ts in engine.state.timeline:
                    if ts.narrative:
                        narratives.append(ts.narrative)

                full_narrative = f"### 📖 {engine.state.setting.title}\n\n" + "\n\n---\n\n".join(narratives)
                step = engine.state.current_step
                day = engine.state.current_day
                hour = engine.state.current_hour
                step_text = f"第 {step} 步 | 第 {day} 天 | {hour:02d}:00"

                return "✅ 存档加载成功", status_text, schedule_text, full_narrative, step_text, clock_text
            except Exception as e:
                return f"❌ 加载失败: {e}", "", "", "", "", ""

        # ============================================================
        # 辅助函数
        # ============================================================

        def _build_char_status() -> str:
            if engine.state is None:
                return ""
            lines = []
            for cid, state in engine.state.character_states.items():
                c = state.config
                # 获取关键关系
                key_rels = []
                for r in engine.state.relationships:
                    other_id = None
                    if r.character_a == cid:
                        other_id = r.character_b
                    elif r.character_b == cid:
                        other_id = r.character_a
                    if other_id and abs(r.trust - 50) > 10:
                        other_name = engine.state.characters[other_id].name
                        emoji = "❤️" if r.affection > 60 else ("💔" if r.affection < 40 else "🤝")
                        key_rels.append(f"{emoji}{other_name}({r.affection})")
                rel_text = " | ".join(key_rels) if key_rels else "无特殊关系"

                lines.append(
                    f"**{c.name}** ({c.role})\n"
                    f"📍 {state.current_location} | 💭 {state.current_mood} | 🩺 {state.physical_condition}\n"
                    f"🔗 {rel_text}\n"
                )
            return "\n---\n".join(lines)

        def _build_pending_events_text() -> str:
            """构建待生效事件列表文本"""
            if engine.state is None or not engine.state.pending_player_events:
                return ""
            lines = ["**📋 待生效事件：**"]
            for i, e in enumerate(engine.state.pending_player_events, 1):
                etype = "📢 大事件" if e.event_type.value == "plot_event" else "🌦️ 环境"
                lines.append(f"{i}. {etype}: {e.description}")
            return "\n".join(lines)

        def _build_events_text() -> str:
            if engine.state is None:
                return ""
            from engine.world_event import format_event_for_display, get_active_events
            active = get_active_events(
                engine.state.active_world_events, engine.state.current_step
            )
            if not active:
                return ""
            lines = ["### 🌍 当前活跃事件"]
            for e in active:
                source = "🎮 玩家" if e.source.value == "player" else "⚙️ 系统"
                etype = "📢 大事件" if e.event_type.value == "plot_event" else "🌦️ 环境"
                lines.append(f"- {source} {etype}: {e.description}")
                if e.affected_characters:
                    names = [
                        engine.state.characters[cid].name
                        for cid in e.affected_characters
                        if cid in engine.state.characters
                    ]
                    lines.append(f"  - 涉及角色: {'、'.join(names)}")
            return "\n".join(lines)

        def _build_world_clock() -> str:
            """构建世界时钟显示"""
            if engine.state is None:
                return ""
            day = engine.state.current_day
            hour = engine.state.current_hour
            time_label = engine.state.get_time_label()
            imp_threshold = config.NARRATIVE_IMPORTANCE_THRESHOLD
            return f"### 🕐 世界时钟：**{time_label}** | skip阈值：importance<{imp_threshold}"

        def _build_schedule_display() -> str:
            """构建角色日程表显示"""
            if engine.state is None:
                return ""
            lines = []
            for cid, state in engine.state.character_states.items():
                name = state.config.name
                if not state.personal_schedule:
                    lines.append(f"**{name}**：日程为空")
                    continue
                lines.append(f"**{name}**")
                for evt in state.personal_schedule:
                    imp_bar = "🔴" if evt.importance >= 7 else ("🟡" if evt.importance >= 4 else "⚪")
                    src_tag = f"[{evt.source}]" if evt.source != "schedule" else ""
                    time_str = f"{evt.hour:02d}:{evt.minute:02d}"
                    dur_str = f"({evt.duration}min)" if evt.duration != 60 else ""
                    lines.append(f"  - {imp_bar} 第{evt.day}天 {time_str} {dur_str} {evt.description} {src_tag}")
            return "\n".join(lines)

        # ============================================================
        # 绑定事件
        # ============================================================

        init_outputs = [
            game_row, control_row, active_events_display,
            char_status, schedule_display, narrative_box, step_info,
            world_clock_display, active_events_display, init_status,
        ]
        init_btn.click(
            on_init,
            inputs=[setting_title, setting_era, setting_location,
                    setting_desc, setting_tone, setting_start, setting_start_iso, chars_input],
            outputs=init_outputs,
        )

        # 启动区域加载存档
        load_setup_outputs = [
            game_row, control_row, active_events_display,
            char_status, schedule_display, narrative_box, step_info,
            world_clock_display, active_events_display, load_setup_status,
        ]
        load_btn_setup.click(
            on_load_from_setup,
            inputs=[load_file_setup],
            outputs=load_setup_outputs,
        )

        advance_outputs = [char_status, schedule_display, narrative_box, step_info, world_clock_display, active_events_display]
        advance_btn.click(on_advance, outputs=advance_outputs)
        auto_btn.click(on_auto_advance, outputs=advance_outputs)

        add_event_btn.click(
            on_add_event,
            inputs=[event_type, event_input],
            outputs=[event_feedback, pending_events_display, event_input],
        )

        save_btn.click(on_save, outputs=[save_file])
        load_btn.click(
            on_load,
            inputs=[save_file],
            outputs=[init_status, char_status, schedule_display, narrative_box, step_info, world_clock_display],
        )

    return app


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    app = create_ui()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="indigo", secondary_hue="amber"),
    )
