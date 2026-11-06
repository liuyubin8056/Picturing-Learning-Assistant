"""拍照答疑全链路接口测试（LLM mock，不依赖外网）。"""

from sqlmodel import Session, select

from app.db import engine
from app.models import Question

# 合法的 1x1 PNG
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _post(client, cid, user_id=1, ext=".png", data=None):
    return client.post(
        "/api/v1/questions",
        files={"image": (f"photo{ext}", data or PNG_BYTES, "image/png")},
        data={"user_id": str(user_id), "client_question_id": cid},
    )


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm_configured"] is False  # 测试环境强制未配置


def test_root(client):
    assert client.get("/").status_code == 200


def test_submit_and_idempotent(client, mock_llm):
    r = _post(client, "cid-001")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answered"
    assert body["answer"]
    assert body["meta"]["chapter"] == "二次函数"
    assert body["meta"]["profile_delta"]["confusion"]
    assert body["duplicated"] is False
    assert body["image_url"].startswith("/uploads/")
    qid = body["id"]

    # 同一幂等 ID 重复提交 → 返回已有记录
    r2 = _post(client, "cid-001")
    assert r2.status_code == 200
    assert r2.json()["duplicated"] is True
    assert r2.json()["id"] == qid

    # 不同幂等 ID → 新记录
    r3 = _post(client, "cid-002")
    assert r3.json()["duplicated"] is False
    assert r3.json()["id"] != qid


def test_invalid_extension(client, mock_llm):
    r = _post(client, "cid-gif", ext=".gif")
    assert r.status_code == 422


def test_missing_fields(client):
    r = client.post(
        "/api/v1/questions", files={"image": ("a.png", PNG_BYTES, "image/png")}
    )
    assert r.status_code == 422


def test_llm_not_configured_then_retry(client, monkeypatch):
    # 未配置 API Key → 503，且记录落库为 failed
    r = _post(client, "cid-key")
    assert r.status_code == 503
    with Session(engine) as s:
        q = s.exec(
            select(Question).where(Question.client_question_id == "cid-key")
        ).one()
        assert q.status == "failed"
        assert q.image_path  # 图片已保存，重试时复用

    # 配置好后凭同一 ID 重试 → 复用记录并成功
    from app.llm.deepseek import DeepSeekClient, LLMResult

    async def fake(self, image_bytes, mime="image/jpeg"):
        return LLMResult(answer="重试成功", meta=None, raw="重试成功")

    monkeypatch.setattr(DeepSeekClient, "ask_with_image", fake)
    r2 = _post(client, "cid-key")
    assert r2.status_code == 200
    assert r2.json()["status"] == "answered"
    assert r2.json()["answer"] == "重试成功"
    assert r2.json()["duplicated"] is False  # failed 重试不算幂等命中


def test_get_and_list(client, mock_llm):
    _post(client, "cid-a", user_id=7)
    _post(client, "cid-b", user_id=7)

    r = client.get("/api/v1/users/7/questions")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert items[0]["client_question_id"] == "cid-b"  # 倒序

    qid = items[0]["id"]
    r2 = client.get(f"/api/v1/questions/{qid}")
    assert r2.status_code == 200
    assert r2.json()["image_url"].startswith("/uploads/")

    assert client.get("/api/v1/questions/99999").status_code == 404


def test_list_pagination(client, mock_llm):
    for i in range(5):
        _post(client, f"cid-p{i}", user_id=9)
    r = client.get("/api/v1/users/9/questions?limit=2&offset=0")
    assert len(r.json()) == 2
    r2 = client.get("/api/v1/users/9/questions?limit=2&offset=4")
    assert len(r2.json()) == 1
