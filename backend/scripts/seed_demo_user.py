"""生成演示用户数据（阶段性汇报用）。

造出一个"像真实学生用了一周"的学习轨迹，覆盖多个章节：
- 答疑记录（含学生反馈的错因）
- 多次练习（得分有起伏，能看到进步趋势）
- 错题本（与练习错题、答疑未解决自洽）
- 掌握度分布（好/中/差混合，雷达图有明显形态）
- 强制重建画像 + 生成规则版诊断报告（零 token 成本）

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/seed_demo_user.py            # 默认用户 1001
    .venv/Scripts/python.exe scripts/seed_demo_user.py --user 2002 --force
"""

import argparse
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.models import (  # noqa: E402
    DiagnosisReport,
    KBProblem,
    KnowledgePoint,
    Mastery,
    ProfileMeta,
    Question,
    TestQuestion,
    TestSession,
    TokenUsage,
    WrongBook,
    utcnow,
)
from app.services import diagnose_service as ds  # noqa: E402
from app.services import profile_service as ps  # noqa: E402

random.seed(20261015)  # 固定种子，保证可复现

# 演示轨迹（天数以前 = 更早）：让"最近一周在持续练习"
PLAN = [
    # (天前, 场景)
    (6, "qa"), (6, "test_low"), (5, "test_mid"), (4, "qa_feedback"),
    (4, "test_mid"), (3, "test_high"), (2, "qa_feedback"), (2, "test_high"),
    (1, "test_perfect"), (1, "qa_feedback"), (0, "test_mid"),
]


def clear_user(s: Session, uid: int) -> None:
    """清空该用户的旧数据（脚本可安全重复运行）。"""
    for q in s.exec(select(Question).where(Question.user_id == uid)).all():
        s.delete(q)
    sessions = s.exec(select(TestSession).where(TestSession.user_id == uid)).all()
    for t in sessions:
        for tq in s.exec(select(TestQuestion).where(TestQuestion.session_id == t.id)).all():
            s.delete(tq)
        s.delete(t)
    for w in s.exec(select(WrongBook).where(WrongBook.user_id == uid)).all():
        s.delete(w)
    for m in s.exec(select(Mastery).where(Mastery.user_id == uid)).all():
        s.delete(m)
    for r in s.exec(select(DiagnosisReport).where(DiagnosisReport.user_id == uid)).all():
        s.delete(r)
    for t in s.exec(select(TokenUsage).where(TokenUsage.user_id == uid)).all():
        s.delete(t)
    pm = s.get(ProfileMeta, uid)
    if pm:
        s.delete(pm)
    s.commit()


def pick_kps(s: Session, n: int = 18) -> list[KnowledgePoint]:
    """按章节均匀选取知识点，保证雷达图覆盖多个章节。"""
    all_kps = s.exec(select(KnowledgePoint).where(KnowledgePoint.level == 3)).all()
    by_chapter: dict[str, list[KnowledgePoint]] = {}
    for k in all_kps:
        by_chapter.setdefault(k.chapter or "未分类", []).append(k)
    # 取知识点较多的前 6 个章节，每章抽 3 个
    chapters = sorted(by_chapter.items(), key=lambda x: -len(x[1]))[:6]
    picked: list[KnowledgePoint] = []
    for _, kps in chapters:
        picked.extend(random.sample(kps, min(3, len(kps))))
    return picked[:n]


