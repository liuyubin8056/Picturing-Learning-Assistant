"""限流中间件测试：确认烧钱接口真的会被拦，且不误伤静态资源。

注意：中间件是 app 级单例，计数会跨用例累积，所以每个用例用不同的
X-Real-IP 隔离，避免互相干扰。
"""

from app.config import get_settings

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100ffff03000006000557bfabd40000000049454e44ae426082"
)


def _ask(client, ip: str, cid: str):
    return client.post(
        "/api/v1/questions",
        files={"image": ("a.png", PNG_BYTES, "image/png")},
        data={"user_id": "1", "client_question_id": cid},
        headers={"X-Real-IP": ip},
    )


def _with_rate_limit():
    s = get_settings()
    prev = s.rate_limit_enabled
    s.rate_limit_enabled = True
    return s, prev


def test_questions_rate_limited_per_ip(client):
    """同一 IP 第 7 次答疑应被拦（规则：6 次 / 60 秒）。"""
    settings, prev = _with_rate_limit()
    try:
        codes = [_ask(client, "10.0.0.1", f"rl-{i}").status_code for i in range(7)]
        assert codes[:6] != [429] * 6, f"前 6 次不该限流，实际 {codes}"
        assert codes[6] == 429, f"第 7 次应 429，实际 {codes}"
    finally:
        settings.rate_limit_enabled = prev


def test_rate_limit_is_per_ip(client):
    """换 IP 不受影响。"""
    settings, prev = _with_rate_limit()
    try:
        for i in range(6):
            _ask(client, "10.0.0.2", f"rl-a-{i}")
        assert _ask(client, "10.0.0.2", "rl-a-6").status_code == 429
        # 另一个 IP 第一次请求应正常放行（不是 429）
        assert _ask(client, "10.0.0.3", "rl-b-0").status_code != 429
    finally:
        settings.rate_limit_enabled = prev


def test_429_has_retry_after_and_request_id(client):
    settings, prev = _with_rate_limit()
    try:
        for i in range(6):
            _ask(client, "10.0.0.4", f"rl-c-{i}")
        r = _ask(client, "10.0.0.4", "rl-c-6")
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        body = r.json()
        assert body["retry_after"] > 0
        assert body["request_id"]
        assert r.headers.get("X-Request-ID")
    finally:
        settings.rate_limit_enabled = prev


def test_static_and_health_not_limited(client):
    """静态资源与健康检查不计入限流（页面一次加载十几个资源会被误判）。"""
    settings, prev = _with_rate_limit()
    try:
        ip = {"X-Real-IP": "10.0.0.5"}
        for _ in range(50):
            assert client.get("/api/v1/health", headers=ip).status_code == 200
    finally:
        settings.rate_limit_enabled = prev


def test_request_id_present_on_normal_response(client):
    """每个响应都带 X-Request-ID，便于按 ID 查日志。"""
    r = client.get("/api/v1/health")
    assert r.headers.get("X-Request-ID")


def test_validation_error_is_readable(client):
    """422 不再是 [{loc,msg}] 数组，而是一句人话。"""
    r = client.post(
        "/api/v1/questions", files={"image": ("a.png", PNG_BYTES, "image/png")}
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str) and detail, f"期望字符串，实际 {detail!r}"
