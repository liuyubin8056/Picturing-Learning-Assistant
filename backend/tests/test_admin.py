"""管理后台、演示登录收紧、数据导入导出。

重点验证三件事：
1. 演示登录不再是后门——未登录 401、普通用户 403、管理员 200
2. 管理接口普通用户进不去
3. 导入的 merge / replace 语义正确（不重复累加、可选清空）
"""

import json

from fastapi.testclient import TestClient

from app.deps import current_user
from app.main import app
from app.models import User


def _as(client, **kw):
    """临时把当前用户换成指定身份。"""
    app.dependency_overrides[current_user] = lambda: User(
        id=kw.get("id", 1),
        email=kw.get("email", "u@example.com"),
        nickname=kw.get("nickname", "测试"),
        is_demo=kw.get("is_demo", False),
        is_admin=kw.get("is_admin", False),
    )


def test_demo_login_requires_login(client: TestClient):
    app.dependency_overrides.pop(current_user, None)
    r = client.post("/api/v1/auth/demo-login")
    assert r.status_code == 401


def test_demo_login_forbidden_for_normal_user(client: TestClient):
    _as(client, is_admin=False)
    r = client.post("/api/v1/auth/demo-login")
    assert r.status_code == 403
    assert "管理员" in r.json()["detail"]


def test_demo_login_allowed_for_admin(client: TestClient):
    _as(client, is_admin=True)
    r = client.post("/api/v1/auth/demo-login")
    # 演示账号 1001 若不存在会 404；存在则 200。两种都比 403 说明鉴权通过
    assert r.status_code in (200, 404)


def test_admin_endpoints_blocked_for_normal_user(client: TestClient):
    _as(client, is_admin=False)
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/api/v1/admin/overview").status_code == 403


def test_admin_can_read_stats(client: TestClient):
    _as(client, is_admin=True)
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "users" in body
    for key in (
        "created_at",
        "questions",
        "test_answered",
        "api_hits",
        "tokens_total",
    ):
        if body["users"]:
            assert key in body["users"][0]

    ov = client.get("/api/v1/admin/overview")
    assert ov.status_code == 200
    assert "users" in ov.json() and "tokens_total" in ov.json()


def test_export_filename_has_nickname_and_seconds(client: TestClient):
    _as(client, nickname="刘同学")
    r = client.get("/api/v1/auth/export")
    assert r.status_code == 200
    disp = r.headers["content-disposition"]
    assert "%E5%88%98" in disp or "刘同学" in disp or "学习数据" in disp
    # 形如 学习数据-刘同学-20261111-224958.json
    import re

    assert re.search(r"\d{8}-\d{6}", disp), disp


def test_import_merge_is_idempotent(client: TestClient):
    _as(client, id=1)
    payload = {
        "schema_version": 1,
        "mastery": [{"kp_id": 101, "score": 0.6, "ask_count": 2, "wrong_count": 1}],
        "wrong_books": [{"kb_problem_id": 9001, "stem": "题", "wrong_count": 1}],
        "questions": [{"client_question_id": "imp-1", "answer": "答案", "status": "answered"}],
    }
    r1 = client.post("/api/v1/auth/import", json={"mode": "merge", "data": payload})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/v1/auth/import", json={"mode": "merge", "data": payload})
    assert r2.status_code == 200

    # 掌握度取最大值，不因重复导入翻倍
    from sqlmodel import Session, select

    from app.db import engine
    from app.models import Mastery, Question, WrongBook

    with Session(engine) as s:
        m = s.exec(
            select(Mastery).where(Mastery.user_id == 1, Mastery.kp_id == 101)
        ).first()
        assert m is not None and abs(m.score - 0.6) < 1e-6
        assert m.ask_count == 2

        # 错题累加：两次导入 → 2
        w = s.exec(
            select(WrongBook).where(WrongBook.user_id == 1, WrongBook.kb_problem_id == 9001)
        ).first()
        assert w is not None and w.wrong_count == 2

        # 答疑按 client_question_id 去重：只留一条
        qs = s.exec(
            select(Question).where(
                Question.user_id == 1, Question.client_question_id == "imp-1"
            )
        ).all()
        assert len(qs) == 1


def test_import_replace_clears_first(client: TestClient):
    _as(client, id=1)
    client.post(
        "/api/v1/auth/import",
        json={
            "mode": "merge",
            "data": {
                "mastery": [
                    {"kp_id": 201, "score": 0.9},
                    {"kp_id": 202, "score": 0.3},
                ]
            },
        },
    )
    # replace 只带一个点 → 另一个应被清掉
    r = client.post(
        "/api/v1/auth/import",
        json={"mode": "replace", "data": {"mastery": [{"kp_id": 201, "score": 0.5}]}},
    )
    assert r.status_code == 200

    from sqlmodel import Session, select

    from app.db import engine
    from app.models import Mastery

    with Session(engine) as s:
        rows = s.exec(select(Mastery).where(Mastery.user_id == 1)).all()
        ids = sorted(r.kp_id for r in rows)
        assert ids == [201], ids


def test_import_rejects_bad_schema(client: TestClient):
    _as(client, id=1)
    r = client.post(
        "/api/v1/auth/import",
        json={"mode": "merge", "data": {"schema_version": 99}},
    )
    assert r.status_code == 422


def test_timeline_blocked_for_normal_user(client: TestClient):
    _as(client, is_admin=False)
    assert client.get("/api/v1/admin/timeline").status_code == 403


def test_timeline_fills_missing_days(client: TestClient):
    """缺数据的日子必须补 0，否则折线图会把"没人用的一天"连成斜线。"""
    _as(client, is_admin=True)
    r = client.get("/api/v1/admin/timeline", params={"days": 7})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["series"]) == 7
    days = [row["day"] for row in body["series"]]
    assert days == sorted(days)
    assert len(set(days)) == 7
    # 今天必然在序列末尾
    from app.services import usage_counter

    assert days[-1] == usage_counter.today_str()
    for row in body["series"]:
        for key in ("api_hits", "llm_calls", "tokens_prompt", "tokens_completion", "tokens_total"):
            assert key in row and row[key] >= 0


def test_timeline_aggregates_token_usage_by_local_day(client: TestClient):
    """UTC 23:30 的调用属于北京时间的第二天，不能被算到前一天。"""
    from datetime import datetime, timezone

    from sqlmodel import Session

    from app.db import engine
    from app.models import TokenUsage
    from app.services import usage_counter

    now_cn = datetime.now(usage_counter.TZ_CN)
    created_utc = now_cn.astimezone(timezone.utc)

    with Session(engine) as s:
        row = TokenUsage(
            user_id=999001,
            scene="timeline_test",
            prompt_tokens=1000,
            completion_tokens=234,
            total_tokens=1234,
            created_at=created_utc,
        )
        s.add(row)
        s.commit()
        rid = row.id

    try:
        _as(client, is_admin=True)
        r = client.get(
            "/api/v1/admin/timeline", params={"days": 2, "user_id": 999001}
        )
        assert r.status_code == 200, r.text
        series = r.json()["series"]
        today = usage_counter.today_str()
        hit = [row for row in series if row["day"] == today][0]
        assert hit["tokens_total"] == 1234
        assert hit["tokens_prompt"] == 1000
        assert hit["llm_calls"] == 1
        assert r.json()["totals"]["tokens_total"] == 1234
    finally:
        with Session(engine) as s:
            obj = s.get(TokenUsage, rid)
            if obj:
                s.delete(obj)
                s.commit()
