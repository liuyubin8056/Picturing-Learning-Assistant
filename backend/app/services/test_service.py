"""E 模块：自测组卷与判分。

组卷：按薄弱度取知识点 → 从题库（kb_problems）抽题，难度阶梯（基础:中等:挑战 = 3:5:2）。
判分：客观题程序匹配答案；主观题给"我做对/我做错"自选项，只判对错并回库内解析。
详细解析：仅在学生点击"看详解"时上传大模型生成（省 token 的关键设计）。
"""

import json

from sqlmodel import Session, select

from ..llm.deepseek import DeepSeekClient
from ..models import (
    KBProblem,
    KnowledgePoint,
    TestQuestion,
    TestSession,
    WrongBook,
    utcnow,
)
from . import profile_service as ps

DIFFICULTY_MIX = (1, 1, 2, 2, 2, 3)  # 每 6 题的难度阶梯
EXPLAIN_SYSTEM = """你是高数教师，要把库内已有解析改写成给学生看的详细讲解。

要求：
1. 在原有解析基础上补充：这一步在做什么、为什么用它、易错点是什么。
2. 用 Markdown，分步骤，控制在 400 字以内。
3. 禁止使用英文双引号。"""


def pick_knowledge_points(
    session: Session, user_id: int, purpose: str = "weakness", limit: int = 6
) -> list[int]:
    """按用途选知识点：薄弱点优先 / 复习（高掌握度）/ 章节（全部样本）。

    新用户尚无画像数据时，回退到题库中出现频次最高的知识点，保证首次组卷可用。
    """
    stats = ps.user_kp_stats(session, user_id)
    if stats:
        if purpose == "review":
            ranked = sorted(stats, key=lambda x: -x["score"])
        else:
            weak = [s for s in stats if s["weak"] >= ps.WEAK_THRESHOLD]
            ranked = weak or sorted(stats, key=lambda x: -x["weak"])
        return [s["kp_id"] for s in ranked[:limit]]

    # 冷启动：按题库覆盖度挑知识点（题多的先练）
    rows = session.exec(
        select(KBProblem).where(KBProblem.kp_ids.is_not(None)).limit(500)
    ).all()
    counter: dict[int, int] = {}
    names: dict[int, str] = {}
    for p in rows:
        try:
            for i in json.loads(p.kp_ids or "[]"):
                counter[i] = counter.get(i, 0) + 1
        except json.JSONDecodeError:
            continue
    for kp in session.exec(select(KnowledgePoint).where(KnowledgePoint.level == 3)).all():
        names[kp.id] = kp.name
    return [kp_id for kp_id, _ in sorted(counter.items(), key=lambda x: -x[1])[:limit]]


def build_session(
    session: Session,
    user_id: int,
    purpose: str = "weakness",
    kp_ids: list[int] | None = None,
    count: int = 6,
    chapter: str | None = None,
) -> TestSession:
    """组卷：从题库按知识点抽题，题面做快照。"""
    kp_ids = kp_ids or pick_knowledge_points(session, user_id, purpose)

    picked: list[KBProblem] = []
    for i, kp_id in enumerate(kp_ids):
        want = DIFFICULTY_MIX[i % len(DIFFICULTY_MIX)]
        stmt = select(KBProblem).where(
            KBProblem.kp_ids.is_not(None), KBProblem.answer.is_not(None)
        )
        if chapter:
            stmt = stmt.where(KBProblem.chapter == chapter)
        rows = session.exec(stmt.limit(200)).all()
        same = [
            p
            for p in rows
            if p.kp_ids and kp_id in json.loads(p.kp_ids)
        ]
        hit = next((p for p in same if p.difficulty == want), None) or (same[0] if same else None)
        if hit and hit.id not in {p.id for p in picked}:
            picked.append(hit)

    if not picked:  # 题库为空或无匹配 → 建空会话，前端提示先做题库
        s = TestSession(
            user_id=user_id,
            title="自测",
            purpose=purpose,
            kp_ids=json.dumps(kp_ids),
            total_count=0,
            status="pending",
        )
        session.add(s)
        session.commit()
        session.refresh(s)
        return s

    ts = TestSession(
        user_id=user_id,
        title=f"针对性练习（{len(picked)} 题）",
        purpose=purpose,
        kp_ids=json.dumps(kp_ids),
        total_count=len(picked),
        status="pending",
    )
    session.add(ts)
    session.commit()
    session.refresh(ts)

    for order, p in enumerate(picked, 1):
        session.add(
            TestQuestion(
                session_id=ts.id,
                kb_problem_id=p.id,
                order_no=order,
                stem=p.stem,
                options=p.options,
                answer=p.answer,
                solution=p.solution,
                image_path=p.crop_image_path,
                kp_ids=p.kp_ids,
                question_type=p.question_type,
                is_objective=p.is_objective,
                difficulty=p.difficulty,
            )
        )
    session.commit()
    session.refresh(ts)
    return ts


