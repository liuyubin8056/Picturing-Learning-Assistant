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
