"""验证码邮件构造测试。

重点不是「能不能发出去」，而是这封信是否具备「规范事务邮件」的形态：
标准头齐全（缺了会被反垃圾规则扣分）、纯文本 + HTML 双版本、HTML 里
没有外链与图片、Message-ID 落在真实域名上。这些是降低误判垃圾邮件的
代码层基础，改动时需要有回归保护。
"""

from app.services.mailer import build_message, mask_email


def test_headers_are_complete():
    msg = build_message("student@example.com", "123456", "login")
    assert "登录验证码" in msg["Subject"]
    assert msg["To"] == "student@example.com"
    assert msg["From"]                              # 发件人必须有
    assert msg["Reply-To"]                          # 无回复地址的邮件信誉更低
    assert msg["Date"]
    assert msg["Auto-Submitted"] == "auto-generated"


def test_message_id_uses_real_domain():
    """Message-ID 必须带发信域名，不能是 localhost / 机器名。"""
    msg = build_message("student@example.com", "123456", "login")
    mid = msg["Message-ID"]
    assert mid.startswith("<") and mid.endswith(">")
    domain = mid.strip("<>").rpartition("@")[2]
    assert domain and domain != "localhost"
    assert "." in domain


def test_multipart_has_text_and_html():
    msg = build_message("student@example.com", "123456", "login")
    assert msg.get_content_type() == "multipart/alternative"
    parts = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in parts and "text/html" in parts

    plain = msg.get_body(("plain",)).get_content()
    assert "123456" in plain
    assert "<html" not in plain.lower()      # 纯文本里不能夹 HTML

    html = msg.get_body(("html",)).get_content()
    assert "123456" in html


def test_html_has_no_remote_assets():
    """正文不能引用图片/外链脚本——这是垃圾邮件规则的高频扣分项。"""
    html = build_message("student@example.com", "123456", "login").get_body(("html",)).get_content()
    assert "<img" not in html.lower()
    assert "http://" not in html.lower() and "https://" not in html.lower()


def test_purpose_label_switches():
    msg = build_message("student@example.com", "654321", "reset")
    assert "重置密码" in msg["Subject"]
    assert "654321" in msg.get_body(("plain",)).get_content()


def test_mask_email():
    assert mask_email("2101388133@qq.com") == "21***@qq.com"
    assert mask_email("ab@qq.com") == "a***@qq.com"
    assert mask_email("not-an-email") == "***"
