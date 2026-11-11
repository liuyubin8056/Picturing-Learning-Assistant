"""管理后台接口（仅管理员）。

用途：看"谁在用、用了多少"。数据全部来自现有表，不额外埋点，
唯一新增的是 api_hits（登录用户每请求一次 +1，内存累加到点落库）。
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, func, select

from ..db import get_session
from ..deps import require_admin
from ..models import (
    ApiHit,
    DiagnosisReport,
    Mastery,
    Question,
    TestQuestion,
    TestSession,
    TokenUsage,
    User,
    WrongBook,
)
from ..services import auth_service as auth
from ..services import export_service, usage_counter

router = APIRouter(prefix="/api/v1/admin", tags=["管理后台"])


def _sum_by_user(session: Session, column, model) -> dict[int, int]:
    rows = session.exec(select(model.user_id, func.count()).group_by(model.user_id)).all()
    return {(uid or 0): int(n or 0) for uid, n in rows}


@router.get("/users", summary="所有用户的关键统计")
def list_users(
    me: User = Depends(require_admin),
    session: Session = Depends(get_session),
    limit: int = Query(500, ge=1, le=2000),
):
    usage_counter.flush(session)          # 先把内存计数落库，保证数字是最新的

    users = session.exec(select(User).order_by(User.created_at)).all()
    users = users[:limit]

    q_total = _sum_by_user(session, Question.user_id, Question)
    q_answered = {
        (uid or 0): int(n or 0)
        for uid, n in session.exec(
            select(Question.user_id, func.count())
            .where(Question.status == "answered")
            .group_by(Question.user_id)
        ).all()
    }
    wrong_total = _sum_by_user(session, WrongBook.user_id, WrongBook)
    mastery_total = _sum_by_user(session, Mastery.user_id, Mastery)
    report_total = _sum_by_user(session, DiagnosisReport.user_id, DiagnosisReport)

    # 答题量：练习会话里的题（TestQuestion 没有 user_id，按会话归属回连）
    answered_rows = session.exec(
        select(TestSession.user_id, func.count(TestQuestion.id))
        .join(TestQuestion, TestQuestion.session_id == TestSession.id)
        .where(TestQuestion.answered_at.is_not(None))
        .group_by(TestSession.user_id)
    ).all()
    tq_answered = {(uid or 0): int(n or 0) for uid, n in answered_rows}

    session_total = _sum_by_user(session, TestSession.user_id, TestSession)

    # token 用量与调用次数
    token_rows = session.exec(
        select(
            TokenUsage.user_id,
            func.sum(TokenUsage.total_tokens),
            func.sum(TokenUsage.prompt_tokens),
            func.sum(TokenUsage.completion_tokens),
            func.count(),
        ).group_by(TokenUsage.user_id)
    ).all()
    tokens = {
        (uid or 0): {
            "total": int(t or 0),
            "prompt": int(p or 0),
            "completion": int(c or 0),
            "calls": int(n or 0),
        }
        for uid, t, p, c, n in token_rows
    }

    api_rows = session.exec(
        select(ApiHit.user_id, func.sum(ApiHit.count)).group_by(ApiHit.user_id)
    ).all()
    api_hits = {(uid or 0): int(n or 0) for uid, n in api_rows}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_rows = session.exec(
        select(ApiHit.user_id, ApiHit.count).where(ApiHit.day == today)
    ).all()
    today_hits = {(uid or 0): int(n or 0) for uid, n in today_rows}

    out = []
    for u in users:
        uid = u.id
        t = tokens.get(uid, {"total": 0, "prompt": 0, "completion": 0, "calls": 0})
        out.append(
            {
                "id": uid,
                "nickname": u.nickname or f"用户{uid}",
                "email": auth.mask_email(u.email) if u.email else None,
                "has_email": bool(u.email),
                "is_demo": bool(u.is_demo),
                "is_admin": bool(u.is_admin),
                "status": u.status,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                "questions": q_total.get(uid, 0),
                "questions_answered": q_answered.get(uid, 0),
                "test_sessions": session_total.get(uid, 0),
                "test_answered": tq_answered.get(uid, 0),
                "wrong_books": wrong_total.get(uid, 0),
                "mastery_points": mastery_total.get(uid, 0),
                "diagnose_reports": report_total.get(uid, 0),
                "api_hits": api_hits.get(uid, 0),
                "api_hits_today": today_hits.get(uid, 0),
                "llm_calls": t["calls"],
                "tokens_total": t["total"],
                "tokens_prompt": t["prompt"],
                "tokens_completion": t["completion"],
            }
        )
    return {"users": out, "count": len(out)}


@router.get("/overview", summary="全局概览")
def overview(
    me: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    usage_counter.flush(session)

    def count(model, where=None):
        stmt = select(func.count()).select_from(model)
        if where is not None:
            stmt = stmt.where(where)
        return int(session.exec(stmt).one() or 0)

    total_tokens = int(
        session.exec(select(func.sum(TokenUsage.total_tokens))).one() or 0
    )
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    return {
        "users": count(User),
        "users_with_email": count(User, User.email.is_not(None)),
        "users_active_7d": count(User, User.last_login_at >= week_ago),
        "demo_users": count(User, User.is_demo == True),  # noqa: E712
        "questions": count(Question),
        "questions_answered": count(Question, Question.status == "answered"),
        "test_sessions": count(TestSession),
        "wrong_books": count(WrongBook),
        "mastery_points": count(Mastery),
        "diagnose_reports": count(DiagnosisReport),
        "tokens_total": total_tokens,
        "llm_calls": count(TokenUsage),
        "api_hits_total": int(
            session.exec(select(func.sum(ApiHit.count))).one() or 0
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/export-all", summary="导出全部用户数据（备份用）")
def export_all(
    me: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """整站备份：每个用户一份，含学习数据（不含凭证）。"""
    users = session.exec(select(User)).all()
    data = {
        "schema_version": export_service.SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "users": [
            {"user": u.email or u.nickname or u.id, "data": export_service.export_user_data(session, u)}
            for u in users
        ],
    }
    return data
