"""知识库查询接口：题目列表/详情、知识点树、统计、人工校对回写。"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from ..db import get_session
from ..models import KBProblem, KnowledgePoint, utcnow

router = APIRouter(prefix="/api/v1/kb", tags=["知识库"])


class ProblemOut(BaseModel):
    id: int
    problem_no: str | None
    chapter: str | None
    section: str | None
    question_type: str | None
    stem: str | None
    options: list | None
    answer: str | None
    solution: str | None
    difficulty: int | None
    error_tags: list | None
    kp_ids: list | None
    kp_names: list | None
    is_objective: bool
    source_page: int | None
    book_page: int | None
    crop_image_path: str | None
    page_image_path: str | None
    extract_status: str
    review_status: str
    review_note: str | None
    ocr_text: str | None


class PageOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ProblemOut]


class ReviewIn(BaseModel):
    review_status: str  # ok / fix / pending
    review_note: str | None = None


def _to_out(p: KBProblem, kp_names: dict[int, str]) -> ProblemOut:
    ids = json.loads(p.kp_ids) if p.kp_ids else []
    return ProblemOut(
        id=p.id,
        problem_no=p.problem_no,
        chapter=p.chapter,
        section=p.section,
        question_type=p.question_type,
        stem=p.stem,
        options=json.loads(p.options) if p.options else None,
        answer=p.answer,
        solution=p.solution,
        difficulty=p.difficulty,
        error_tags=json.loads(p.error_tags) if p.error_tags else None,
        kp_ids=ids or None,
        kp_names=[kp_names[i] for i in ids if i in kp_names] or None,
        is_objective=p.is_objective,
        source_page=p.source_page,
        book_page=p.book_page,
        crop_image_path=p.crop_image_path,
        page_image_path=p.page_image_path,
        extract_status=p.extract_status,
        review_status=p.review_status,
        review_note=p.review_note,
        ocr_text=p.ocr_text,
    )


@router.get("/problems", response_model=PageOut, summary="题目列表（分页筛选）")
def list_problems(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    chapter: str | None = None,
    section: str | None = None,
    question_type: str | None = None,
    review_status: str | None = None,
    source_page: int | None = None,
    keyword: str | None = None,
    session: Session = Depends(get_session),
):
    stmt = select(KBProblem)
    if chapter:
        stmt = stmt.where(KBProblem.chapter.contains(chapter))
    if section:
        stmt = stmt.where(KBProblem.section == section)
    if question_type:
        stmt = stmt.where(KBProblem.question_type == question_type)
    if review_status:
        stmt = stmt.where(KBProblem.review_status == review_status)
    if source_page:
        stmt = stmt.where(KBProblem.source_page == source_page)
    if keyword:
        stmt = stmt.where(KBProblem.stem.contains(keyword))

    total = session.exec(
        select(func.count()).select_from(stmt.subquery())
    ).one()
    rows = session.exec(
        stmt.order_by(KBProblem.source_page, KBProblem.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    kp_names = {
        r.id: r.name for r in session.exec(select(KnowledgePoint)).all() if r.level == 3
    }
    return PageOut(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_out(r, kp_names) for r in rows],
    )


@router.get("/problems/{problem_id}", response_model=ProblemOut, summary="题目详情")
def get_problem(problem_id: int, session: Session = Depends(get_session)):
    p = session.get(KBProblem, problem_id)
    if p is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    kp_names = {
        r.id: r.name for r in session.exec(select(KnowledgePoint)).all() if r.level == 3
    }
    return _to_out(p, kp_names)


@router.put("/problems/{problem_id}/review", summary="回写人工校对结果")
def review_problem(
    problem_id: int, body: ReviewIn, session: Session = Depends(get_session)
):
    if body.review_status not in ("ok", "fix", "pending"):
        raise HTTPException(status_code=422, detail="review_status 仅支持 ok / fix / pending")
    p = session.get(KBProblem, problem_id)
    if p is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    p.review_status = body.review_status
    p.review_note = body.review_note
    p.reviewed_at = utcnow()
    session.add(p)
    session.commit()
    return {"id": p.id, "review_status": p.review_status, "reviewed_at": p.reviewed_at}


@router.get("/knowledge-points", summary="知识点树")
def list_kps(
    level: int | None = Query(None, ge=1, le=3),
    chapter: str | None = None,
    parent_id: int | None = None,
    session: Session = Depends(get_session),
):
    stmt = select(KnowledgePoint).order_by(KnowledgePoint.level, KnowledgePoint.order_no)
    if level:
        stmt = stmt.where(KnowledgePoint.level == level)
    if chapter:
        stmt = stmt.where(KnowledgePoint.chapter.contains(chapter))
    if parent_id:
        stmt = stmt.where(KnowledgePoint.parent_id == parent_id)
    rows = session.exec(stmt).all()
    return [
        {
            "id": r.id,
            "level": r.level,
            "name": r.name,
            "parent_id": r.parent_id,
            "chapter": r.chapter,
            "desc": r.desc,
            "key_formula": r.key_formula,
            "difficulty_hint": r.difficulty_hint,
            "start_page": r.start_page,
            "end_page": r.end_page,
        }
        for r in rows
    ]


@router.get("/stats", summary="题库统计（校对进度）")
def stats(session: Session = Depends(get_session)):
    problems = session.exec(select(KBProblem)).all()
    kps = session.exec(select(KnowledgePoint)).all()
    by_review: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_chapter: dict[str, int] = {}
    for p in problems:
        by_review[p.review_status] = by_review.get(p.review_status, 0) + 1
        t = p.question_type or "unknown"
        by_type[t] = by_type.get(t, 0) + 1
        c = p.chapter or "unknown"
        by_chapter[c] = by_chapter.get(c, 0) + 1
    return {
        "problems": len(problems),
        "objective": len([p for p in problems if p.is_objective]),
        "subjective": len([p for p in problems if not p.is_objective]),
        "with_answer": len([p for p in problems if p.answer]),
        "with_solution": len([p for p in problems if p.solution]),
        "with_crop_image": len([p for p in problems if p.crop_image_path]),
        "with_kp": len([p for p in problems if p.kp_ids]),
        "by_review_status": by_review,
        "by_type": by_type,
        "by_chapter": by_chapter,
        "knowledge_points": {
            "chapters": len([k for k in kps if k.level == 1]),
            "sections": len([k for k in kps if k.level == 2]),
            "points": len([k for k in kps if k.level == 3]),
        },
    }