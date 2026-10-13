"""数据库引擎与会话管理。"""

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()

# SQLite 需禁用 check_same_thread（FastAPI 线程池访问）
_connect_args = {"check_same_thread": False} if _settings.db_url.startswith("sqlite") else {}

engine = create_engine(_settings.db_url, echo=False, connect_args=_connect_args)


def init_db() -> None:
    """MVP：启动时建表 + 轻量补列；表结构复杂后引入 alembic 迁移。"""
    from . import models  # noqa: F401  确保模型注册到 metadata

    SQLModel.metadata.create_all(engine)
    _light_migrate()


# 开发期轻量迁移：create_all 不会给已存在的表补列，这里显式 ALTER 补齐
_LIGHT_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "kb_problems": [
        ("ocr_text", "TEXT"),
        ("review_status", "TEXT NOT NULL DEFAULT 'pending'"),
        ("review_note", "TEXT"),
        ("reviewed_at", "DATETIME"),
    ],
}


def _light_migrate() -> None:
    from sqlalchemy import text as _t

    with engine.begin() as conn:
        for table, cols in _LIGHT_MIGRATIONS.items():
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            if not rows:  # 表不存在，交给 create_all
                continue
            existing = {r[1] for r in rows}
            for name, ddl in cols:
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                    print(f"[migrate] {table}.{name} 已添加")


def get_session():
    """FastAPI 依赖：请求级会话。"""
    with Session(engine) as session:
        yield session
