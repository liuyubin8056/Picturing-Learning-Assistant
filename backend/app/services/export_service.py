"""数据导出：把单个用户的全部学习数据打成一份 JSON。

为什么需要：合规上「用户可带走自己的数据」和「可注销」是一对，
现在只有注销没有导出。尤其是学生（含未成年人），数据可迁移是底线要求。

导出范围（只含本人数据，不含题库）：
    账户 / 答疑 / 练习会话 + 逐题作答 / 错题本 / 掌握度 / 诊断报告 / 画像 / token 用量
不导出：密码哈希、令牌、验证码（凭证类，导出即泄露）
"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from ..models import (
    DiagnosisReport,
    Mastery,
    Question,
    TestQuestion,
    TestSession,
    TokenUsage,
    User,
    WrongBook,
    utcnow,
)

SCHEMA_VERSION = 1


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _loads(text: str | None, default: Any) -> Any:
    """JSON 字段安全解析：坏数据不要让整个导出失败。"""
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def export_user_data(session: Session, user: User) -> dict:
    uid = user.id

    questions = session.exec(
        select(Question).where(Question.user_id == uid).order_by(Question.id)
    ).all()

    sessions = session.exec(
        select(TestSession).where(TestSession.user_id == uid).order_by(TestSession.id)
    ).all()
    session_ids = [s.id for s in sessions]
    tqs = []
    if session_ids:
        tqs = session.exec(
            select(TestQuestion)
            .where(TestQuestion.session_id.in_(session_ids))
            .order_by(TestQuestion.session_id, TestQuestion.order_no)
        ).all()
    by_session: dict[int, list] = {}
    for t in tqs:
        by_session.setdefault(t.session_id, []).append(t)

    wrong = session.exec(
        select(WrongBook).where(WrongBook.user_id == uid).order_by(WrongBook.id)
    ).all()
    mastery = session.exec(
        select(Mastery).where(Mastery.user_id == uid).order_by(Mastery.kp_id)
    ).all()
    reports = session.exec(
        select(DiagnosisReport)
        .where(DiagnosisReport.user_id == uid)
        .order_by(DiagnosisReport.version)
    ).all()
    usage = session.exec(
        select(TokenUsage).where(TokenUsage.user_id == uid).order_by(TokenUsage.id)
    ).all()

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": _iso(utcnow()),
        "note": "本文件包含你的全部学习数据，不含密码与登录令牌。",

        "account": {
            "id": user.id,
            "email": user.email,
            "nickname": user.nickname,
            "created_at": _iso(user.created_at),
            "last_login_at": _iso(user.last_login_at),
            "is_demo": user.is_demo,
        },

        "summary": {
            "questions": len(questions),
            "test_sessions": len(sessions),
            "test_questions": len(tqs),
            "wrong_books": len(wrong),
            "mastery_points": len(mastery),
            "diagnose_reports": len(reports),
            "token_records": len(usage),
            "total_tokens": sum(u.total_tokens or 0 for u in usage),
        },

        "questions": [
            {
                "id": q.id,
                "client_question_id": q.client_question_id,
                "status": q.status,
                "image_path": q.image_path,
                "answer": q.answer,
                "problems": _loads(q.problems_json, None),
                "meta": _loads(q.meta_json, None),
                "feedback": _loads(q.feedback_result, None),
                "feedback_at": _iso(q.feedback_at),
                "created_at": _iso(q.created_at),
                "answered_at": _iso(q.answered_at),
                "error_msg": q.error_msg,
            }
            for q in questions
        ],

        "test_sessions": [
            {
                "id": s.id,
                "title": s.title,
                "purpose": s.purpose,
                "kp_ids": _loads(s.kp_ids, []),
                "total_count": s.total_count,
                "right_count": s.right_count,
                "wrong_count": s.wrong_count,
                "score": s.score,
                "status": s.status,
                "created_at": _iso(s.created_at),
                "submitted_at": _iso(s.submitted_at),
                "questions": [
                    {
                        "order_no": t.order_no,
                        "kb_problem_id": t.kb_problem_id,
                        "question_type": t.question_type,
                        "difficulty": t.difficulty,
                        "stem": t.stem,
                        "options": _loads(t.options, None),
                        "answer": t.answer,
                        "solution": t.solution,
                        "user_answer": t.user_answer,
                        "is_correct": t.is_correct,
                        "judged_by": t.judged_by,
                        "answered_at": _iso(t.answered_at),
                        "kp_ids": _loads(t.kp_ids, []),
                    }
                    for t in by_session.get(s.id, [])
                ],
            }
            for s in sessions
        ],

        "wrong_books": [
            {
                "id": w.id,
                "source": w.source,
                "kb_problem_id": w.kb_problem_id,
                "question_id": w.question_id,
                "stem": w.stem,
                "answer": w.answer,
                "solution": w.solution,
                "error_tags": _loads(w.error_tags, []),
                "kp_ids": _loads(w.kp_ids, []),
                "status": w.status,
                "wrong_count": w.wrong_count,
                "last_wrong_at": _iso(w.last_wrong_at),
                "mastered_at": _iso(w.mastered_at),
                "created_at": _iso(w.created_at),
            }
            for w in wrong
        ],

        "mastery": [
            {
                "kp_id": m.kp_id,
                "score": m.score,
                "ask_count": m.ask_count,
                "wrong_count": m.wrong_count,
                "right_count": m.right_count,
                "feedback_count": m.feedback_count,
                "error_tags": _loads(m.error_tags, []),
                "custom_notes": m.custom_notes,
                "last_active_at": _iso(m.last_active_at),
            }
            for m in mastery
        ],

        "diagnose_reports": [
            {
                "version": r.version,
                "title": r.title,
                "content_md": r.content_md,
                "weak_kp_ids": _loads(r.weak_kp_ids, []),
                "strong_kp_ids": _loads(r.strong_kp_ids, []),
                "signal_count": r.signal_count,
                "confidence": r.confidence,
                "created_at": _iso(r.created_at),
            }
            for r in reports
        ],

        "token_usage": [
            {
                "scene": u.scene,
                "model": u.model,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "reasoning_tokens": u.reasoning_tokens,
                "total_tokens": u.total_tokens,
                "latency_ms": u.latency_ms,
                "created_at": _iso(u.created_at),
            }
            for u in usage
        ],
    }

# ============================================================
# 文件名与导入
# ============================================================


def _safe_name(text: str | None, fallback: str = "用户") -> str:
    """文件名里不能出现路径分隔符与 Windows 保留字符。"""
    if not text:
        return fallback
    for ch in '\\/:*?"<>|\n\r\t':
        text = text.replace(ch, "")
    return text.strip()[:24] or fallback


def suggest_filename(user: User) -> str:
    """导出文件名：昵称 + 精确到秒的时间，便于用户区分数据新旧。"""
    name = _safe_name(user.nickname, f"user{user.id}")
    # 用本地时间：用户看文件名想对应"我什么时候导的"
    ts = utcnow().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"学习数据-{name}-{ts}.json"


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def import_user_data(
    session: Session, user: User, payload: dict, mode: str = "merge"
) -> dict:
    """把导出的 JSON 导回账号。

    mode = merge   ：与现有数据合并（掌握度取较高分、错题累加、答疑按幂等 ID 去重）
    mode = replace ：先清空该账号的学习数据，再全量恢复（账户本身不删）

    只接受本系统导出的结构；缺失字段一律跳过，不因单条坏数据整体失败。
    """
    if not isinstance(payload, dict):
        raise ValueError("文件内容不是有效的 JSON 对象")
    if payload.get("schema_version") not in (None, SCHEMA_VERSION):
        raise ValueError("数据文件版本不兼容，请使用本系统导出的文件")

    uid = user.id
    stats = {"mastery": 0, "wrong_books": 0, "questions": 0, "test_sessions": 0}

    if mode == "replace":
        for model in (Mastery, WrongBook, Question, TestQuestion, DiagnosisReport):
            if model is TestQuestion:
                continue
            for row in session.exec(select(model).where(model.user_id == uid)).all():
                session.delete(row)
        # 练习会话：先删题目再删会话
        for ts in session.exec(
            select(TestSession).where(TestSession.user_id == uid)
        ).all():
            for tq in session.exec(
                select(TestQuestion).where(TestQuestion.session_id == ts.id)
            ).all():
                session.delete(tq)
            session.delete(ts)
        session.commit()

    # ---- 掌握度 ----
    for item in payload.get("mastery") or []:
        kp_id = item.get("kp_id")
        if not kp_id:
            continue
        row = session.exec(
            select(Mastery).where(Mastery.user_id == uid, Mastery.kp_id == kp_id)
        ).first()
        if row:
            row.score = max(row.score or 0.0, float(item.get("score") or 0))
            row.ask_count = max(row.ask_count or 0, int(item.get("ask_count") or 0))
            row.wrong_count = max(row.wrong_count or 0, int(item.get("wrong_count") or 0))
            row.right_count = max(row.right_count or 0, int(item.get("right_count") or 0))
            row.feedback_count = max(
                row.feedback_count or 0, int(item.get("feedback_count") or 0)
            )
            row.last_active_at = _parse_dt(item.get("last_active_at")) or row.last_active_at
            session.add(row)
        else:
            session.add(
                Mastery(
                    user_id=uid,
                    kp_id=kp_id,
                    score=float(item.get("score") or 0),
                    ask_count=int(item.get("ask_count") or 0),
                    wrong_count=int(item.get("wrong_count") or 0),
                    right_count=int(item.get("right_count") or 0),
                    feedback_count=int(item.get("feedback_count") or 0),
                    error_tags=json.dumps(item.get("error_tags") or [], ensure_ascii=False),
                    custom_notes=item.get("custom_notes"),
                    last_active_at=_parse_dt(item.get("last_active_at")),
                )
            )
        stats["mastery"] += 1

    # ---- 错题本（按题库题目合并）----
    for item in payload.get("wrong_books") or []:
        kb_id = item.get("kb_problem_id")
        stem = item.get("stem")
        if not kb_id and not stem:
            continue
        row = None
        if kb_id:
            row = session.exec(
                select(WrongBook).where(
                    WrongBook.user_id == uid, WrongBook.kb_problem_id == kb_id
                )
            ).first()
        if row:
            row.wrong_count = (row.wrong_count or 0) + int(item.get("wrong_count") or 1)
            # 任一方未掌握就保持待攻克
            if (row.status or "pending") == "pending" or item.get("status") == "pending":
                row.status = "pending"
            session.add(row)
        else:
            session.add(
                WrongBook(
                    user_id=uid,
                    source=item.get("source") or "import",
                    kb_problem_id=kb_id,
                    stem=stem,
                    answer=item.get("answer"),
                    solution=item.get("solution"),
                    error_tags=json.dumps(item.get("error_tags") or [], ensure_ascii=False),
                    kp_ids=json.dumps(item.get("kp_ids") or []),
                    status=item.get("status") or "pending",
                    wrong_count=int(item.get("wrong_count") or 1),
                    last_wrong_at=_parse_dt(item.get("last_wrong_at")),
                )
            )
        stats["wrong_books"] += 1

    # ---- 答疑记录（按幂等 ID 去重，避免合并出重复题）----
    existing_cids = {
        c
        for c in session.exec(
            select(Question.client_question_id).where(Question.user_id == uid)
        ).all()
        if c
    }
    for item in payload.get("questions") or []:
        cid = item.get("client_question_id")
        if cid and cid in existing_cids:
            continue
        if not item.get("answer"):
            continue
        session.add(
            Question(
                user_id=uid,
                client_question_id=cid or f"import-{utcnow().timestamp()}",
                status=item.get("status") or "answered",
                # image_path 在模型里非空；导入外部文件时可能缺失，用空串占位
                image_path=item.get("image_path") or "",
                answer=item.get("answer"),
                meta_json=json.dumps(item.get("meta"), ensure_ascii=False)
                if item.get("meta")
                else None,
                problems_json=json.dumps(item.get("problems"), ensure_ascii=False)
                if item.get("problems")
                else None,
                feedback_result=json.dumps(item.get("feedback"), ensure_ascii=False)
                if item.get("feedback")
                else None,
                created_at=_parse_dt(item.get("created_at")) or utcnow(),
                answered_at=_parse_dt(item.get("answered_at")),
            )
        )
        stats["questions"] += 1

    # ---- 练习会话（作为历史导入）----
    for item in payload.get("test_sessions") or []:
        created = _parse_dt(item.get("created_at"))
        title = item.get("title") or "导入的练习"
        dup = session.exec(
            select(TestSession).where(
                TestSession.user_id == uid, TestSession.title == title
            )
        ).first()
        if dup:
            continue
        ts = TestSession(
            user_id=uid,
            title=title,
            purpose=item.get("purpose") or "import",
            kp_ids=json.dumps(item.get("kp_ids") or []),
            total_count=int(item.get("total_count") or 0),
            right_count=int(item.get("right_count") or 0),
            wrong_count=int(item.get("wrong_count") or 0),
            score=item.get("score"),
            status=item.get("status") or "submitted",
            created_at=created or utcnow(),
            submitted_at=_parse_dt(item.get("submitted_at")),
        )
        session.add(ts)
        session.commit()
        session.refresh(ts)
        for q in item.get("questions") or []:
            session.add(
                TestQuestion(
                    session_id=ts.id,
                    kb_problem_id=q.get("kb_problem_id"),
                    order_no=int(q.get("order_no") or 1),
                    stem=q.get("stem"),
                    options=json.dumps(q.get("options"), ensure_ascii=False)
                    if q.get("options")
                    else None,
                    answer=q.get("answer"),
                    solution=q.get("solution"),
                    kp_ids=json.dumps(q.get("kp_ids") or []),
                    question_type=q.get("question_type"),
                    difficulty=q.get("difficulty"),
                    user_answer=q.get("user_answer"),
                    is_correct=q.get("is_correct"),
                    judged_by=q.get("judged_by"),
                    answered_at=_parse_dt(q.get("answered_at")),
                )
            )
        stats["test_sessions"] += 1

    session.commit()
    return {"mode": mode, "imported": stats}
