"""D/E/F 模块测试：诊断报告、自测组卷判分、错题本、上下文管理。"""

import json

from sqlmodel import Session, select

from app.db import engine
from app.models import (
    TokenUsage,
    DiagnosisReport,
    KBProblem,
    KnowledgePoint,
    TestQuestion,
    TestSession,
    WrongBook,
)
from app.services import context_manager as cm
from app.services import diagnose_service as ds
from app.services import test_service as tes
from app.services import wrongbook_service as wbs


def _seed_kb(session, kps: list[str]) -> list[int]:
    """造 2 个知识点 + 每个知识点 3 道题（覆盖三种难度）。"""
    kp_ids = []
    for name in kps:
        kp = KnowledgePoint(level=3, name=name, chapter="测试章")
        session.add(kp)
        session.commit()
        session.refresh(kp)
        kp_ids.append(kp.id)
    for i, kp_id in enumerate(kp_ids):
        for d in (1, 2, 3):
            session.add(
                KBProblem(
                    problem_no=f"T{i}{d}",
                    chapter="测试章",
                    section="测试节",
                    kp_ids=json.dumps([kp_id]),
                    question_type="choice" if d != 3 else "solve",
                    stem=f"测试题 {i}-{d}",
                    options=json.dumps([{"key": "A", "text": "对"}, {"key": "B", "text": "错"}]),
                    answer="A",
                    solution=f"解析 {i}-{d}",
                    difficulty=d,
                    is_objective=d != 3,
                )
            )
    session.commit()
    return kp_ids


def test_build_session_from_weak_points(client):
    """按薄弱点组卷：题目来自题库，覆盖知识点。"""
    with Session(engine) as s:
        kp_ids = _seed_kb(s, ["上下文与裁剪", "薄弱点识别"])

    r = client.post("/api/v1/tests/users/5/sessions?purpose=weakness&count=4")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] > 0
    assert len(body["questions"]) == body["total"]
    q = body["questions"][0]
    assert "stem" in q and "kp_names" in q
    # 主观题应标记为自评模式且不提前给答案
    for item in body["questions"]:
        if item["question_type"] == "solve":
            assert item["self_review"] is True


def test_submit_and_judge(client):
    """提交作答：客观题程序判分、主观题自评；结果回流画像并入错题本。"""
    with Session(engine) as s:
        _seed_kb(s, ["客观判分", "主观自评"])

    created = client.post("/api/v1/tests/users/6/sessions?count=6").json()
    sid = created["id"]

    with Session(engine) as s:
        qs = s.exec(
            select(TestQuestion).where(TestQuestion.session_id == sid)
        ).all()
    answers = []
    for tq in qs:
        if tq.is_objective:
            # 故意交替对错：一半答对一半答错
            right = "A" if tq.id % 2 == 0 else "B"
            answers.append({"question_id": tq.id, "answer": right})
        else:
            answers.append({"question_id": tq.id, "self_correct": True})

    r = client.post(f"/api/v1/tests/sessions/{sid}/submit", json={"answers": answers})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["total"] == len(qs)
    assert res["right"] + res["wrong"] == res["total"]
    assert 0 <= res["score"] <= 1

    # 重复提交应拒绝
    r2 = client.post(f"/api/v1/tests/sessions/{sid}/submit", json={"answers": answers})
    assert r2.status_code == 409

    # 错题自动入错题本
    wb = client.get("/api/v1/wrongbook/users/6").json()
    assert wb["stats"]["from_test"] > 0


def test_judge_objective_normalizes():
    """客观题判分容忍空格与全角符号。"""
    tq = TestQuestion(is_objective=True, answer="A")
    ok, by = tes.judge(tq, " a ")
    assert ok is True and by == "auto"
    ok2, _ = tes.judge(tq, "B")
    assert ok2 is False