def _normalize(text: str | None) -> str:
    """答案归一化：去空白、统一大小写与常见符号，便于匹配判分。"""
    if not text:
        return ""
    t = text.strip().upper()
    for ch in " \t　,，.。;；:：":
        t = t.replace(ch, "")
    return t.replace("−", "-").replace("－", "-")


def judge(
    tq: TestQuestion, user_answer: str | None, self_correct: bool | None = None
) -> tuple[bool, str]:
    """判分：客观题匹配答案；主观题用自选项。返回 (是否正确, 判定方式)。"""
    if tq.is_objective:
        ok = _normalize(user_answer) == _normalize(tq.answer)
        return ok, "auto"
    # 主观题：学生自评；未给自评则默认判错（保守）
    return bool(self_correct), "self"


def submit_session(
    session: Session,
    ts: TestSession,
    answers: dict[int, dict],
) -> dict:
    """提交作答：逐题判分 → 更新画像 → 错题入库 → 汇总结果。"""
    qs = session.exec(
        select(TestQuestion)
        .where(TestQuestion.session_id == ts.id)
        .order_by(TestQuestion.order_no)
    ).all()

    detail = []
    right = wrong = 0
    for tq in qs:
        a = answers.get(tq.id) or answers.get(str(tq.id)) or {}
        ua = a.get("answer")
        self_correct = a.get("self_correct")
        ok, by = judge(tq, ua, self_correct)
        tq.user_answer = ua
        tq.is_correct = ok
        tq.judged_by = by
        tq.answered_at = utcnow()
        session.add(tq)

        if ok:
            right += 1
        else:
            wrong += 1
            _add_wrong_book(session, ts.user_id, tq=tq)
        # 客观题判分结果直接入画像
        kp_ids = json.loads(tq.kp_ids or "[]")
        ps.record_test_result(
            session,
            ts.user_id,
            kp_ids,
            correct=ok,
            subjective_self=None if by == "auto" else ok,
        )
        detail.append(
            {
                "question_id": tq.id,
                "correct": ok,
                "judged_by": by,
                "your_answer": ua,
                "correct_answer": tq.answer,
                "solution": tq.solution if by == "auto" or ok else tq.solution,
            }
        )

    ts.right_count = right
    ts.wrong_count = wrong
    ts.score = round(right / len(qs), 3) if qs else 0.0
    ts.status = "submitted"
    ts.submitted_at = utcnow()
    session.add(ts)
    session.commit()

    ps.rebuild_profile(session, ts.user_id)
    return {
        "session_id": ts.id,
        "total": len(qs),
        "right": right,
        "wrong": wrong,
        "score": ts.score,
        "detail": detail,
    }


def _add_wrong_book(session: Session, user_id: int, tq: TestQuestion) -> None:
    """自测错题入错题本（同题重复错则累加次数）。"""
    existing = session.exec(
        select(WrongBook).where(
            WrongBook.user_id == user_id,
            WrongBook.test_question_id == tq.id,
        )
    ).first()
    if existing:
        existing.wrong_count += 1
        existing.last_wrong_at = utcnow()
        existing.status = "pending"
        session.add(existing)
        return
    session.add(
        WrongBook(
            user_id=user_id,
            source="test",
            test_question_id=tq.id,
            kb_problem_id=tq.kb_problem_id,
            kp_ids=tq.kp_ids,
            stem=tq.stem,
            image_path=tq.image_path,
            answer=tq.answer,
            solution=tq.solution,
            last_wrong_at=utcnow(),
        )
    )


async def detailed_solution(
    session: Session, tq: TestQuestion, llm: DeepSeekClient
) -> dict:
    """详细解析：按需上传大模型（库内解析作为 prompt 基底，避免从零生成）。"""
    kp_names = []
    if tq.kp_ids:
        kps = session.exec(
            select(KnowledgePoint).where(
                KnowledgePoint.id.in_(json.loads(tq.kp_ids))
            )
        ).all()
        kp_names = [k.name for k in kps]

    user_prompt = (
        f"题目：{(tq.stem or '')[:400]}\n"
        f"标准答案：{tq.answer or ''}\n"
        f"库内解析：{(tq.solution or '')[:800]}\n"
        f"涉及知识点：{'、'.join(kp_names) or '未知'}\n\n"
        "请改写成详细讲解。"
    )
    res = await llm.ask_text(EXPLAIN_SYSTEM, user_prompt, max_tokens=3000)
    return {
        "question_id": tq.id,
        "detailed": res.answer,
        "token_used": res.usage.get("completion_tokens", 0),
        "usage": res.usage,
    }