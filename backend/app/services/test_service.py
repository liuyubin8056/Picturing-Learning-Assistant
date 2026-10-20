"""E 模块：自测组卷与判分。

组卷：按薄弱度取知识点 → 从题库（kb_problems）抽题，难度阶梯（基础:中等:挑战 = 3:5:2）。
判分：客观题程序匹配答案；主观题给"我做对/我做错"自选项，只判对错并回库内解析。
详细解析：仅在学生点击"看详解"时上传大模型生成（省 token 的关键设计）。
"""

import json
import re

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


# 学生「看解析还不懂」时的困惑类型（与错因分离：它只用于改进讲解，不改画像权重）
CONFUSION_LABELS = {
    "step": "某一步跳得太快，没跟上",
    "why": "不知道为什么能这样变形/放缩",
    "concept": "用到的概念或定理没学过、忘了",
    "formula": "公式记不住或不会套",
    "start": "完全不知道第一步从哪下手",
    "answer": "不明白答案为什么是这个",
}


def _extract_json(text: str) -> dict | None:
    """从模型输出里抠出 JSON（容忍 ```json 包裹与前后杂字）。"""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(s[i : j + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None

TUTOR_SYSTEM = """你是极其耐心的数学辅导老师。学生已经看过书上的解析，但仍然卡住，现在向你求助。

要求：
1. **先正面回应他的困惑**，不要绕开、不要泛泛复述原解析；
2. 把书上跳步的地方拆开，补上「为什么可以这么做」；
3. 能用具体数字或小例子说明的，就举一个例子；
4. 数学式用 LaTeX：行内 $...$，独立公式用 $$...$$；
5. 结构固定为三段：**你卡在哪**（一句话点出问题）→ **换个角度看**（3~5 步，每步单独成段）→ **这里最容易错**（一句提醒）；
6. 语气像面对面讲题，不要客套。

只输出 JSON，不要代码块标记：
{"explain": "Markdown 讲解正文", "followup": [{"tag": "step", "label": "……"}]}
followup 给出 3 条「如果还不懂，你可能卡在」的候选，tag 只能从 step / why / concept / formula / start / answer 中选。"""


JUDGE_SYSTEM = """你是高数阅卷老师，要判断学生手写解答的对错。

判定原则：
1. **数学等价即可判对**：如 1/2 与 0.5、√2 与 1.414、$x=1$ 与 $x=1,0$ 这类等价表述不要误判；
2. 最终答案正确但步骤有小瑕疵 → correct=true，但在 reason 里点出瑕疵；
3. 最终答案错误 → correct=false，并指出**具体错在哪一步**；
4. 图片模糊或不是解答 → correct 填 null，reason 说明原因（不要瞎判）；
5. 若学生答案缺失但过程正确 → 以过程为准，reason 里说明。

只输出 JSON，不要代码块标记：
{"correct": true/false/null, "student_answer": "识别出的学生最终答案", "reason": "一两句话，指出对在哪/错在哪", "confidence": 0.0~1.0}"""


async def judge_subjective_image(
    session: Session,
    tq: TestQuestion,
    llm: DeepSeekClient,
    image_bytes: bytes,
    mime: str = "image/jpeg",
    user_id: int | None = None,
) -> dict:
    """阅卷：学生上传手写解答照片 → 多模态模型按答案匹配判分。

    判分结果写回 TestQuestion（user_answer / is_correct / judged_by='ai'），
    并即时回流掌握度，这样"考试式作答"也能进画像。
    """
    user_prompt = (
        f"题目：{(tq.stem or '')[:600]}\n"
        f"标准答案：{tq.answer or '（无）'}\n"
        f"参考解析：{(tq.solution or '（无）')[:800]}\n\n"
        "学生的手写解答见图片，请判分。"
    )
    res = await llm.ask_image_custom(JUDGE_SYSTEM, user_prompt, image_bytes, mime, max_tokens=1600)
    data = _extract_json(res.answer) or {}

    correct = data.get("correct")
    if not isinstance(correct, bool):
        correct = None  # 无法判定时不硬判，交给学生自评
    student_answer = str(data.get("student_answer") or "").strip()
    reason = str(data.get("reason") or "").strip()
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0

    tq.judged_by = "ai"
    if student_answer:
        tq.user_answer = student_answer
    if correct is not None:
        tq.is_correct = correct
        # 回流画像（确定性信号）
        try:
            ids = json.loads(tq.kp_ids or "[]")
        except (json.JSONDecodeError, TypeError):
            ids = []
        if ids:
            ps.record_test_result(session, user_id or 0, ids, correct)
    tq.answered_at = utcnow()
    session.add(tq)
    session.commit()

    return {
        "question_id": tq.id,
        "correct": correct,
        "student_answer": student_answer,
        "reason": reason,
        "confidence": round(confidence, 2),
        "usage": res.usage or {},
    }


async def explain_with_feedback(
    session: Session,
    tq: TestQuestion,
    llm: DeepSeekClient,
    feedback_tags: list[str] | None = None,
    custom: str | None = None,
) -> dict:
    """看解析还不懂 → 带着学生的具体困惑让大模型换个讲法。

    与 detailed_solution 的区别：那个是通用详解；这个是**针对困惑定向重讲**，
    困惑类型（含自定义）会原样注入 prompt，所以回答更贴人。
    """
    kp_names = []
    if tq.kp_ids:
        try:
            ids = json.loads(tq.kp_ids)
        except (json.JSONDecodeError, TypeError):
            ids = []
        if ids:
            kps = session.exec(
                select(KnowledgePoint).where(KnowledgePoint.id.in_(ids))
            ).all()
            kp_names = [k.name for k in kps]

    confusions = [
        CONFUSION_LABELS.get(t, t) for t in (feedback_tags or []) if t
    ]
    if custom and custom.strip():
        confusions.append(f"自己的话：{custom.strip()}")

    user_prompt = (
        f"题目：{(tq.stem or '')[:500]}\n"
        f"标准答案：{tq.answer or '（无）'}\n"
        f"书上解析：{(tq.solution or '（无）')[:900]}\n"
        f"涉及知识点：{'、'.join(kp_names) or '未知'}\n"
        f"学生的具体困惑：{'；'.join(confusions) if confusions else '只说了「看不懂」，请先判断他可能卡在哪一步'}\n\n"
        "请按系统要求重新讲一遍，重点解决上述困惑。"
    )

    res = await llm.ask_text(TUTOR_SYSTEM, user_prompt, max_tokens=3200)
    raw = (res.answer or "").strip()
    data = _extract_json(raw)
    if data:
        explain = (data.get("explain") or "").strip() or raw
        followup = data.get("followup") or []
    else:
        # 模型没按 JSON 输出时，整段文本就是讲解正文（内容不丢），只是没有二次选项
        explain = raw
        followup = []

    opts = []
    for item in followup:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag") or "").strip()
        label = str(item.get("label") or "").strip()
        if tag and label:
            opts.append({"tag": tag, "label": label})

    return {
        "question_id": tq.id,
        "explain_md": explain,
        "feedback_options": opts,
        "confusions": confusions,
        "usage": res.usage or {},
    }


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
                stem_image_path=p.stem_image_path,
                solution_image_path=p.solution_image_path,
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