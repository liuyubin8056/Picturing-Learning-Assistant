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
    error_msg: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    answered_at: datetime | None = None
