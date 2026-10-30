"""账户体系：邮箱验证码、令牌签发/校验、密码哈希。

设计要点（见 docs/账户管理方案.md）：
- 令牌是数据库里的 opaque token（存 sha256），能立即撤销、能踢设备；不用 JWT。
- 验证码只存 sha256；5 分钟有效、用后即废、错误 5 次作废。
- 邮箱统一规范化（小写、去 + 别名），避免同一人注册成两个号。
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ..config import get_settings
from ..models import AuthToken, User, VerificationCode

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 这些域名的 + 别名指向同一收件箱，统一去掉避免重复注册
ALIAS_DOMAINS = {"gmail.com", "qq.com", "163.com", "126.com", "foxmail.com"}

DAILY_CODE_LIMIT = 10        # 单邮箱每日发码上限
IP_HOURLY_LIMIT = 20         # 单 IP 每小时上限
MAX_CODE_ATTEMPTS = 5        # 单条验证码最多试错次数
PBKDF2_ITER = 200_000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    """SQLite 读出的 datetime 可能丢时区，统一按 UTC 处理。"""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------- 邮箱 ----------

def normalize_email(raw: str) -> str:
    e = (raw or "").strip().lower()
    local, _, domain = e.partition("@")
    if domain in ALIAS_DOMAINS:
        local = local.split("+")[0]
    return f"{local}@{domain}"


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or "")) and len(email) <= 254


def mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    head = local[:2] if len(local) > 2 else local[:1]
    return f"{head}***@{domain}"


# ---------- 哈希 ----------

def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_code(code: str) -> str:
    return _sha256(code)


def hash_token(token: str) -> str:
    return _sha256(token)


def hash_password(raw: str) -> str:
    """pbkdf2_sha256（标准库，无需额外依赖）。格式：pbkdf2$迭代$盐$哈希"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt.encode(), PBKDF2_ITER)
    return f"pbkdf2${PBKDF2_ITER}${salt}${dk.hex()}"


def verify_password(raw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iter_s, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt.encode(), int(iter_s))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


# ---------- 验证码 ----------

def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def request_code(
    session: Session, email: str, purpose: str = "login", ip: str | None = None
) -> str:
    """生成并登记一条验证码，返回明文（由调用方发送）。

    超频时抛 ValueError（信息给前端直接展示）。
    """
    now = utcnow()
    cooldown = get_settings().auth_code_cooldown

    latest = session.exec(
        select(VerificationCode)
        .where(VerificationCode.email == email)
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    ).first()
    if latest:
        last = _as_aware(latest.created_at)
        if last and (now - last).total_seconds() < cooldown:
            wait = int(cooldown - (now - last).total_seconds())
            raise ValueError(f"请求过于频繁，请 {max(wait, 1)} 秒后再试")

    today_start = now - timedelta(days=1)
    sent_today = len(
        session.exec(
            select(VerificationCode).where(
                VerificationCode.email == email,
                VerificationCode.created_at >= today_start,
            )
        ).all()
    )
    if sent_today >= DAILY_CODE_LIMIT:
        raise ValueError("今日验证码发送次数已达上限，请明天再试")

    if ip:
        hour_ago = now - timedelta(hours=1)
        ip_count = len(
            session.exec(
                select(VerificationCode).where(
                    VerificationCode.ip == ip,
                    VerificationCode.created_at >= hour_ago,
                )
            ).all()
        )
        if ip_count >= IP_HOURLY_LIMIT:
            raise ValueError("当前网络请求过于频繁，请稍后再试")

    # 旧的未用验证码统一作废，避免多条并存
    for old in session.exec(
        select(VerificationCode).where(
            VerificationCode.email == email, VerificationCode.used == False  # noqa: E712
        )
    ).all():
        old.used = True
        session.add(old)

    code = generate_code()
    session.add(
        VerificationCode(
            email=email,
            code_hash=hash_code(code),
            purpose=purpose,
            expires_at=now + timedelta(seconds=get_settings().auth_code_ttl_seconds),
            ip=ip,
        )
    )
    session.commit()
    return code


def verify_code(session: Session, email: str, code: str) -> None:
    """校验验证码；失败抛 ValueError。通过后标记为已用。"""
    code = (code or "").strip()
    if not code:
        raise ValueError("请输入验证码")

    row = session.exec(
        select(VerificationCode)
        .where(
            VerificationCode.email == email,
            VerificationCode.used == False,  # noqa: E712
        )
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    ).first()
    if not row:
        raise ValueError("验证码已失效，请重新获取")

    if _as_aware(row.expires_at) < utcnow():
        row.used = True
        session.add(row)
        session.commit()
        raise ValueError("验证码已过期，请重新获取")

    if row.attempts >= MAX_CODE_ATTEMPTS:
        row.used = True
        session.add(row)
        session.commit()
        raise ValueError("尝试次数过多，请重新获取验证码")

    if not hmac.compare_digest(row.code_hash, hash_code(code)):
        row.attempts += 1
        session.add(row)
        session.commit()
        left = MAX_CODE_ATTEMPTS - row.attempts
        raise ValueError(f"验证码不正确，还可尝试 {max(left, 0)} 次")

    row.used = True
    session.add(row)
    session.commit()


# ---------- 用户 ----------

def get_user_by_email(session: Session, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email)).first()


def get_or_create_user(session: Session, email: str) -> tuple[User, bool]:
    """验证码通过后调用：没有就建号（首次登录自动注册）。

    昵称留空，由前端首次登录后引导用户自己填。
    """
    user = get_user_by_email(session, email)
    if user:
        user.last_login_at = utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        return user, False

    user = User(email=email, last_login_at=utcnow())
    session.add(user)
    session.commit()
    session.refresh(user)
    return user, True


# ---------- 令牌 ----------

def issue_token(
    session: Session, user_id: int, client: str = "web", device: str | None = None
) -> tuple[str, datetime]:
    """签发令牌，返回 (明文, 过期时间)。明文只在此时出现一次。"""
    raw = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(days=get_settings().auth_token_days)
    session.add(
        AuthToken(
            token_hash=hash_token(raw),
            user_id=user_id,
            client=client if client in {"web", "app"} else "web",
            expires_at=expires,
            device=(device or "")[:200] or None,
        )
    )
    session.commit()
    return raw, expires


def lookup_token(session: Session, raw: str) -> AuthToken | None:
    """校验令牌：存在、未撤销、未过期；顺手更新 last_seen_at（滑动续期用）。"""
    if not raw:
        return None
    row = session.exec(
        select(AuthToken).where(AuthToken.token_hash == hash_token(raw))
    ).first()
    if not row or row.revoked_at is not None:
        return None
    if _as_aware(row.expires_at) < utcnow():
        return None
    row.last_seen_at = utcnow()
    session.add(row)
    session.commit()
    return row


def revoke_token(session: Session, raw: str) -> None:
    row = session.exec(
        select(AuthToken).where(AuthToken.token_hash == hash_token(raw))
    ).first()
    if row:
        row.revoked_at = utcnow()
        session.add(row)
        session.commit()


def revoke_all_tokens(session: Session, user_id: int) -> int:
    rows = session.exec(
        select(AuthToken).where(
            AuthToken.user_id == user_id, AuthToken.revoked_at == None  # noqa: E712
        )
    ).all()
    for row in rows:
        row.revoked_at = utcnow()
        session.add(row)
    session.commit()
    return len(rows)
