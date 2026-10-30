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


# ============================================================
# 账户（邮箱验证码登录）
# ============================================================


class UserOut(BaseModel):
    id: int
    email: str | None = None
    email_masked: str | None = None
    nickname: str | None = None
    is_demo: bool = False
    created_at: datetime


class SendCodeIn(BaseModel):
    email: str
    purpose: str = "login"          # login / reset / bind


class SendCodeOut(BaseModel):
    sent: bool
    cooldown: int
    hint: str
    # 仅 MAIL_PROVIDER=console（本地开发）时回显，便于不联网联调
    debug_code: str | None = None


class CodeLoginIn(BaseModel):
    email: str
    code: str


class PasswordLoginIn(BaseModel):
    email: str
    password: str


class SetPasswordIn(BaseModel):
    password: str


class SetNicknameIn(BaseModel):
    nickname: str


class LoginOut(BaseModel):
    user: UserOut
    token: str | None = None        # 仅 App 端（X-Client: app）返回；Web 走 httpOnly Cookie
    expires_in: int | None = None
    is_new: bool = False            # 首次登录自动注册
