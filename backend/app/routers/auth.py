"""账户接口：邮箱验证码登录、密码登录、当前用户、退出、注销、演示登录。

两端凭证策略见 docs/账户管理方案.md 决策 4：
- X-Client: web（默认）→ 下发 httpOnly Cookie，响应体不含 token；
- X-Client: app        → 返回 token 由客户端存入 Keychain / Keystore，不设 Cookie。
"""

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_session
from ..deps import COOKIE_NAME, current_user
from ..services import export_service
from ..models import (
    AuthToken,
    DiagnosisReport,
    Mastery,
    ProfileMeta,
    Question,
    TestQuestion,
    TestSession,
    TokenUsage,
    User,
    WrongBook,
    utcnow,
)
from ..schemas import (
    CodeLoginIn,
    ImportIn,
    LoginOut,
    PasswordLoginIn,
    SendCodeIn,
    SendCodeOut,
    SetNicknameIn,
    SetPasswordIn,
    UserOut,
)
from ..services import auth_service as auth
from ..services import mailer

# 隐私政策版本：政策内容有实质变化时改这里，用户下次登录会补记新版本
CONSENT_VERSION = "2026-11"

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        email_masked=auth.mask_email(u.email) if u.email else None,
        nickname=u.nickname,
        is_demo=bool(u.is_demo),
        is_admin=bool(u.is_admin),
        consent_at=u.consent_at,
        created_at=u.created_at,
    )


def _set_auth_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=s.auth_token_days * 86400,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _client_kind(x_client: str | None) -> str:
    return "app" if (x_client or "").strip().lower() == "app" else "web"


def _login_response(
    session: Session,
    user: User,
    is_new: bool,
    response: Response,
    client: str,
    device: str | None,
) -> LoginOut:
    raw, expires = auth.issue_token(session, user.id, client, device=device)
    ttl = int((expires - utcnow()).total_seconds())
    if client == "web":
        _set_auth_cookie(response, raw)
        return LoginOut(user=_user_out(user), is_new=is_new)
    return LoginOut(user=_user_out(user), token=raw, expires_in=ttl, is_new=is_new)


# ---------------- 验证码 ----------------

@router.post("/email/send", response_model=SendCodeOut, summary="发送邮箱验证码")
async def send_email_code(
    payload: SendCodeIn,
    request: Request,
    session: Session = Depends(get_session),
):
    email = auth.normalize_email(payload.email)
    if not auth.is_valid_email(email):
        raise HTTPException(400, "邮箱格式不正确")

    ip = request.client.host if request.client else None
    try:
        code = auth.request_code(session, email, payload.purpose, ip=ip)
    except ValueError as exc:
        raise HTTPException(429, str(exc)) from exc

    try:
        delivered = await mailer.send_code(email, code, payload.purpose)
    except mailer.MailError as exc:
        raise HTTPException(503, f"邮件发送失败：{exc}") from exc

    s = get_settings()
    return SendCodeOut(
        sent=True,
        cooldown=s.auth_code_cooldown,
        hint="验证码已发出，若 1 分钟内未收到请检查垃圾邮件",
        # console 模式（本地开发）回显，方便不联网联调；生产走 smtp 时为 None
        debug_code=None if delivered else code,
    )


@router.post("/email/login", response_model=LoginOut, summary="验证码登录（首次自动注册）")
def login_by_code(
    payload: CodeLoginIn,
    request: Request,
    response: Response,
    x_client: str | None = Header(None),
    session: Session = Depends(get_session),
):
    email = auth.normalize_email(payload.email)
    try:
        auth.verify_code(session, email, payload.code)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc

    # 合规：新建账号必须先同意隐私政策；老账号不阻塞，下次登录时补记
    existing = auth.get_user_by_email(session, email)
    if existing is None and not payload.consent:
        raise HTTPException(400, "首次登录需要先阅读并同意《隐私政策与用户协议》")

    user, is_new = auth.get_or_create_user(session, email)
    if user.status != "active":
        raise HTTPException(403, "账号已被停用")

    if payload.consent and not user.consent_at:
        user.consent_at = utcnow()
        user.consent_version = CONSENT_VERSION
        session.add(user)
        session.commit()
        session.refresh(user)

    return _login_response(
        session, user, is_new, response,
        _client_kind(x_client), request.headers.get("user-agent"),
    )


# ---------------- 密码 ----------------

@router.post("/password/login", response_model=LoginOut, summary="密码登录")
def login_by_password(
    payload: PasswordLoginIn,
    request: Request,
    response: Response,
    x_client: str | None = Header(None),
    session: Session = Depends(get_session),
):
    email = auth.normalize_email(payload.email)
    user = auth.get_user_by_email(session, email)
    if not user or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "邮箱或密码不正确")
    if user.status != "active":
        raise HTTPException(403, "账号已被停用")
    user.last_login_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)
    return _login_response(
        session, user, False, response,
        _client_kind(x_client), request.headers.get("user-agent"),
    )


