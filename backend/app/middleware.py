"""HTTP 中间件：请求上下文（ID / 耗时 / 异常兜底）与烧钱接口限流。

注册顺序（`add_middleware` 后加的先执行）：
    RequestContextMiddleware（外层） → RateLimitMiddleware（内层） → 路由
这样限流返回的 429 也会带上 X-Request-ID，日志能对上。
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import get_settings

logger = logging.getLogger("learnmate.access")

# 静态资源不必逐条记访问日志，否则一次页面加载刷十几行
_QUIET_PREFIX = ("/assets", "/kb_images", "/uploads")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """给每个请求分配 ID、记录耗时、兜住未捕获异常。

    兜底的价值：未捕获异常默认只会在 uvicorn 打一整段 traceback，前端拿到的是
    干巴巴的 "Internal Server Error"，出问题时两边对不上。这里统一返回
    {"detail", "request_id"}，日志里用同一个 ID，用户报错时报 ID 就能定位。
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            cost = (time.perf_counter() - started) * 1000
            logger.exception(
                "未处理异常 rid=%s %s %s %.0fms",
                rid, request.method, request.url.path, cost,
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "服务内部错误，请稍后重试", "request_id": rid},
                headers={"X-Request-ID": rid},
            )

        cost = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = rid

        fmt = "%s %s %s %.0fms rid=%s"
        args = (request.method, request.url.path, response.status_code, cost, rid)
        if cost >= 3000:
            logger.warning("慢请求 " + fmt, *args)
        elif not request.url.path.startswith(_QUIET_PREFIX):
            logger.info(fmt, *args)
        return response


# ---------------------------------------------------------------
# 限流：只拦"点一下就是一次真实大模型调用"的接口。
# 额度按单 IP 计，短窗防连点、长窗防慢速刷。
# ---------------------------------------------------------------
_RULES: list[tuple[re.Pattern[str], str, tuple[tuple[int, int], ...]]] = [
    # 拍照答疑：最贵（一次 5k~12k token）
    (re.compile(r"^/api/v1/questions$"), "POST", ((6, 60), (30, 3600))),
    # 诊断报告（LLM 版）
    (re.compile(r"^/api/v1/diagnose/users/\d+$"), "POST", ((2, 60), (10, 3600))),
    # 题目详解按需生成
    (re.compile(r"^/api/v1/tests/questions/\d+/detailed-solution$"), "POST",
     ((10, 60), (60, 3600))),
    # 主观题拍照阅卷
    (re.compile(r"^/api/v1/tests/questions/\d+/judge-image$"), "POST",
     ((6, 60), (30, 3600))),
    # 看不懂换个讲法
    (re.compile(r"^/api/v1/tests/questions/\d+/explain$"), "POST",
     ((10, 60), (60, 3600))),
]

# 兜底：任何接口每 IP 每分钟 300 次，挡脚本扫接口
_GLOBAL_LIMIT = (300, 60)

# 这些路径不计入全局限流：一次页面加载会并发十几个静态资源，
# 计数会把正常用户误判成攻击；健康检查也可能被监控高频调用。
_SKIP_PREFIX = ("/assets", "/kb_images", "/uploads", "/docs", "/redoc", "/openapi.json")
_SKIP_EXACT = {"/", "/review", "/api/v1/health"}


def _client_ip(request: Request) -> str:
    """取真实客户端 IP。

    部署后请求都来自 Nginx，`request.client.host` 会是容器/本机地址，
    必须读 Nginx 写的 X-Real-IP；直连（开发环境）时回落到 client.host。
    注意不用 X-Forwarded-For：那是列表且可被客户端伪造，X-Real-IP 由
    Nginx 用 $remote_addr 覆盖写入，更可信。
    """
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _match_rule(method: str, path: str):
    for pattern, m, limits in _RULES:
        if method == m and pattern.match(path):
            return limits
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """内存滑动窗口限流。

    单进程内存计数，够用也够简单：uvicorn 是单 worker（SQLite 的并发写本就不适合
    多进程），Docker 里也是单容器。将来上多实例再换 Redis。
    """

    def __init__(self, app, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_gc = time.time()

    async def dispatch(self, request: Request, call_next):
        # 运行期读配置：测试/本地调试可以随时关掉，不必重建中间件
        if not self.enabled or not get_settings().rate_limit_enabled:
            return await call_next(request)

        ip = _client_ip(request)
        now = time.time()
        self._gc(now)

        path = request.url.path
        # 静态资源与健康检查不参与限流（页面一次加载十几个资源，会被误判）
        if path in _SKIP_EXACT or path.startswith(_SKIP_PREFIX):
            return await call_next(request)

        # CORS 预检（OPTIONS）不计入限流：一次页面/接口调用可能伴随多条预检
        if request.method == "OPTIONS":
            return await call_next(request)

        limits = _match_rule(request.method, path)
        if limits:
            for limit, window in limits:
                wait = self._blocked(f"{ip}|{path}|{window}", now, limit, window)
                if wait:
                    return self._too_many(request, window, wait)

        wait = self._blocked(f"{ip}|*|{_GLOBAL_LIMIT[1]}", now, *_GLOBAL_LIMIT)
        if wait:
            return self._too_many(request, _GLOBAL_LIMIT[1], wait)

        return await call_next(request)

    # ---------- 内部 ----------
    def _blocked(self, key: str, now: float, limit: int, window: int) -> int:
        """超限返回建议等待秒数，未超限返回 0。"""
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return max(1, int(window - (now - q[0])) + 1)
        q.append(now)
        return 0

    def _too_many(self, request: Request, window: int, wait: int) -> JSONResponse:
        rid = getattr(request.state, "request_id", "")
        logger.warning("限流 rid=%s ip=%s %s %s 等待 %ss",
                       rid, _client_ip(request), request.method, request.url.path, wait)
        return JSONResponse(
            status_code=429,
            content={
                "detail": f"操作太频繁，请 {wait} 秒后再试（每分钟 {window} 秒窗口内有次数上限）",
                "request_id": rid,
                "retry_after": wait,
            },
            headers={"Retry-After": str(wait)},
        )

    def _gc(self, now: float) -> None:
        """每分钟清一次空队列，避免长跑后内存只增不减。"""
        if now - self._last_gc < 60:
            return
        self._last_gc = now
        stale = [k for k, q in self._hits.items() if not q]
        for k in stale:
            self._hits.pop(k, None)
