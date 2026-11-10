"""认证依赖：从 Cookie（Web）或 Authorization: Bearer（App）解析当前用户。

两端的差异见 docs/账户管理方案.md 决策 4：
- Web 用 httpOnly Cookie，防 XSS；
- App 用 Bearer + 系统安全存储（Keychain / Keystore），天然免 CSRF。
"""

from fastapi import Cookie, Depends, Header, HTTPException
from sqlmodel import Session

from .config import get_settings
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


def ensure_self(user_id: int, me: User = Depends(current_user)) -> int:
    """校验路径里的 user_id，返回**有权操作的 user_id**。

    用法：把接口签名里的 `user_id: int` 换成 `uid: int = Depends(ensure_self)`，
    函数体用 uid。路径不变，前端无需改动。

    演示账号只有开了 ALLOW_DEMO_CROSS_ACCESS 才能看别人的数据（汇报切换用），
    否则和普通账号一样只能看自己 —— 避免"有个 demo 账号就等于全站可读"。
    """
    if user_id == me.id:
        return user_id
    if me.is_demo and get_settings().allow_demo_cross_access:
        return user_id
    raise HTTPException(status_code=403, detail="无权访问他人数据")


def ensure_owner(user_id: int | None, me: User) -> int:
    """用于 Form / 请求体里自报 user_id 的接口：缺省取自己，给了就必须是自己。"""
    if user_id is None or user_id == me.id:
        return me.id
    if me.is_demo and get_settings().allow_demo_cross_access:
        return user_id
    raise HTTPException(status_code=403, detail="无权操作他人数据")
