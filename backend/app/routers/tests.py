"""E 模块接口：自测组卷、提交判分、按需详解；F 模块接口：错题本。"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_session
from ..llm.deepseek import DeepSeekClient, LLMCallError, LLMNotConfiguredError
from ..models import TestQuestion, TestSession
from ..services import test_service as tes
from ..services import wrongbook_service as wbs
from ..services.token_service import record_usage

router = APIRouter(prefix="/api/v1/tests", tags=["自测练习"])
wb_router = APIRouter(prefix="/api/v1/wrongbook", tags=["错题本"])


class AnswerItem(BaseModel):
    question_id: int
    answer: str | None = None  # 客观题作答
    self_correct: bool | None = None  # 主观题自评：做对/做错


class SubmitIn(BaseModel):
    answers: list[AnswerItem] = Field(default_factory=list)


def _session_or_404(session: Session, sid: int) -> TestSession:
    ts = session.get(TestSession, sid)
    if ts is None:
        raise HTTPException(status_code=404, detail="自测会话不存在")
    return ts


def _q_to_dict(session: Session, tq: TestQuestion, with_answer: bool = False) -> dict:
    kps = []
    if tq.kp_ids:
        from ..models import KnowledgePoint

        ids = json.loads(tq.kp_ids)
        if ids:
            kps = [k.name for k in session.exec(
                select(KnowledgePoint).where(KnowledgePoint.id.in_(ids))
            ).all()]
    return {
        "id": tq.id,
        "order_no": tq.order_no,
        "stem": tq.stem,
        "options": json.loads(tq.options) if tq.options else None,
        "image_path": tq.image_path,
        "question_type": tq.question_type,
        "is_objective": tq.is_objective,
        "difficulty": tq.difficulty,
        "kp_names": kps,
        # 主观题不做客观题那样提前给答案
        "self_review": not tq.is_objective,
        "your_answer": tq.user_answer,
        "is_correct": tq.is_correct,
        "correct_answer": tq.answer if (with_answer or tq.is_correct is not None) else None,
        "solution": tq.solution if (with_answer or tq.is_correct is not None) else None,
    }


@router.post("/users/{user_id}/sessions", summary="按薄弱点组卷")
def create_session(
    user_id: int,
    purpose: str = Query("weakness", pattern="^(weakness|review|chapter)$"),
    count: int = Query(6, ge=1, le=20),
    chapter: str | None = None,
    session: Session = Depends(get_session),
):
    ts = tes.build_session(session, user_id, purpose=purpose, count=count, chapter=chapter)
    qs = session.exec(
        select(TestQuestion)
        .where(TestQuestion.session_id == ts.id)
        .order_by(TestQuestion.order_no)
    ).all()
    return {
        "id": ts.id,
        "title": ts.title,
        "purpose": ts.purpose,
        "kp_ids": json.loads(ts.kp_ids or "[]"),
        "total": len(qs),
        "questions": [_q_to_dict(session, q) for q in qs],
    }


@router.get("/sessions/{sid}", summary="查看会话与作答状态")
def session_detail(sid: int, session: Session = Depends(get_session)):
    ts = _session_or_404(session, sid)
    qs = session.exec(
        select(TestQuestion)
        .where(TestQuestion.session_id == ts.id)
        .order_by(TestQuestion.order_no)
    ).all()
    return {
        "id": ts.id,
        "title": ts.title,
        "status": ts.status,
        "score": ts.score,
        "right": ts.right_count,
        "wrong": ts.wrong_count,
        "questions": [
            _q_to_dict(session, q, with_answer=ts.status == "submitted") for q in qs
        ],
    }


@router.post("/sessions/{sid}/submit", summary="提交作答：判分 + 回流画像 + 错题入库")
def submit(sid: int, body: SubmitIn, session: Session = Depends(get_session)):
    ts = _session_or_404(session, sid)
    if ts.status == "submitted":
        raise HTTPException(status_code=409, detail="该会话已提交")
    answers = {a.question_id: {"answer": a.answer, "self_correct": a.self_correct} for a in body.answers}
    return tes.submit_session(session, ts, answers)


@router.post("/questions/{qid}/detailed-solution", summary="按需生成详细解析（上传大模型）")
async def detailed(qid: int, session: Session = Depends(get_session)):
    tq = session.get(TestQuestion, qid)
    if tq is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    try:
        out = await tes.detailed_solution(
            session, tq, DeepSeekClient(get_settings())
        )
    except LLMNotConfiguredError:
        raise HTTPException(status_code=503, detail="DEEPSEEK_API_KEY 未配置")
    except LLMCallError as e:
        raise HTTPException(status_code=502, detail=str(e))

    usage = out.pop("usage", {}) or {}
    record_usage(
        session,
        user_id=None,
        scene="test_explain",
        model=get_settings().deepseek_model,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        reasoning_tokens=usage.get("reasoning_tokens", 0),
        cache_hit_tokens=usage.get("cache_hit_tokens", 0),
        cache_miss_tokens=usage.get("cache_miss_tokens", 0),
    )
    session.commit()
    return out


@router.get("/users/{user_id}/sessions", summary="自测历史")
def list_sessions(user_id: int, limit: int = Query(10, ge=1, le=50), session: Session = Depends(get_session)):
    rows = session.exec(
        select(TestSession)
        .where(TestSession.user_id == user_id)
        .order_by(TestSession.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": s.id,
            "title": s.title,
            "purpose": s.purpose,
            "status": s.status,
            "score": s.score,
            "right": s.right_count,
            "wrong": s.wrong_count,
            "created_at": s.created_at,
        }
        for s in rows
    ]


# ---------------- F 错题本 ----------------


@wb_router.get("/users/{user_id}", summary="错题列表（可筛选）")
def list_wrong(
    user_id: int,
    status: str | None = Query(None, pattern="^(pending|mastered)$"),
    kp_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    items = wbs.list_wrong(session, user_id, status=status, kp_id=kp_id, limit=limit, offset=offset)
    return {"stats": wbs.stats(session, user_id), "items": items}


@wb_router.put("/users/{user_id}/{wrong_id}/mastered", summary="标记已掌握/重新加入")
def mark_mastered(
    user_id: int,
    wrong_id: int,
    mastered: bool = Query(True),
    session: Session = Depends(get_session),
):
    w = wbs.mark_mastered(session, user_id, wrong_id, mastered)
    if w is None:
        raise HTTPException(status_code=404, detail="错题不存在")
    return {"id": w.id, "status": w.status, "mastered_at": w.mastered_at}