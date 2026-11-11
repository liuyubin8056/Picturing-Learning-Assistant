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
    "users": [
        # 账户体系（邮箱验证码登录）：历史匿名账号这些列为 NULL
        ("email", "TEXT"),
        ("nickname", "TEXT"),
        ("password_hash", "TEXT"),
        ("status", "TEXT DEFAULT 'active'"),
        ("is_demo", "INTEGER DEFAULT 0"),
        ("last_login_at", "DATETIME"),
        ("is_admin", "BOOLEAN DEFAULT 0"),
        ("consent_at", "DATETIME"),
        ("consent_version", "TEXT"),
    ],
    "kb_problems": [
        ("ocr_text", "TEXT"),
        ("review_status", "TEXT NOT NULL DEFAULT 'pending'"),
        ("review_note", "TEXT"),
        ("reviewed_at", "DATETIME"),
        # 题干/解析分离裁剪（练习只展示题干图，解析图判分后才给）
        ("stem_image_path", "TEXT"),
        ("solution_image_path", "TEXT"),
    ],
    "questions": [
        ("feedback_options", "TEXT"),
        ("feedback_result", "TEXT"),
        ("feedback_at", "DATETIME"),
        # 多题照片的逐题讲解（前端详解上方的题号切换按钮）
        ("problems_json", "TEXT"),
    ],
    "test_questions": [
        # 组卷快照也要带分离图，否则练习时只能用含解析的整题图
        ("stem_image_path", "TEXT"),
        ("solution_image_path", "TEXT"),
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

        # users.email 唯一（部分索引：NULL 不参与，可兼容历史匿名账号与演示账号）
        rows = conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        if rows:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email "
                "ON users(email) WHERE email IS NOT NULL"
            )


def get_session():
    """FastAPI 依赖：请求级会话。"""
    with Session(engine) as session:
        yield session