def test_wrongbook_mastered_updates_mastery(client):
    """标记已掌握 → 错题状态变更 → 掌握度上调。"""
    with Session(engine) as s:
        kp_ids = _seed_kb(s, ["错题攻克"])
    created = client.post("/api/v1/tests/users/8/sessions?count=2").json()
    sid = created["id"]
    with Session(engine) as s:
        qs = s.exec(select(TestQuestion).where(TestQuestion.session_id == sid)).all()
    client.post(
        f"/api/v1/tests/sessions/{sid}/submit",
        json={"answers": [{"question_id": q.id, "answer": "B"} for q in qs]},
    )

    wb = client.get("/api/v1/wrongbook/users/8?status=pending").json()
    assert wb["items"], "应有待攻克错题"
    wid = wb["items"][0]["id"]

    r = client.put(f"/api/v1/wrongbook/users/8/{wid}/mastered")
    assert r.status_code == 200 and r.json()["status"] == "mastered"
    r2 = client.put(f"/api/v1/wrongbook/users/8/{wid}/mastered?mastered=false")
    assert r2.json()["status"] == "pending"


def test_diagnosis_report_rule_version(client):
    """诊断报告：LLM 关闭时走规则版，仍可生成且不烧 token。"""
    with Session(engine) as s:
        _seed_kb(s, ["诊断知识点"])
    r = client.post("/api/v1/diagnose/users/9?use_llm=false")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 1
    assert body["token_used"] == 0
    assert "# 诊断报告" in body["content_md"]
    assert 0 <= body["confidence"] <= 1

    # 再次生成应产生版本 2，并可对比
    r2 = client.post("/api/v1/diagnose/users/9?use_llm=false")
    assert r2.json()["version"] == 2
    cmp = client.get("/api/v1/diagnose/users/9/compare?v1=1&v2=2").json()
    assert "resolved" in cmp and "new_weak" in cmp and "axis_change" in cmp


def test_context_manager_layers(client):
    """上下文分层：L1 画像摘要受长度上限约束，L2 只保留最近若干轮。"""
    with Session(engine) as s:
        _seed_kb(s, ["上下文知识点"])

    l1 = cm.build_l1_profile(s, 12)
    assert isinstance(l1, str)
    assert len(l1) <= cm.L1_MAX_CHARS

    turns = [{"question": f"第{i}题", "answer": "a", "verdict": "没懂"} for i in range(10)]
    l2 = cm.build_l2_summary(turns)
    assert "第9题" in l2
    assert len(l2) <= cm.L2_MAX_CHARS

    l3 = cm.build_l3_window(turns)
    assert len(l3) == cm.L3_MAX_TURNS
    assert l3[-1]["question"] == "第9题"

    full = cm.compose(s, 12, turns=turns, base_prompt="基础指令")
    assert full.startswith("基础指令")
    assert len(full) <= cm.L1_MAX_CHARS + cm.L2_MAX_CHARS + 16


def test_token_usage_aggregation(client):
    """token 计量：落库 + 汇总接口。"""
    from app.services.token_service import aggregate, record_usage

    with Session(engine) as s:
        record_usage(
            s, user_id=11, scene="qa", model="test",
            prompt_tokens=100, completion_tokens=500, reasoning_tokens=400,
            cache_hit_tokens=80, cache_miss_tokens=20,
        )
        record_usage(s, user_id=11, scene="qa", model="test",
                     prompt_tokens=100, completion_tokens=300, reasoning_tokens=100,
                     cache_hit_tokens=100, cache_miss_tokens=0)
        s.commit()

    with Session(engine) as s:
        rows = s.exec(select(TokenUsage)).all()
    agg = aggregate(rows)
    qa = agg["scenes"]["qa"]
    assert qa["calls"] == 2
    assert qa["total_tokens"] == 1000
    assert qa["cache_hit_rate"] == 90.0
    assert qa["reasoning_share"] == 62.5

    r = client.get("/api/v1/tokens/summary?user_id=11")
    assert r.status_code == 200
    assert r.json()["total_calls"] == 2