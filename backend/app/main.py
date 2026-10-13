"""FastAPI 入口。"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import health, kb, profile, questions
from .storage import get_storage

BASE_DIR = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="智能拍照学习助手 API",
    version="0.2.0",
    description="拍照 → 多模态大模型识图答疑（一期）+ 知识库查询与人工校对",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(questions.router)
app.include_router(kb.router)
app.include_router(profile.router)

# 题目图片静态服务（MVP 本地存储；get_storage 构造时确保目录存在）
_storage = get_storage()
app.mount("/uploads", StaticFiles(directory=str(_storage.base)), name="uploads")

_kb_images = BASE_DIR / "kb_images"
# 题目裁剪图与整页图（知识库）
for _name, _dir in (("kb_images", _kb_images), ("_kb_out", BASE_DIR / "_kb_out")):
    if _dir.exists():
        app.mount(f"/{_name}", StaticFiles(directory=str(_dir)), name=_name)


@app.get("/", summary="服务信息")
def root():
    return {
        "service": "智能拍照学习助手 API",
        "docs": "/docs",
        "health": "/api/v1/health",
        "kb_review": "/review",
    }


@app.get("/review", include_in_schema=False)
def review_page():
    """人工校对页。"""
    f = BASE_DIR / "static" / "review.html"
    if not f.exists():
        return {"message": "校对页未构建"}
    return FileResponse(str(f))
