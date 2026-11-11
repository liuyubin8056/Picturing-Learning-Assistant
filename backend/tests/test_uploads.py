"""分片上传（断点续传）接口测试。

覆盖真实故障形态：网络中断、重传同一片、乱序、缺片、越界、他人 upload_id。
"""

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _pad(n: int) -> bytes:
    """构造恰好 n 字节的假图片数据（分片大小必须严格匹配）。"""
    return (PNG * (n // len(PNG) + 1))[:n]


def _init(client, size, chunk=None, name="photo.png"):
    body = {"filename": name, "size": size}
    if chunk:
        body["chunk_size"] = chunk
    return client.post("/api/v1/uploads/init", json=body)


def _put(client, uid, idx, data):
    return client.put(f"/api/v1/uploads/{uid}/chunks/{idx}", content=data)


def test_init_returns_plan(client):
    r = _init(client, 300 * 1024)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["chunk_size"] == 256 * 1024          # 服务端默认
    assert d["total_chunks"] == 2
    assert d["received"] == []
    assert d["status"] == "uploading"


def test_reject_bad_extension_and_size(client):
    assert _init(client, 1024, name="evil.sh").status_code == 400
    assert _init(client, 20 * 1024 * 1024).status_code == 422  # pydantic 上限


def test_upload_resume_after_interruption(client):
    """模拟中断：只传第 0 片 → 查状态 → 补第 1 片 → 合并。"""
    size, cs = 200 * 1024, 100 * 1024
    uid = _init(client, size, chunk=cs).json()["upload_id"]

    r = _put(client, uid, 0, _pad(cs))
    assert r.status_code == 200, r.text
    assert r.json()["received"] == [0]
    assert r.json()["done"] is False

    # 中断后重连：查服务端状态（前端据此决定从哪片续传）
    st = client.get(f"/api/v1/uploads/{uid}").json()
    assert st["received"] == [0]
    assert st["status"] == "uploading"

    # 缺片时合并必须被拒
    assert client.post(f"/api/v1/uploads/{uid}/complete").status_code == 400

    assert _put(client, uid, 1, _pad(size - cs)).json()["done"] is True
    done = client.post(f"/api/v1/uploads/{uid}/complete")
    assert done.status_code == 200, done.text
    d = done.json()
    assert d["status"] == "completed" and d["path"].endswith(".png")
    assert d["total_size"] == size


def test_reupload_same_chunk_is_idempotent(client):
    """超时重传：同一片传两次不应报错，也不应重复计数。"""
    uid = _init(client, 64 * 1024).json()["upload_id"]
    data = _pad(64 * 1024)
    assert _put(client, uid, 0, data).json()["received"] == [0]
    assert _put(client, uid, 0, data).json()["received"] == [0]


def test_out_of_order_chunks(client):
    size, cs = 300 * 1024, 100 * 1024
    uid = _init(client, size, chunk=cs).json()["upload_id"]
    assert _put(client, uid, 2, _pad(cs)).json()["received"] == [2]
    assert _put(client, uid, 0, _pad(cs)).json()["received"] == [0, 2]
    assert _put(client, uid, 1, _pad(cs)).json()["done"] is True
    assert client.post(f"/api/v1/uploads/{uid}/complete").status_code == 200


def test_chunk_size_mismatch_rejected(client):
    uid = _init(client, 128 * 1024, chunk=64 * 1024).json()["upload_id"]
    r = _put(client, uid, 0, b"x" * 100)          # 该片必须 64KB
    assert r.status_code == 400
    assert "分片大小不符" in r.json()["detail"]


def test_chunk_index_out_of_range(client):
    uid = _init(client, 64 * 1024).json()["upload_id"]
    assert _put(client, uid, 5, _pad(64 * 1024)).status_code == 400


def test_unknown_upload_id_is_rejected(client):
    assert client.get("/api/v1/uploads/deadbeef").status_code == 400


def test_discard_removes_session(client):
    uid = _init(client, 64 * 1024).json()["upload_id"]
    assert client.delete(f"/api/v1/uploads/{uid}").status_code == 200
    assert client.get(f"/api/v1/uploads/{uid}").status_code == 400


def test_ask_question_accepts_upload_id(client, mock_llm):
    """答疑接口可直接消费分片上传结果，免去二次传输。"""
    uid = _init(client, len(PNG)).json()["upload_id"]
    assert _put(client, uid, 0, PNG).json()["done"] is True
    assert client.post(f"/api/v1/uploads/{uid}/complete").status_code == 200

    r = client.post(
        "/api/v1/questions",
        data={
            "user_id": "1",
            "client_question_id": "cid-upload-1",
            "image_upload_id": uid,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "answered"


def test_ask_question_requires_image_or_upload_id(client):
    r = client.post(
        "/api/v1/questions",
        data={"user_id": "1", "client_question_id": "cid-none"},
    )
    assert r.status_code == 422
