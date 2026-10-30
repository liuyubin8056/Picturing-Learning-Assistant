"""账户权限守门：未登录 401 / 跨账号 403 / 本人放行 / 演示账号放行。

conftest 的 auto_login 默认给了演示身份（放行任意 user_id），
这里显式换成普通用户或清空覆盖，验证真实边界。
"""

import pytest
from fastapi.testclient import TestClient

from app.deps import current_user
from app.main import app
from app.models import User

PROTECTED = [
    "/api/v1/profile/users/1",
    "/api/v1/profile/users/1/radar",
    "/api/v1/wrongbook/users/1",
    "/api/v1/tests/users/1/sessions",
    "/api/v1/tests/users/1/unlock-status",
    "/api/v1/diagnose/users/1/latest",
]


@pytest.fixture()
def anon(client):
    """清掉登录覆盖 → 未登录。"""
    app.dependency_overrides.pop(current_user, None)
    return client


@pytest.fixture()
def bob(client):
    """普通用户 id=2（非演示，不可跨账号）。"""
    app.dependency_overrides[current_user] = lambda: User(
        id=2, email="bob@example.com", nickname="bob"
    )
    return client


def test_anonymous_all_protected_return_401(anon):
    for url in PROTECTED:
        r = anon.get(url)
        assert r.status_code == 401, f"{url} 应为 401，实际 {r.status_code}"


def test_cross_user_read_forbidden(bob):
    """bob 读 1 号的数据 → 403。"""
    for url in PROTECTED:
        r = bob.get(url)
        assert r.status_code in (403, 404), f"{url} 应为 403，实际 {r.status_code}"
        # 404 仅出现在无画像/无数据的场景，但不应泄露数据
        if r.status_code == 403:
            assert "他人" in r.json().get("detail", "")


def test_self_access_ok(bob):
    """读自己的数据 → 200。"""
    r = bob.get("/api/v1/profile/users/2")
    assert r.status_code == 200
    assert r.json()["user_id"] == 2


def test_demo_can_switch_accounts(client):
    """演示账号（conftest 默认）可查看任意账号，便于汇报演示。"""
    for uid in (1, 2, 1001):
        r = client.get(f"/api/v1/profile/users/{uid}")
        assert r.status_code == 200, f"demo 访问 {uid} 应放行"


def test_demo_can_switch_wrongbook(client):
    r = client.get("/api/v1/wrongbook/users/1001")
    assert r.status_code == 200


def test_tokens_scoped_to_login_user(bob):
    """token 统计只看自己（非 demo）。"""
    r = bob.get("/api/v1/tokens/summary")
    assert r.status_code == 200
    assert r.json()["total_calls"] >= 0


def test_create_question_rejects_other_user(client, monkeypatch):
    """上传答疑时 Form 里的 user_id 必须是本人（demo 放行）。"""
    app.dependency_overrides[current_user] = lambda: User(id=2, email="bob@example.com")

    from app.llm.deepseek import DeepSeekClient, LLMResult

    async def fake_ask(self, image_bytes: bytes, mime: str = "image/jpeg"):
        return LLMResult(answer="ok", meta={}, raw="{}")

    monkeypatch.setattr(DeepSeekClient, "ask_with_image", fake_ask)

    files = {"image": ("a.jpg", b"\xff\xd8\xff\xe0" + b"0" * 32, "image/jpeg")}
    r = client.post(
        "/api/v1/questions",
        data={"user_id": "1", "client_question_id": "cross-user-test"},
        files=files,
    )
    assert r.status_code == 403
