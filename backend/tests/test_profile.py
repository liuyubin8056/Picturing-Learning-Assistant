"""个性画像链路测试：反馈多选+自定义、掌握度更新、md 生成、雷达图 JSON。"""

import json

from sqlmodel import Session, select

from app.db import engine
from app.models import KnowledgePoint, Mastery, Question


def _seed_kp(session) -> int:
    """造一个知识点与一道带 meta 的题目（meta 含知识点 id 与反馈选项权重）。"""
    kp = session.exec(select(KnowledgePoint).where(KnowledgePoint.level == 3)).first()
    if kp is None:  # 测试库为空时自建，保证自包含
        kp = KnowledgePoint(level=3, name="测试知识点", chapter="测试章")
        session.add(kp)
        session.commit()
        session.refresh(kp)
    q = Question(
        user_id=99,
        client_question_id="prof-test-1",
        image_path="x.png",
        status="answered",
        answer="解答",
        meta_json=json.dumps(
            {
                "kp_tags": [kp.name],
                "feedback_options": [
                    {"tag": "concept_unclear", "label": "概念没懂", "weight": 1.0},
                    {"tag": "careless", "label": "粗心算错", "weight": 0.2},
                ],
            },
            ensure_ascii=False,
        ),
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return kp.id, q.id


def test_feedback_updates_mastery_and_profile(client):
    """用户自报错因 → 掌握度入账 → 生成画像 md。"""
    from app.db import get_session  # noqa: F401  确保依赖可用

    with Session(engine) as s:
        kp_id, q_id = _seed_kp(s)

    # 1) 反馈：选「概念没懂」(权重1.0) + 自定义
    r = client.post(
        f"/api/v1/profile/questions/{q_id}/feedback",
        json={
            "selected": ["concept_unclear"],
            "custom": ["没记住公式的适用条件"],
            "solved": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_updated"] is True
    assert body["kp_updated"] >= 1
    assert body["score_delta"] < 0  # 真实漏洞应降低掌握度

    with Session(engine) as s:
        m = s.exec(select(Mastery).where(Mastery.user_id == 99, Mastery.kp_id == kp_id)).first()
        assert m is not None
        assert m.feedback_count == 1
        tags = json.loads(m.error_tags)
        assert tags["concept_unclear"] == 1
        notes = json.loads(m.custom_notes)
        assert "没记住公式的适用条件" in notes[0]

    # 2) 画像 md 已生成且含薄弱知识点
    r2 = client.get("/api/v1/profile/users/99")
    assert r2.status_code == 200
    data = r2.json()
    md = data["markdown"]
    assert "# 用户画像 · 99" in md
    assert "薄弱环节" in md
    assert kp_id in [s["kp_id"] for s in data["stats"]]

    # 3) 自定义内容出现在画像中
    r3 = client.get("/api/v1/profile/users/99/markdown")
    assert r3.status_code == 200
    assert "没记住公式的适用条件" in r3.text


def test_low_level_error_weak_score_lower(client):
    """低级错误（粗心）不应被当成知识薄弱：同样反馈下薄弱度明显更低。"""
    from app.services.profile_service import weak_score

    with Session(engine) as s:
        kp_id, q_id = _seed_kp(s)
        kp = s.get(KnowledgePoint, kp_id)
        q2 = Question(
            user_id=98,
            client_question_id="prof-test-2",
            image_path="y.png",
            status="answered",
            answer="a",
            meta_json=json.dumps(
                {
                    "kp_tags": [kp.name],
                    "feedback_options": [{"tag": "careless", "weight": 0.2}],
                },
                ensure_ascii=False,
            ),
        )
        s.add(q2)
        s.commit()
        s.refresh(q2)

    # 用户 99 选概念不清
    client.post(
        f"/api/v1/profile/questions/{q_id}/feedback",
        json={"selected": ["concept_unclear"]},
    )
    # 用户 98 选粗心
    client.post(
        f"/api/v1/profile/questions/{q2.id}/feedback",
        json={"selected": ["careless"]},
    )

    with Session(engine) as s:
        m1 = s.exec(select(Mastery).where(Mastery.user_id == 99)).first()
        m2 = s.exec(select(Mastery).where(Mastery.user_id == 98)).first()
        w_real = weak_score(m1)
        w_careless = weak_score(m2)
    assert w_real > w_careless, f"真实漏洞({w_real}) 应比粗心({w_careless}) 薄弱度更高"


def test_multi_choice_not_diluted_by_low_level_tag(client):
    """多选错因时取「最强错因」：勾了粗心不能把「概念不清」稀释成不薄弱。

    回归用例：此前用平均值，粗心(0.2)+概念不清(1.0) 平均成 0.6，
    薄弱度只有 0.33（低于 0.35 阈值）→ 真实知识漏洞被漏判。
    """
    from app.models import Mastery
    from app.services.profile_service import weak_score

    both = Mastery(user_id=1, kp_id=1, ask_count=1, feedback_count=1)
    both.error_tags = json.dumps({"careless": 1, "concept_unclear": 1})
    only_careless = Mastery(user_id=1, kp_id=1, feedback_count=1)
    only_careless.error_tags = json.dumps({"careless": 1})

    w_both = weak_score(both)
    w_careless = weak_score(only_careless)

    assert w_both >= 0.35, f"勾选概念不清应判薄弱，实际 {w_both}"
    assert w_both > w_careless, "多选含真实错因时，薄弱度必须高于纯粗心"
    assert w_careless == 0.0, f"纯粗心不应判薄弱，实际 {w_careless}"


def test_solved_feedback_raises_score(client):
    """反馈「已看懂/会了」应提升掌握度。"""
    with Session(engine) as s:
        kp_id, q_id = _seed_kp(s)
    client.post(
        f"/api/v1/profile/questions/{q_id}/feedback",
        json={"selected": [], "custom": [], "solved": True},
    )
    with Session(engine) as s:
        m = s.exec(select(Mastery).where(Mastery.user_id == 99)).first()
        assert m is not None
        assert m.score > 0, "会了应使掌握度大于初始值"


def test_empty_feedback_rejected(client):
    """空反馈应被拒（422）。"""
    with Session(engine) as s:
        _, q_id = _seed_kp(s)
    r = client.post(f"/api/v1/profile/questions/{q_id}/feedback", json={})
    assert r.status_code == 422


def test_radar_json_shape(client):
    """雷达图接口返回前端可直接消费的 JSON 结构。"""
    with Session(engine) as s:
        _, q_id = _seed_kp(s)
    client.post(
        f"/api/v1/profile/questions/{q_id}/feedback",
        json={"selected": ["concept_unclear"]},
    )
    r = client.get("/api/v1/profile/users/99/radar")
    assert r.status_code == 200
    d = r.json()
    assert "axes" in d and "weak_points" in d and "signal_count" in d
    if d["axes"]:
        a = d["axes"][0]
        assert {"axis", "value", "kp_count"} <= set(a)
        assert 0 <= a["value"] <= 1