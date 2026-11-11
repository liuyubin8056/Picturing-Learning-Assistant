"""FastAPI 入口。"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .middleware import RateLimitMiddleware, RequestContextMiddleware
from .routers import (
    admin,
    diagnose,
    health,
    kb,
    profile,
    questions,
    tests,
    tokens,
    uploads,
)
from .routers import auth as auth_router
from .storage import get_storage

BASE_DIR = Path(__file__).resolve().parents[1]


def _setup_logging() -> None:
    """让 learnmate.* 的日志进到 uvicorn 的 stdout（生产由 journald / docker 收）。

    uvicorn 自己会配 root handler，所以只在没有 handler 时才 basicConfig，
    避免把 uvicorn 的访问日志格式覆盖掉。
    """
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    logging.getLogger("learnmate").setLevel(level)


_setup_logging()


@asynccontextmanager
def _sync_admins() -> None:
    """按 ADMIN_EMAILS 给账号打管理员标记（改 .env 重启即生效）。"""
    from sqlmodel import Session, select

    from .db import engine
    from .models import User
    from .services import auth_service as auth

    raw = (get_settings().admin_emails or "").strip()
    emails = [auth.normalize_email(e) for e in raw.split(",") if e.strip()]
    if not emails:
        return
    with Session(engine) as s:
        for email in emails:
            u = auth.get_user_by_email(s, email)
            if u and not u.is_admin:
                u.is_admin = True
                s.add(u)
                print(f"[admin] 已授予管理员：{email}")
        s.commit()


async def _usage_flusher() -> None:
    """每 60 秒把访问计数落库；进程退出时再冲一次，避免丢最后一段。"""
    import asyncio

    from sqlmodel import Session

    from .db import engine
    from .services import usage_counter

    try:
        while True:
            await asyncio.sleep(60)
            try:
                with Session(engine) as s:
                    usage_counter.flush(s)
            except Exception as e:      # 计数失败不能影响服务
                print(f"[usage] flush failed: {e}")
    except asyncio.CancelledError:
        with Session(engine) as s:
            usage_counter.flush(s)
        raise


async def lifespan(app: FastAPI):
    import asyncio

    init_db()
    _sync_admins()
    task = asyncio.create_task(_usage_flusher())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="智能拍照学习助手 API",
    version="0.2.0",
    description="拍照 → 多模态大模型识图答疑（一期）+ 知识库查询与人工校对",
    lifespan=lifespan,
)

# 中间件：add_middleware 后加的先执行 → 请求上下文包在限流外层，
# 这样限流返回的 429 也会带 X-Request-ID，日志能对上。
app.add_middleware(RateLimitMiddleware, enabled=True)
app.add_middleware(RequestContextMiddleware)

# CORS：给 Android/iOS 壳用。
# 壳里的页面源是 https://localhost（Capacitor androidScheme），调远程 API 属跨域。
# 壳走 Authorization: Bearer（不依赖 Cookie），所以不需要 allow_credentials，
# 因此可以放开 *；Web 端同源访问本来就不经过 CORS。
# 必须最后注册：add_middleware 后加的先执行，预检要在限流之前被处理。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
    max_age=600,
)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    """把 FastAPI 默认的 [{loc:[...],msg:...}] 压成一句人话。

    默认格式前端只能 JSON.stringify 出来给用户看，太糟。
    """
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(
        str(x) for x in first.get("loc", []) if x not in ("body", "query", "path")
    )
    msg = first.get("msg", "参数不合法")
    return JSONResponse(
        status_code=422,
        content={
            "detail": f"{loc}: {msg}" if loc else msg,
            "request_id": getattr(request.state, "request_id", ""),
        },
    )

app.include_router(health.router)
app.include_router(questions.router)
app.include_router(kb.router)
app.include_router(profile.router)
app.include_router(diagnose.router)   # D 诊断报告
app.include_router(tests.router)       # E 自测练习
app.include_router(tests.wb_router)   # F 错题本
app.include_router(tokens.router)     # token 计量
app.include_router(auth_router.router)  # 账户（邮箱验证码登录）
app.include_router(uploads.router)      # 分片上传（断点续传）
app.include_router(admin.router)        # 管理后台（仅管理员）

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
