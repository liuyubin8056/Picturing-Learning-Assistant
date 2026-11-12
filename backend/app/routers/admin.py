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

# TokenUsage.scene 的取值（散落在各业务模块里，这里统一给展示名）
SCENE_LABEL = {
    "qa": "拍照答疑",
    "diagnose": "诊断报告",
    "test_explain": "详解生成",
    "test_judge": "主观题阅卷",
    "test_tutor": "追问辅导",
    "context_probe": "上下文实验",
}


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

    today = usage_counter.today_str()          # 与写入口径一致（北京时间）
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
                # 管理后台展示完整邮箱：脱敏后无法核对是谁，也搜不到。
                # 这个接口本身被 require_admin 挡着，普通用户拿不到。
                "email": u.email,
                "email_masked": auth.mask_email(u.email) if u.email else None,
                "has_email": bool(u.email),
                # 早期未绑定邮箱的空壳账号：昵称和邮箱都没有，界面上不能显示成"用户0"
                "anonymous": not (u.nickname or u.email),
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
    today = usage_counter.today_str()
    TZ = usage_counter.TZ_CN
    # 今天 00:00（北京时间）对应的 UTC 时刻。必须保持 tz-aware：
    # SQLModel 的 datetime 列拒收 naive 值（ValueError: must have timezone information）。
    today_start_utc = datetime.combine(
        datetime.now(TZ).date(), datetime.min.time(), tzinfo=TZ
    ).astimezone(timezone.utc)

    tokens_today = int(
        session.exec(
            select(func.sum(TokenUsage.total_tokens)).where(
                TokenUsage.created_at >= today_start_utc
            )
        ).one()
        or 0
    )
    llm_calls_today = int(
        session.exec(
            select(func.count()).select_from(TokenUsage).where(
                TokenUsage.created_at >= today_start_utc
            )
        ).one()
        or 0
    )
    api_today = int(
        session.exec(select(func.sum(ApiHit.count)).where(ApiHit.day == today)).one() or 0
    )

    return {
        "users": count(User),
        "users_with_email": count(User, User.email.is_not(None)),
        "users_active_7d": count(User, User.last_login_at >= week_ago),
        "users_new_7d": count(User, User.created_at >= week_ago),
        "demo_users": count(User, User.is_demo == True),  # noqa: E712
        "questions": count(Question),
        "questions_answered": count(Question, Question.status == "answered"),
        "test_sessions": count(TestSession),
        "wrong_books": count(WrongBook),
        "mastery_points": count(Mastery),
        "diagnose_reports": count(DiagnosisReport),
        "tokens_total": total_tokens,
        "tokens_today": tokens_today,
        "llm_calls": count(TokenUsage),
        "llm_calls_today": llm_calls_today,
        "api_hits_total": int(
            session.exec(select(func.sum(ApiHit.count))).one() or 0
        ),
        "api_hits_today": api_today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/timeline", summary="按天的 API 调用量与 Token 用量（时间轴）")
def timeline(
    me: User = Depends(require_admin),
    session: Session = Depends(get_session),
    days: int = Query(30, ge=1, le=180, description="往前看多少天（含今天）"),
    user_id: int | None = Query(None, description="只看某个用户；不传则全站"),
):
    """返回连续日期的序列，**缺数据的日子补 0**。

    补 0 很关键：折线图不能因为中间某天没人用就把两点连成一条斜线，
    那样看不出"停了一天"，量级也会被误读。
    """
    usage_counter.flush(session)

    TZ = usage_counter.TZ_CN
    today = datetime.now(TZ).date()
    start = today - timedelta(days=days - 1)
    start_day = start.isoformat()

    # 1) 接口访问：本来就按天存，直接 group by
    stmt = select(ApiHit.day, func.sum(ApiHit.count)).where(ApiHit.day >= start_day)
    if user_id is not None:
        stmt = stmt.where(ApiHit.user_id == user_id)
    api_by_day = {
        d: int(n or 0) for d, n in session.exec(stmt.group_by(ApiHit.day)).all()
    }

    # 2) Token 用量：按 created_at 归到北京时间的那一天
    #    库里的值是 UTC（SQLite 存成无偏移字符串），下界取"北京开始日 0 点"对应的 UTC 时刻
    since_utc = datetime.combine(
        start, datetime.min.time(), tzinfo=TZ
    ).astimezone(timezone.utc)
    tstmt = select(
        TokenUsage.created_at,
        TokenUsage.scene,
        TokenUsage.prompt_tokens,
        TokenUsage.completion_tokens,
        TokenUsage.total_tokens,
    ).where(TokenUsage.created_at >= since_utc)
    if user_id is not None:
        tstmt = tstmt.where(TokenUsage.user_id == user_id)

    llm_by_day: dict[str, dict[str, int]] = {}
    scene_agg: dict[str, dict[str, int]] = {}
    for created, scene, prompt, completion, total in session.exec(tstmt).all():
        dt = created
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        key = dt.astimezone(TZ).strftime("%Y-%m-%d")
        cell = llm_by_day.setdefault(
            key, {"calls": 0, "prompt": 0, "completion": 0, "total": 0}
        )
        cell["calls"] += 1
        cell["prompt"] += int(prompt or 0)
        cell["completion"] += int(completion or 0)
        cell["total"] += int(total or 0)

        sc = scene_agg.setdefault(scene or "other", {"tokens": 0, "calls": 0})
        sc["tokens"] += int(total or 0)
        sc["calls"] += 1

    series = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        cell = llm_by_day.get(d, {"calls": 0, "prompt": 0, "completion": 0, "total": 0})
        series.append(
            {
                "day": d,
                "api_hits": api_by_day.get(d, 0),
                "llm_calls": cell["calls"],
                "tokens_prompt": cell["prompt"],
                "tokens_completion": cell["completion"],
                "tokens_total": cell["total"],
            }
        )

    def total_of(key: str) -> int:
        return sum(row[key] for row in series)

    def peak_of(key: str) -> dict:
        best = max(series, key=lambda r: r[key]) if series else None
        return {"day": best["day"], "value": best[key]} if best else {"day": None, "value": 0}

    total_token_sum = total_of("tokens_total") or 1
    scenes = sorted(
        (
            {
                "scene": k,
                "label": SCENE_LABEL.get(k, k),
                "tokens": v["tokens"],
                "calls": v["calls"],
                "share": round(v["tokens"] / total_token_sum, 4),
            }
            for k, v in scene_agg.items()
        ),
        key=lambda s: s["tokens"],
        reverse=True,
    )

    return {
        "days": days,
        "user_id": user_id,
        "start": start_day,
        "end": today.isoformat(),
        "timezone": "UTC+8",
        "series": series,
        "scenes": scenes,
        "totals": {
            "api_hits": total_of("api_hits"),
            "llm_calls": total_of("llm_calls"),
            "tokens_prompt": total_of("tokens_prompt"),
            "tokens_completion": total_of("tokens_completion"),
            "tokens_total": total_of("tokens_total"),
        },
        "peak": {
            "api_hits": peak_of("api_hits"),
            "tokens_total": peak_of("tokens_total"),
        },
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