def build_mastery(s: Session, uid: int, kps: list[KnowledgePoint], now) -> dict[int, float]:
    """掌握度分布：大部分中等、少量薄弱、少量已掌握（形成雷达图差异）。"""
    scores = [0.85, 0.78, 0.72, 0.65, 0.60, 0.55, 0.48, 0.42, 0.35,
              0.28, 0.22, 0.80, 0.68, 0.52, 0.40, 0.30, 0.58, 0.45]
    err_pools = [
        {"concept_unclear": 2, "calculation": 1},   # 概念型
        {"method_missing": 2, "careless": 1},       # 方法型
        {"knowledge_gap": 1, "misread": 1},         # 遗忘型
        {"no_idea": 1, "condition_miss": 1},        # 无思路型
    ]
    out: dict[int, float] = {}
    for i, kp in enumerate(kps):
        score = scores[i % len(scores)]
        m = Mastery(user_id=uid, kp_id=kp.id, score=score)
        weak = score < 0.5
        # 弱的知识点有更多求助/错题记录
        m.feedback_count = 2 if weak else 1
        m.ask_count = 2 if weak else 0
        m.wrong_count = 1 if weak else 0
        m.right_count = 0 if weak else 2
        m.error_tags = json.dumps(err_pools[i % len(err_pools)], ensure_ascii=False) if weak else None
        if weak and i % 3 == 0:
            m.custom_notes = json.dumps(["课程讲到这节时请假了，自己看书没看懂"], ensure_ascii=False)
        m.last_active_at = now - timedelta(days=random.randint(0, 5))
        m.updated_at = m.last_active_at
        m.created_at = now - timedelta(days=7)
        s.add(m)
        out[kp.id] = score
    s.commit()
    return out


def add_qa(
    s: Session, uid: int, kps: list[KnowledgePoint], when, with_feedback: bool
) -> Question:
    """一条答疑记录（含模型元信息与可选的学生反馈）。"""
    kp = random.choice(kps)
    options = [
        {"tag": "concept_unclear", "label": f"没理解「{kp.name}」的基本定义", "weight": 1.0},
        {"tag": "method_missing", "label": "不知道该套用哪个方法", "weight": 1.0},
        {"tag": "careless", "label": "会做但粗心/算错了", "weight": 0.2},
        {"tag": "misread", "label": "看错题目了或漏看了条件", "weight": 0.2},
        {"tag": "no_idea", "label": "完全没思路，从第一步就不会", "weight": 1.2},
    ]
    picked = random.choice(
        [["concept_unclear"], ["method_missing"], ["careless"], ["concept_unclear", "method_missing"]]
    )
    q = Question(
        user_id=uid,
        client_question_id=f"demo-qa-{random.randint(100000, 999999)}",
        image_path="uploads/.gitkeep",
        status="answered",
        answer=(
            f"【结论】本题考察「{kp.name}」的核心方法。\n\n"
            f"第一步：先整理已知条件，明确要求的目标量。\n\n"
            f"第二步：套用「{kp.name}」的标准公式 $f(x)=x^2+1$ 进行化简。\n\n"
            f"第三步：代入边界条件求值，得到最终结果。"
        ),
        meta_json=json.dumps(
            {
                "subject": "数学",
                "chapter": kp.chapter,
                "kp_tags": [kp.name],
                "difficulty": random.choice([1, 2, 2, 3]),
                "suspected_error_type": "概念不清",
                "feedback_options": options,
                "profile_delta": {"confusion": f"{kp.name}的适用条件", "hint": "下次先讲条件再讲公式"},
            },
            ensure_ascii=False,
        ),
        feedback_options=json.dumps(options, ensure_ascii=False),
        created_at=when,
        answered_at=when + timedelta(seconds=95),
    )
    if with_feedback:
        q.feedback_result = json.dumps(
            {"selected": picked, "custom": [], "solved": False}, ensure_ascii=False
        )
        q.feedback_at = when + timedelta(minutes=3)
    s.add(q)
    s.commit()
    s.refresh(q)
    return q