@router.post("/password", summary="设置或修改密码（需登录）")
def set_password(
    payload: SetPasswordIn,
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    pwd = payload.password or ""
    if len(pwd) < 6:
        raise HTTPException(400, "密码至少 6 位")
    if len(pwd) > 128:
        raise HTTPException(400, "密码过长")
    me.password_hash = auth.hash_password(pwd)
    session.add(me)
    session.commit()
    return {"ok": True}


# ---------------- 当前用户 ----------------

@router.get("/me", response_model=UserOut, summary="当前登录用户")
def get_me(me: User = Depends(current_user)):
    return _user_out(me)


@router.put("/me/nickname", response_model=UserOut, summary="设置昵称")
def set_nickname(
    payload: SetNicknameIn,
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    name = (payload.nickname or "").strip()
    if not name:
        raise HTTPException(400, "昵称不能为空")
    if len(name) > 20:
        raise HTTPException(400, "昵称最多 20 个字符")
    me.nickname = name
    session.add(me)
    session.commit()
    session.refresh(me)
    return _user_out(me)


# ---------------- 令牌生命周期 ----------------

@router.post("/refresh", summary="续期（App 端滑动续期）")
def refresh(
    request: Request,
    response: Response,
    x_client: str | None = Header(None),
    session: Session = Depends(get_session),
):
    from ..deps import _extract  # 复用同一套"Cookie 或 Bearer"解析

    token = _extract(request.cookies.get(COOKIE_NAME), request.headers.get("authorization"))
    row = auth.lookup_token(session, token) if token else None
    if not row:
        raise HTTPException(401, "登录已失效，请重新登录")
    user = session.get(User, row.user_id)
    if not user:
        raise HTTPException(401, "账号不存在")
    auth.revoke_token(session, token)                 # 换新令牌，旧的立即作废
    return _login_response(
        session, user, False, response,
        _client_kind(x_client), request.headers.get("user-agent"),
    )


@router.post("/logout", summary="退出登录（撤销当前令牌）")
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    from ..deps import _extract

    token = _extract(request.cookies.get(COOKIE_NAME), request.headers.get("authorization"))
    if token:
        auth.revoke_token(session, token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/logout-all", summary="退出所有设备")
def logout_all(
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    n = auth.revoke_all_tokens(session, me.id)
    return {"ok": True, "revoked": n}


# ---------------- 演示账号 ----------------

@router.post("/demo-login", response_model=LoginOut, summary="演示账号免登录（仅演示环境）")
def demo_login(
    request: Request,
    response: Response,
    x_client: str | None = Header(None),
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    """进入演示账号：**必须已登录且是管理员**。

    原先这里是无鉴权的"一键进入"，等于把演示账号当后门（它能看到所有用户数据）。
    现在改成管理员专属，普通用户只能用邮箱验证码登录自己的账号。
    """
    s = get_settings()
    if not s.allow_demo_login:
        raise HTTPException(403, "演示登录已关闭")
    if not me.is_admin:
        raise HTTPException(403, "仅管理员可进入演示账号")
    demo = session.get(User, 1001)
    if not demo:
        raise HTTPException(404, "演示账号不存在（先运行种子脚本）")
    return _login_response(
        session, demo, False, response,
        _client_kind(x_client), request.headers.get("user-agent"),
    )


# ---------------- 注销账号 ----------------

@router.delete("/account", summary="注销账号并清除学习数据")
def delete_account(
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    if me.is_demo:
        raise HTTPException(400, "演示账号不可注销")

    uid = me.id
    # 级联清理学习数据（业务表都以 user_id 关联）
    for model in (Question, Mastery, WrongBook, DiagnosisReport, TokenUsage):
        for row in session.exec(select(model).where(model.user_id == uid)).all():
            session.delete(row)
    for ts in session.exec(select(TestSession).where(TestSession.user_id == uid)).all():
        for tq in session.exec(
            select(TestQuestion).where(TestQuestion.session_id == ts.id)
        ).all():
            session.delete(tq)
        session.delete(ts)
    pm = session.get(ProfileMeta, uid)
    if pm:
        session.delete(pm)
    for tok in session.exec(select(AuthToken).where(AuthToken.user_id == uid)).all():
        session.delete(tok)

    # 画像 md 存档
    try:
        from ..config import BASE_DIR

        md = BASE_DIR / "profiles" / f"{uid}.md"
        if md.exists():
            md.unlink()
    except OSError:
        pass

    # 软删除用户本身：邮箱置空释放唯一约束，便于同一邮箱重新注册
    me.status = "deleted"
    me.email = None
    me.nickname = None
    me.password_hash = None
    session.add(me)
    session.commit()
    return {"ok": True}


# ---------------- 数据导出 ----------------

@router.get("/export", summary="导出我的全部学习数据（JSON 下载）")
def export_my_data(
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    """合规用：用户随时可以把自己的数据带走。

    只含本人数据，不含题库；不含密码哈希、登录令牌、验证码。
    与 DELETE /account 构成「可导出 + 可注销」的闭环。
    """
    data = export_service.export_user_data(session, me)
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    filename = export_service.suggest_filename(me)
    # 中文文件名不能直接放 HTTP 头（头字段只允许 latin-1），必须 RFC 5987 编码；
    # 同时给一个 ASCII 兜底名，老浏览器读不到 filename* 时也不会存成乱码。
    from urllib.parse import quote

    ascii_name = f"learnmate-{me.id}.json"
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; '
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


# ---------------- 数据导入 ----------------

@router.post("/import", summary="导入学习数据（可合并或覆盖）")
def import_my_data(
    payload: ImportIn,
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    """把导出的 JSON 导回账号。

    merge  ：掌握度取较高分、错题累加、答疑按幂等 ID 去重、练习按标题去重
    replace：先清空本人学习数据再恢复（账户本身不会删）
    """
    mode = payload.mode if payload.mode in ("merge", "replace") else "merge"
    try:
        result = export_service.import_user_data(session, me, payload.data, mode)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return result
