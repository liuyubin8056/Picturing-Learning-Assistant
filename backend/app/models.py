"""SQLModel 数据模型。

Question.meta_json 存放答疑调用搭车返回的打标原始输出
（subject / chapter / kp_tags / difficulty / suspected_error_type / profile_delta），
一期只存不用，二期由诊断模块消费（见方案文档第 3.2、11.5 节）。
"""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """统一 UTC。SQLModel 0.0.48+ 的 datetime 列要求 tz-aware 值。"""
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Question(SQLModel, table=True):
    """拍照题目记录。

    client_question_id 由端侧生成（UUID），配合唯一约束实现
    断网续传的服务端幂等去重：重复提交返回已有结果；
    上次 failed 的记录可凭同一 ID 重试（复用已存图片）。
    """

    __tablename__ = "questions"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    client_question_id: str = Field(unique=True, index=True, max_length=64)
    image_path: str  # 存储后端返回的文件名（相对 UPLOAD_DIR）
    status: str = Field(default="pending", index=True)  # pending / answered / failed
    answer: str | None = None  # 答疑正文
    meta_json: str | None = None  # 搭车打标原始 JSON（二期消费）
    # 学生互动反馈：答疑时模型预生成的错因候选 + 用户提交结果
    feedback_options: str | None = None
    feedback_result: str | None = None
    feedback_at: datetime | None = None
    error_msg: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    answered_at: datetime | None = None


class KnowledgePoint(SQLModel, table=True):
    """知识点树（来源：吉米多维奇题集）。

    三级结构：level=1 章 / level=2 节 / level=3 知识点。
    L1/L2 来自 PDF 书签目录，L3 由 LLM 从节标题细分而来。
    """

    __tablename__ = "knowledge_points"

    id: int | None = Field(default=None, primary_key=True)
    level: int = Field(index=True)  # 1=章 2=节 3=知识点
    name: str = Field(index=True)
    parent_id: int | None = Field(default=None, foreign_key="knowledge_points.id", index=True)
    chapter: str | None = Field(default=None, index=True)  # 冗余所属章，便于按章查询
    order_no: int = Field(default=0)  # 章/节在书中的顺序
    start_page: int | None = None  # PDF 物理页起始（1-based）
    end_page: int | None = None  # PDF 物理页结束（1-based）
    desc: str | None = None  # 知识点说明 / 要点
    key_formula: str | None = None  # 核心公式（选填）
    difficulty_hint: int | None = None  # 难度提示 1-3
    source: str | None = None  # 数据来源标记
    created_at: datetime = Field(default_factory=utcnow, index=True)


class KBProblem(SQLModel, table=True):
    """题库题目（来源：吉米多维奇题集，多模态批量提取）。"""

    __tablename__ = "kb_problems"

    id: int | None = Field(default=None, primary_key=True)
    problem_no: str | None = Field(default=None, index=True)  # 书内题号，如 140
    chapter: str | None = Field(default=None, index=True)
    section: str | None = Field(default=None, index=True)  # 所属节（L2 名）
    kp_ids: str | None = None  # 关联知识点 id 列表（JSON 数组）
    question_type: str | None = Field(default=None, index=True)
    # choice 单选 / multiple 多选 / judge 判断 / fill 填空 / solve 解答
    stem: str | None = None  # 题干（文本）
    options: str | None = None  # 选项 JSON：[{"key":"A","text":"..."}]
    answer: str | None = None  # 标准答案
    solution: str | None = None  # 详解（DB 内存储，供展示）
    difficulty: int | None = None  # 1 基础 / 2 中等 / 3 挑战
    error_tags: str | None = None  # 错因标签 JSON 数组
    is_objective: bool = Field(default=False, index=True)  # 是否可自动判分
    feedback_options: str | None = None  # 答疑时模型预生成的错因候选（JSON，含 tag/label/weight）
    feedback_result: str | None = None  # 用户反馈结果（JSON：selected/custom）
    feedback_at: datetime | None = None  # 反馈时间
    source_page: int | None = Field(default=None, index=True)  # PDF 物理页
    book_page: int | None = None  # 书内页码（页脚）
    page_image_path: str | None = None  # 整页图
    crop_image_path: str | None = None  # 题目裁剪图（一题一图）
    extract_status: str = Field(default="ok", index=True)  # ok / low_confidence / failed
    raw_json: str | None = None  # 模型原始输出，便于回溯修正
    ocr_text: str | None = None  # OCR 辅助文本（仅用于定位/匹配，不作为题干来源）
    review_status: str = Field(default="pending", index=True)  # pending 待校对 / ok 准确 / fix 需修正
    review_note: str | None = None  # 校对备注
    reviewed_at: datetime | None = None  # 校对时间
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Mastery(SQLModel, table=True):
    """用户 × 知识点的掌握度（个性化画像的数据底座）。

    信号来源：
    1. 答疑反馈（主信号）：用户自报错因，权重按 err_weights 加权
    2. 自测判分（确定性信号）：客观题直接判分，主观题按用户自评
    3. 答疑行为（弱信号）：仅拍照提问、未反馈也计入一次弱求助

    score 为掌握度 0~1（EMA 更新）；薄弱度由 profile_service 依据
    错误率 / 错因权重 / 时间衰减实时计算，不落库。
    """

    __tablename__ = "mastery"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    kp_id: int = Field(foreign_key="knowledge_points.id", index=True)
    score: float = Field(default=0.0)  # 掌握度 0~1
    ask_count: int = Field(default=0)  # 拍照求助次数
    wrong_count: int = Field(default=0)  # 自测做错次数
    right_count: int = Field(default=0)  # 自测做对次数
    feedback_count: int = Field(default=0)  # 提交反馈的次数
    error_tags: str | None = None  # 错因累计（JSON：{tag: 次数}）
    custom_notes: str | None = None  # 用户自定义反馈原文（JSON 数组，最多保留 10 条）
    last_active_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class ProfileMeta(SQLModel, table=True):
    """画像元信息（md 文件本体存backend/profiles/{user_id}.md）。"""

    __tablename__ = "profile_meta"

    user_id: int = Field(primary_key=True)
    md_path: str | None = None  # md 文件相对路径
    weak_kp_ids: str | None = None  # 薄弱知识点 id（JSON 数组，按薄弱度降序）
    strong_kp_ids: str | None = None  # 优势知识点 id（JSON 数组）
    radar: str | None = None  # 雷达图数据（JSON：按章聚合的平均掌握度）
    signal_count: int = Field(default=0)  # 累计信号数（答疑反馈 + 自测结果）
    updated_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
