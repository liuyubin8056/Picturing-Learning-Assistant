"""API 出参 DTO。"""

from datetime import datetime

from pydantic import BaseModel


class QuestionOut(BaseModel):
    id: int
    user_id: int
    client_question_id: str
    image_url: str
    status: str  # pending / answered / failed
    answer: str | None = None
    meta: dict | None = None  # 搭车打标结果（answer 之外的结构化输出）
    # 学生互动反馈：答疑时模型预生成的错因候选（多选 + 前端自定义）
    problems: list | None = None  # 多题照片：逐题讲解（>1 项时前端显示切换按钮）
    feedback_options: list | None = None
    feedback_done: bool = False  # 用户是否已提交过反馈
    error_msg: str | None = None
    duplicated: bool = False  # True = 幂等命中，返回的是已有记录
    created_at: datetime
    answered_at: datetime | None = None
