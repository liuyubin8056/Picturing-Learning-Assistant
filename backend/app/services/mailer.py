"""邮箱验证码发送：SMTP 直发 + 控制台兜底。

个人项目不需要短信商 —— QQ / 163 邮箱开 SMTP 拿授权码即可发信。
配置 MAIL_PROVIDER=smtp 走真实投递，=console 时只打日志（本地开发用）。

关于「容易被判垃圾邮件」：SMTP 直发受限于共享出口 IP 与域名信誉，
代码层能做的是让这封信「更像一封规范的事务邮件」——完整标准头
（Message-ID / Date / Reply-To）、纯文本 + HTML 双版本、无外链无图片、
明确品牌与用途、Auto-Submitted 标记。剩下的靠收件方白名单与专业 ESP，
详见 docs/邮件投递优化.md。
"""

import logging
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from ..config import get_settings

logger = logging.getLogger(__name__)

PURPOSE_LABEL = {"login": "登录", "reset": "重置密码", "bind": "绑定邮箱"}
# 验证码有效期（与 auth_code_ttl_seconds 保持一致，仅用于文案展示）
CODE_TTL_MINUTES = 5


class MailError(RuntimeError):
    """发信失败（配置缺失或 SMTP 异常）。"""


def mask_email(email: str) -> str:
    """脱敏展示：abcd@qq.com → ab***@qq.com"""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    head = local[:2] if len(local) > 2 else local[:1]
    return f"{head}***@{domain}"


def _html_body(label: str, code: str, brand: str) -> str:
    """HTML 正文。

    刻意不用任何外链图片、不用短链、不用花哨字体：
    图片与外链是垃圾邮件规则最爱扣分的地方。全表格布局保证 QQ / 163 /
    Gmail / Outlook 一致渲染，`color-scheme: light` 避免深色模式反色。
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{label}验证码</title>
</head>
<body style="margin:0;padding:0;background:#f4f6fb;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:#f4f6fb;padding:26px 12px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="max-width:480px;background:#ffffff;border-radius:16px;padding:30px 28px;
                  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',Arial,sans-serif;
                  color:#1f2430;line-height:1.7;">
      <tr><td>
        <div style="font-size:13px;font-weight:700;color:#4c6fff;letter-spacing:0.4px;">{brand}</div>
        <div style="font-size:19px;font-weight:700;margin:10px 0 6px;">{label}验证码</div>
        <div style="font-size:13.5px;color:#5b6479;">
          你正在{brand}进行<b>{label}</b>操作，请在页面中输入下面的验证码完成验证。
        </div>

        <div style="margin:20px 0 6px;padding:16px 0;text-align:center;background:#eff3ff;
                    border-radius:12px;font-size:30px;font-weight:700;letter-spacing:9px;
                    color:#3b5bdb;font-family:'SF Mono',Consolas,Menlo,monospace;">{code}</div>

        <div style="text-align:center;font-size:12.5px;color:#8a90a2;margin-bottom:20px;">
          验证码 {CODE_TTL_MINUTES} 分钟内有效，仅可使用一次
        </div>

        <div style="border-top:1px solid #eceff7;padding-top:16px;font-size:12.5px;color:#8a90a2;">
          <p style="margin:0 0 8px;">如果不是你本人操作，请忽略本邮件，你的账号不会发生任何变化。</p>
          <p style="margin:0 0 8px;">本邮件由系统自动发送，请勿直接回复。</p>
          <p style="margin:0;">若收件箱里找不到它，可能在「垃圾邮件 / 广告邮件」文件夹中；
             将该邮件标记为「不是垃圾邮件」，下次即可正常送达。</p>
        </div>
      </td></tr>
    </table>
    <div style="max-width:480px;margin:14px auto 0;font-size:11.5px;color:#a2a8b8;text-align:center;">
      此邮件由 {brand} 发出，用于账号身份验证
    </div>
  </td></tr>
</table>
</body>
</html>"""


def _text_body(label: str, code: str, brand: str) -> str:
    """纯文本正文。

    必须是「完整可读」的版本，而不是「请用 HTML 查看」——
    只有 HTML 没有等价纯文本，是最经典的垃圾邮件特征之一。
    """
    return (
        f"{brand}\n\n"
        f"你正在{brand}进行{label}操作。\n\n"
        f"验证码：{code}\n\n"
        f"验证码 {CODE_TTL_MINUTES} 分钟内有效，仅可使用一次。\n\n"
        f"如果不是你本人操作，请忽略本邮件，你的账号不会发生任何变化。\n"
        f"本邮件由系统自动发送，请勿直接回复。\n\n"
        f"若收件箱里找不到这封邮件，请检查「垃圾邮件 / 广告邮件」文件夹，\n"
        f"并将该邮件标记为「不是垃圾邮件」，下次即可正常送达。\n"
    )


def build_message(to: str, code: str, purpose: str = "login") -> EmailMessage:
    """构造验证码邮件（不发送，便于单测与复用）。

    标准头一个都不少：缺 Message-ID / Date 的邮件会被多数反垃圾规则扣分，
    而 `Auto-Submitted` 明确告诉收件方「这是自动生成的事务邮件」，
    可避免被当成营销群发，也能抑制「不在办公室」之类的自动回复。
    """
    s = get_settings()
    label = PURPOSE_LABEL.get(purpose, "验证")
    brand = s.mail_from_name

    msg = EmailMessage()
    # 直接用 str：EmailMessage（policy=default）会按 RFC 2047 自动编码中文主题；
    # 若传 email.header.Header 会报 "'Header' object is not subscriptable"
    msg["Subject"] = f"【{brand}】{label}验证码"
    msg["From"] = f"{brand} <{s.smtp_user}>"
    msg["To"] = to
    # 有回复地址的邮件信誉高于无回复地址的「死信箱」
    msg["Reply-To"] = f"{brand} <{s.smtp_user}>"
    msg["Date"] = formatdate(localtime=True)
    # Message-ID 必须用发信域名，不能落到 localhost/机器名——真实的域名后缀是可信信号
    domain = s.smtp_user.partition("@")[2] or None
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"

    msg.set_content(_text_body(label, code, brand))
    msg.add_alternative(_html_body(label, code, brand), subtype="html")
    return msg


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

    msg = build_message(to, code, purpose)

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
    # 只记脱敏地址与用途：便于统计投递量，也不把验证码写进生产日志
    logger.info("[MAIL-SENT] %s（%s）id=%s", mask_email(to), label, msg["Message-ID"])
    return True
