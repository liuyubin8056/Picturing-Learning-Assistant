"""认证依赖：从 Cookie（Web）或 Authorization: Bearer（App）解析当前用户。

两端的差异见 docs/账户管理方案.md 决策 4：
- Web 用 httpOnly Cookie，防 XSS；
- App 用 Bearer + 系统安全存储（Keychain / Keystore），天然免 CSRF。
"""

from fastapi import Cookie, Depends, Header, HTTPException
from sqlmodel import Session

from .db import get_session
from .models import User
from .services import auth_service as auth

COOKIE_NAME = "spl_token"


def _extract(cookie: str | None, authorization: str | None) -> str | None:
    if cookie:
        return cookie
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def current_user(
    cookie: str | None = Cookie(None, alias=COOKIE_NAME),
    authorization: str | None = Header(None),
    session: Session = Depends(get_session),
) -> User:
    """必须登录。缺失或失效一律 401。"""
    token = _extract(cookie, authorization)
    if not token:
        raise HTTPException(
            status_code=401, detail="未登录", headers={"WWW-Authenticate": "Bearer"}
        )
    row = auth.lookup_token(session, token)
    if not row:
        raise HTTPException(
            status_code=401,
            detail="登录已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = session.get(User, row.user_id)
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="账号不可用")
    return user


async def optional_user(
    cookie: str | None = Cookie(None, alias=COOKIE_NAME),
    authorization: str | None = Header(None),
    session: Session = Depends(get_session),
) -> User | None:
    """登录了就返回用户，没登录返回 None（用于演示态兼容）。"""
    token = _extract(cookie, authorization)
    if not token:
        return None
    row = auth.lookup_token(session, token)
    if not row:
        return None
    user = session.get(User, row.user_id)
    if not user or user.status != "active":
        return None
    return user
