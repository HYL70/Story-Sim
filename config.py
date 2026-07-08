# DeepSeek API 配置
# 将实际的 API Key 填入 .env 文件中（不要直接写在这里）

from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# DeepSeek API
DEEPSEEK_API_KEY = None  # 从 .env 文件读取，见下方 load_env()
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 模型选择
MODEL_FLASH = "deepseek-chat"     # 高速低价，MVP 使用
MODEL_PRO = "deepseek-reasoner"   # 高质量，后续升级使用

# 当前使用模型
ACTIVE_MODEL = MODEL_PRO

# LLM 调用参数
MAX_TOKENS_OUTPUT = 2048
TEMPERATURE = 0.8

# 记忆系统参数
MAX_MEMORIES_PER_CHARACTER = 100
MEMORY_RECENT_WEIGHT = 1.5
REFLECTION_INTERVAL = 3  # 每 N 步触发一次反思
REFLECTION_IMPORTANCE_FLOOR = 7  # 反思记忆固定最低重要性（Stanford 推荐 6.0-8.0）
RECENT_ACTIONS_KEEP = 3  # 角色最近行动记录保留条数

# 时间推进参数（独立事件调度）
DEFAULT_START_HOUR = 8  # 默认一天从8点开始
TIME_WINDOW_MINUTES = 60  # 时间窗口：相近时间点的角色一同激活（0=精确匹配）

# 事件驱动时间推进参数（参考 Stanford Generative Agents 行动与叙事分离）
NARRATIVE_IMPORTANCE_THRESHOLD = 4  # 低于此值的时间步不生成叙事（日常流水账跳过）
MAX_SKIPPED_STEPS = 5              # 连续快进上限，防止无限跳过

# 世界模拟参数（碰撞检测）
ENCOUNTER_EXTREME_THRESHOLD = 70   # 信任度或好感度超过此值视为极端关系 → 对话
ENCOUNTER_PASSING_THRESHOLD = 40    # 信任度和好感度都在此值以下视为无关系 → 擦肩

# 叙事风格参数（由玩家在初始化时设定，存储于 StorySetting.tone）
# NARRATIVE_STYLE 使用说明：
#   - 该值存储在 StorySetting.tone 中，由玩家通过 UI 设定
#   - 各 prompt 模块通过 self.state.setting.tone 读取
#   - 值示例："日式青春校园剧"、"暗流涌动"、"欢乐日常"、"悬疑推理"
#   - prompt 模块根据此值动态调整叙事风格前缀

# 角色弧光大纲（可选，由玩家设定）
# 存储于 StoryState.character_arc_outline（str）
# 如果有值，auto_event 和 character_action 会参考它引导角色发展方向
# 如果为空，则完全由角色自由发展（无主线模式）

# 叙事摘要参数
STORY_SUMMARY_MAX_STEPS = 20  # 用于构建叙事摘要的最大步数（简化后缩小）

# === 标准化地点注册表（Location Registry）===
LOCATIONS_DEFAULT = [
    "教室", "走廊", "图书馆", "食堂", "操场", "体育馆", "社团活动室",
    "屋顶", "校门口", "教师办公室", "保健室", "中庭", "学生宿舍",
    "音乐教室", "美术室", "理科室", "厕所", "其他室内", "其他户外",
]
# 反思最小间隔（至少间隔 N 个叙事步才能再次触发）
REFLECTION_MIN_NARRATIVE_INTERVAL = 2
# 防倒退最小时间偏移（如果 LLM 输出的 next_event 早于当前时间，强制加上此偏移）
ANTI_REVERSE_MIN_MINUTES = 5

# 数据目录
DATA_DIR = PROJECT_ROOT / "data"
SAVES_DIR = DATA_DIR / "saves"
TEMPLATES_DIR = DATA_DIR / "templates"


def load_env():
    """从 .env 文件加载配置"""
    global DEEPSEEK_API_KEY
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key == "DEEPSEEK_API_KEY" and value:
                    DEEPSEEK_API_KEY = value


# 模块加载时自动读取 .env
load_env()
