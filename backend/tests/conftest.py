"""测试公共夹具。

注意：环境变量必须在 import app 之前设置（覆盖 backend/.env），
测试用独立 SQLite 文件库与上传目录，LLM 调用一律 mock，不依赖外网。
"""

import os
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["DATABASE_URL"] = "sqlite:///./test_dev.db"
os.environ["UPLOAD_DIR"] = "./test_uploads"
os.environ["DEEPSEEK_API_KEY"] = ""  # 强制未配置状态

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from app.db import engine
from app.main import app


@pytest.fixture()
def client():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c
    # 先释放连接再清理产物（Windows 上 SQLite 文件锁释放有延迟，删不掉可留到下次，
    # drop_all + create_all 已保证测试间隔离）
    engine.dispose()
    for p in BACKEND_DIR.glob("test_dev.db*"):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    shutil.rmtree(BACKEND_DIR / "test_uploads", ignore_errors=True)


@pytest.fixture()
def mock_llm(monkeypatch):
    """mock DeepSeek 答疑调用，返回带搭车 meta 的固定结果。"""
    from app.llm.deepseek import DeepSeekClient, LLMResult

    async def fake_ask(self, image_bytes: bytes, mime: str = "image/jpeg"):
        assert image_bytes, "图片字节不应为空"
        return LLMResult(
            answer="【测试】第一步：设抛物线方程；第二步：代入顶点坐标。",
            meta={
                "subject": "数学",
                "chapter": "二次函数",
                "kp_tags": ["抛物线性质"],
                "difficulty": 3,
                "suspected_error_type": "概念不清",
                "profile_delta": {
                    "confusion": "平移方向与系数符号",
                    "hint": "先补对称轴",
                },
            },
            raw="{}",
        )

    monkeypatch.setattr(DeepSeekClient, "ask_with_image", fake_ask)

@pytest.fixture(autouse=True)
def auto_login():
    """默认以「演示账号」身份登录。

    账户体系上线后，业务接口都依赖 current_user。原有 33 个用例直接传
    user_id（1/7/11/98/99 等），若逐个改成带 token 调用，改动面大且易错。
    这里统一覆盖成 is_demo=True 并显式打开 allow_demo_cross_access：
    老用例会访问 1/7/11/98/99 等多个 user_id，语义保持不变。
    注意 cross_access 默认是 False（生产默认收窄），
    权限本身（401/403）由 test_auth_guard.py 单独覆盖。
    """
    from app.config import get_settings
    from app.deps import current_user
    from app.models import User

    settings = get_settings()
    prev_cross = settings.allow_demo_cross_access
    settings.allow_demo_cross_access = True
    # 用例之间不抢限流额度（有的用例连续多次调 /questions）
    prev_rl = settings.rate_limit_enabled
    settings.rate_limit_enabled = False

    app.dependency_overrides[current_user] = lambda: User(
        id=1, email="test@example.com", nickname="测试", is_demo=True
    )
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        settings.allow_demo_cross_access = prev_cross
        settings.rate_limit_enabled = prev_rl
