"""数据库引擎与会话管理。"""

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()

# SQLite 需禁用 check_same_thread（FastAPI 线程池访问）
_connect_args = (
    {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(_settings.database_url, echo=False, connect_args=_connect_args)


def init_db() -> None:
    """MVP：启动时建表；二期引入 alembic 迁移管理表结构变更。"""
    from . import models  # noqa: F401  确保模型注册到 metadata

    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI 依赖：请求级会话。"""
    with Session(engine) as session:
        yield session
