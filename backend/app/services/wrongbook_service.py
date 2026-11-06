"""F 模块：错题本。来源 = 答疑未解决 + 自测错题；支持重做与标记掌握。"""

import json

from sqlmodel import Session, select

from ..models import Mastery, Question, WrongBook, utcnow
from . import profile_service as ps


def add_from_question(
    session: Session, user_id: int, q: Question, reason: str = "未解决"
) -> WrongBook:
    """答疑记录进错题本（用户反馈"没懂/不会"时调用）。reason 仅用于日志。"""
    existing = session.exec(
        select(WrongBook).where(
            WrongBook.user_id == user_id, WrongBook.question_id == q.id
        )
    ).first()
    kp_ids = ps.resolve_kp_ids(
        session, (json.loads(q.meta_json or "{}") or {}).get("kp_tags") or []
    )
    fb = json.loads(q.feedback_result) if q.feedback_result else {}
    tags = fb.get("selected") or []

    if existing:
        existing.wrong_count += 1
        existing.last_wrong_at = utcnow()
        existing.status = "pending"
        session.add(existing)
        return existing

    wb = WrongBook(
        user_id=user_id,
        source="qa",
        question_id=q.id,
        kp_ids=json.dumps(kp_ids),
        image_path=q.image_path,
        # 答疑记录的答案在 answer 列（整段讲解），错题本只留错因标签
        error_tags=json.dumps(tags),
        last_wrong_at=utcnow(),
    )
    session.add(wb)
    session.commit()
    session.refresh(wb)
    return wb


def list_wrong(
    session: Session,
    user_id: int,
    status: str | None = None,
    kp_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    stmt = select(WrongBook).where(WrongBook.user_id == user_id)
    if status:
        stmt = stmt.where(WrongBook.status == status)
    rows = session.exec(
        stmt.order_by(WrongBook.last_wrong_at.desc()).offset(offset).limit(limit)
    ).all()
    out = []
    for w in rows:
        if kp_id is not None and (
            kp_id not in json.loads(w.kp_ids or "[]")
        ):
            continue
        out.append(
            {
                "id": w.id,
                "source": w.source,
                "question_id": w.question_id,
                "kb_problem_id": w.kb_problem_id,
                "stem": w.stem,
                "image_path": w.image_path,
                "answer": w.answer,
                "solution": w.solution,
                "error_tags": json.loads(w.error_tags or "[]"),
                "kp_ids": json.loads(w.kp_ids or "[]"),
                "status": w.status,
                "wrong_count": w.wrong_count,
                "last_wrong_at": w.last_wrong_at,
            }
        )
    return out


def mark_mastered(session: Session, user_id: int, wrong_id: int, mastered: bool = True) -> WrongBook | None:
    """标记已掌握：掌握度上调，知识点薄弱度随之下降。"""
    w = session.exec(
        select(WrongBook).where(WrongBook.user_id == user_id, WrongBook.id == wrong_id)
    ).first()
    if w is None:
        return None
    w.status = "mastered" if mastered else "pending"
    w.mastered_at = utcnow() if mastered else None
    session.add(w)

    for kp_id in json.loads(w.kp_ids or "[]"):
        m = session.exec(
            select(Mastery).where(Mastery.user_id == user_id, Mastery.kp_id == kp_id)
        ).first()
        if m is None:
            m = Mastery(user_id=user_id, kp_id=kp_id)
        if mastered:
            m.score = min(1.0, m.score + 0.2)
        else:
            m.score = max(0.0, m.score - 0.1)
        m.last_active_at = utcnow()
        session.add(m)
    session.commit()
    ps.rebuild_profile(session, user_id)
    return w


def stats(session: Session, user_id: int) -> dict:
    rows = session.exec(select(WrongBook).where(WrongBook.user_id == user_id)).all()
    by_status: dict[str, int] = {}
    for w in rows:
        by_status[w.status] = by_status.get(w.status, 0) + 1
    return {
        "total": len(rows),
        "pending": by_status.get("pending", 0),
        "mastered": by_status.get("mastered", 0),
        "from_qa": len([w for w in rows if w.source == "qa"]),
        "from_test": len([w for w in rows if w.source == "test"]),
    }