def add_test(
    s: Session, uid: int, problems: list[KBProblem], kps: list[KnowledgePoint],
    when, accuracy: float,
) -> TestSession:
    """一次练习：按 accuracy 决定对错分布，错题同步进错题本。"""
    n = random.choice([3, 5])
    chosen = random.sample(problems, min(n, len(problems)))
    ts = TestSession(
        user_id=uid,
        title=f"针对性练习（{len(chosen)} 题）",
        purpose=random.choice(["weakness", "review"]),
        kp_ids=json.dumps([k.id for k in kps[:5]]),
        total_count=len(chosen),
        status="submitted",
        created_at=when,
        submitted_at=when + timedelta(minutes=random.randint(8, 25)),
    )
    s.add(ts)
    s.commit()
    s.refresh(ts)

    right = 0
    for order, p in enumerate(chosen, 1):
        ok = random.random() < accuracy
        tq = TestQuestion(
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
            user_answer=p.answer if ok else "B",
            is_correct=ok,
            judged_by="auto" if p.is_objective else "self",
            answered_at=ts.submitted_at,
        )
        s.add(tq)
        if ok:
            right += 1
    ts.right_count = right
    ts.wrong_count = len(chosen) - right
    ts.score = round(right / len(chosen), 3)
    s.add(ts)
    s.commit()

    # 错题入库
    for tq in s.exec(select(TestQuestion).where(TestQuestion.session_id == ts.id)).all():
        if tq.is_correct is False:
            s.add(
                WrongBook(
                    user_id=uid,
                    source="test",
                    test_question_id=tq.id,
                    kb_problem_id=tq.kb_problem_id,
                    kp_ids=tq.kp_ids,
                    stem=tq.stem,
                    image_path=tq.image_path,
                    answer=tq.answer,
                    solution=tq.solution,
                    status="pending",
                    wrong_count=random.choice([1, 1, 2]),
                    last_wrong_at=ts.submitted_at,
                    created_at=ts.submitted_at,
                )
            )
    s.commit()
    return ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=1001, help="演示用户 ID")
    ap.add_argument("--force", action="store_true", help="已存在时也重建")
    args = ap.parse_args()
    uid = args.user

    init_db()
    now = utcnow()
    with Session(engine) as s:
        existing = s.exec(select(Mastery).where(Mastery.user_id == uid)).all()
        if existing and not args.force:
            print(f"用户 {uid} 已有数据（{len(existing)} 条掌握度）。如需重建请加 --force")
            return

        clear_user(s, uid)
        kps = pick_kps(s)
        problems = s.exec(select(KBProblem).where(KBProblem.answer.is_not(None))).all()
        if not problems:
            print("题库为空，请先运行 scripts/kb/04_extract.py")
            return

        print(f"为演示用户 {uid} 构造学习轨迹：{len(kps)} 个知识点 / {len(problems)} 道题库题")
        build_mastery(s, uid, kps, now)

        # 按计划铺开一周的活动
        for days_ago, scene in PLAN:
            when = now - timedelta(days=days_ago, hours=random.randint(18, 22) % 12)
            if scene == "qa":
                add_qa(s, uid, kps, when, with_feedback=False)
            elif scene == "qa_feedback":
                add_qa(s, uid, kps, when, with_feedback=True)
            elif scene.startswith("test"):
                acc = {"test_low": 0.33, "test_mid": 0.6, "test_high": 0.8, "test_perfect": 1.0}[scene]
                add_test(s, uid, problems, kps, when, acc)

        # 画像与诊断报告
        out = ps.rebuild_profile(s, uid)
        report = ds.build_local_report(s, uid)
        r = DiagnosisReport(
            user_id=uid,
            version=1,
            title="学习诊断报告",
            content_md=report["content_md"],
            weak_kp_ids=json.dumps(report["weak_kp_ids"]),
            strong_kp_ids=json.dumps(report["strong_kp_ids"]),
            radar_json=json.dumps(report["radar"], ensure_ascii=False),
            evidence_json="[]",
            signal_count=report["radar"]["signal_count"],
            confidence=report["confidence"],
            token_used=0,
            created_at=now,
        )
        s.add(r)
        s.commit()

        # 汇总
        n_q = len(s.exec(select(Question).where(Question.user_id == uid)).all())
        n_t = len(s.exec(select(TestSession).where(TestSession.user_id == uid)).all())
        n_w = len(s.exec(select(WrongBook).where(WrongBook.user_id == uid)).all())
        print(f"\n完成：答疑 {n_q} 条 / 练习 {n_t} 次 / 错题 {n_w} 条 / 画像 {out['md_path']}")
        print(f"诊断报告：薄弱 {len(report['weak_kp_ids'])} 个，置信度 {report['confidence']}")
        print(f"\n前端「我的」页切换用户 ID 为 {uid} 即可查看")


if __name__ == "__main__":
    main()