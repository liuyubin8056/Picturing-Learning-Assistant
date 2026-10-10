"""FastAPI 入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import health, questions
from .storage import get_storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="智能拍照学习助手 API",
    version="0.1.0",
    description="拍照 → 多模态大模型识图答疑（一期 MVP：同步答疑 + 幂等去重）",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(questions.router)

# 题目图片静态服务（MVP 本地存储；get_storage 构造时确保目录存在）
_storage = get_storage()
app.mount("/uploads", StaticFiles(directory=str(_storage.base)), name="uploads")


@app.get("/", summary="服务信息")
def root():
    return {"service": "智能拍照学习助手 API", "docs": "/docs", "health": "/api/v1/health"}
