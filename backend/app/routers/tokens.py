"""Token 计量接口（优化验证手段）。"""

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from ..db import get_session
from ..models import TokenUsage
from ..services import token_service as ts

router = APIRouter(prefix="/api/v1/tokens", tags=["Token 计量"])


@router.get("/summary", summary="按场景汇总 token 与缓存命中率")
def summary(
    user_id: int | None = None,
    session: Session = Depends(get_session),
):
    stmt = select(TokenUsage)
    if user_id is not None:
        stmt = stmt.where(TokenUsage.user_id == user_id)
    rows = session.exec(stmt).all()
    out = ts.aggregate(rows)
    out["avg_per_call"] = round(out["total_tokens"] / max(out["total_calls"], 1))
    return out


@router.get("/recent", summary="最近的调用记录")
def recent(
    user_id: int | None = None,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    stmt = select(TokenUsage)
    if user_id is not None:
        stmt = stmt.where(TokenUsage.user_id == user_id)
    rows = session.exec(stmt.order_by(TokenUsage.created_at.desc()).limit(limit)).all()
    return [
        {
            "scene": r.scene,
            "model": r.model,
            "prompt": r.prompt_tokens,
            "completion": r.completion_tokens,
            "reasoning": r.reasoning_tokens,
            "cache_hit": r.cache_hit_tokens,
            "latency_ms": r.latency_ms,
            "created_at": r.created_at,
        }
        for r in rows
    ]