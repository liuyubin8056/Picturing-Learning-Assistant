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
    # 先释放连接再清理产物（否则 SQLite 文件被占用删不掉）
    engine.dispose()
    for p in BACKEND_DIR.glob("test_dev.db*"):
        p.unlink(missing_ok=True)
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
