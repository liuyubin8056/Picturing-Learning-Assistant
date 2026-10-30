"""邮箱验证码发送：SMTP 直发 + 控制台兜底。

个人项目不需要短信商 —— QQ / 163 邮箱开 SMTP 拿授权码即可发信。
配置 MAIL_PROVIDER=smtp 走真实投递，=console 时只打日志（本地开发用）。
"""

import logging
from email.message import EmailMessage

from ..config import get_settings

logger = logging.getLogger(__name__)

PURPOSE_LABEL = {"login": "登录", "reset": "重置密码", "bind": "绑定邮箱"}


class MailError(RuntimeError):
    """发信失败（配置缺失或 SMTP 异常）。"""


def mask_email(email: str) -> str:
    """脱敏展示：abcd@qq.com → ab***@qq.com"""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    head = local[:2] if len(local) > 2 else local[:1]
    return f"{head}***@{domain}"


async def send_code(to: str, code: str, purpose: str = "login") -> bool:
    """发送验证码。

    返回 True 表示经 SMTP 真实投递，False 表示 console 模式（只写日志）。
    """
    s = get_settings()
    label = PURPOSE_LABEL.get(purpose, "验证")

    if s.mail_provider != "smtp":
        logger.warning("[MAIL-CONSOLE] %s -> %s（%s）", mask_email(to), code, label)
        return False

    if not (s.smtp_user.strip() and s.smtp_pass.strip()):
        raise MailError("未配置 SMTP_USER / SMTP_PASS（邮箱授权码）")

    try:
        import aiosmtplib
    except ImportError as exc:  # pragma: no cover
        raise MailError("缺少 aiosmtplib，请执行 pip install aiosmtplib") from exc

    msg = EmailMessage()
    # 直接用 str：EmailMessage（policy=default）会按 RFC 2047 自动编码中文主题；
    # 若传 email.header.Header 会报 "'Header' object is not subscriptable"
    msg["Subject"] = f"【智能拍照学习助手】{label}验证码"
    msg["From"] = f"{s.mail_from_name} <{s.smtp_user}>"
    msg["To"] = to
    msg.set_content(
        f"你的{label}验证码是：{code}\n\n"
        f"5 分钟内有效，用完即失效。\n"
        f"如果不是你本人操作，请忽略本邮件。\n"
    )

    try:
        await aiosmtplib.send(
            msg,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_user,
            password=s.smtp_pass,
            use_tls=True,
            timeout=20,
        )
    except Exception as exc:
        raise MailError(f"发信失败：{exc}") from exc
    return True
