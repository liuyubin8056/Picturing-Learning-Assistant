"""隐私政策同意与数据导出的测试。

覆盖两条合规底线：
1. 新建账号必须先同意（老账号不阻塞，下次登录补记）
2. 用户能把自己的数据完整导出
"""

from sqlmodel import Session

from app.config import get_settings
from app.db import engine
from app.services import auth_service as auth


def _code(email: str) -> str:
    """取一条验证码。测试里把 60 秒冷却关掉，否则同一邮箱第二次取码会失败。"""
    s = get_settings()
    prev = s.auth_code_cooldown
    s.auth_code_cooldown = 0
    try:
        with Session(engine) as sess:
            return auth.request_code(sess, email, "login")
    finally:
        s.auth_code_cooldown = prev


def test_first_login_requires_consent(client):
    """新邮箱不带 consent → 400，且不会建出账号。"""
    email = "newbie@example.com"
    code = _code(email)

    r = client.post(
        "/api/v1/auth/email/login",
        json={"email": email, "code": code, "consent": False},
    )
    assert r.status_code == 400
    assert "隐私政策" in r.json()["detail"]

    with Session(engine) as s:
        assert auth.get_user_by_email(s, email) is None


def test_first_login_with_consent_records_timestamp(client):
    email = "newbie2@example.com"
    code = _code(email)

    r = client.post(
        "/api/v1/auth/email/login",
        json={"email": email, "code": code, "consent": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_new"] is True
    assert body["user"]["consent_at"], "应记录同意时间"


def test_existing_user_login_not_blocked(client):
    """老账号（已存在）不带 consent 也能登录 —— 不因为加了这个功能把人挡在外面。"""
    email = "old@example.com"
    code = _code(email)
    r1 = client.post(
        "/api/v1/auth/email/login",
        json={"email": email, "code": code, "consent": True},
    )
    assert r1.status_code == 200

    code2 = _code(email)
    r2 = client.post(
        "/api/v1/auth/email/login",
        json={"email": email, "code": code2, "consent": False},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json().get("is_new") is False


def test_export_returns_downloadable_json(client):
    r = client.get("/api/v1/auth/export")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.json()
    assert body["schema_version"] == 1
    for key in ("account", "summary", "questions", "test_sessions", "wrong_books", "mastery"):
        assert key in body, f"导出缺少字段 {key}"
    # 凭证类绝不能出现
    assert "password_hash" not in r.text
