"""分片上传（断点续传）服务。

协议：
    POST /uploads/init                      建会话，拿到 upload_id 与分片计划
    PUT  /uploads/{id}/chunks/{index}       逐片上传（可乱序、可重传）
    GET  /uploads/{id}                      查状态（续传时拿已收到的分片）
    POST /uploads/{id}/complete             校验并合并，返回可用的存储路径

要点：
- 分片落盘在 uploads/_chunks/{upload_id}/，合并成功后整目录删除
- 已完成的分片序号写在 DB 里，客户端刷新/重装 App 后仍能接着传
- 合并走顺序读，边读边算总量，超过声明大小立即中止（防被塞垃圾）
"""

import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from ..config import get_settings
from ..models import UploadSession

# 允许的扩展名（与答疑接口一致，只收图片）
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024        # 单文件 10MB，与 MAX_IMAGE_BYTES 对齐
MIN_CHUNK = 64 * 1024
MAX_CHUNK = 4 * 1024 * 1024
DEFAULT_CHUNK = 256 * 1024
# 未完成的会话保留 24 小时，之后允许被清理
SESSION_TTL = timedelta(hours=24)


def _root() -> Path:
    return Path(get_settings().upload_path)


def _chunk_dir(upload_id: str) -> Path:
    return _root() / "_chunks" / upload_id


class UploadError(Exception):
    """业务错误，路由层转成 4xx。"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def init_upload(
    session: Session,
    user_id: int,
    filename: str,
    size: int,
    content_type: str | None = None,
    chunk_size: int | None = None,
) -> UploadSession:
    if size <= 0:
        raise UploadError("文件为空")
    if size > MAX_UPLOAD_BYTES:
        raise UploadError(f"图片超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限")

    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise UploadError("仅支持 JPG / PNG / WEBP / HEIC / BMP")

    cs = chunk_size or DEFAULT_CHUNK
    cs = max(MIN_CHUNK, min(MAX_CHUNK, cs))
    total = (size + cs - 1) // cs

    up = UploadSession(
        id=uuid.uuid4().hex,
        user_id=user_id,
        filename=Path(filename).name[:120],
        content_type=content_type,
        total_size=size,
        chunk_size=cs,
        total_chunks=total,
        received_json="[]",
        status="uploading",
    )
    session.add(up)
    session.commit()
    session.refresh(up)
    _chunk_dir(up.id).mkdir(parents=True, exist_ok=True)
    return up


def get_owned(session: Session, upload_id: str, user_id: int) -> UploadSession:
    up = session.get(UploadSession, upload_id)
    if up is None:
        raise UploadError("上传会话不存在")
    if up.user_id != user_id:
        # 不区分「不存在」与「无权限」，避免探测他人 upload_id
        raise UploadError("上传会话不存在")
    return up


def save_chunk(
    session: Session, up: UploadSession, index: int, data: bytes
) -> list[int]:
    """写入一片；返回当前已收齐的序号列表（供前端判断续传进度）。"""
    if up.status == "completed":
        raise UploadError("该上传已完成")
    if index < 0 or index >= up.total_chunks:
        raise UploadError("分片序号越界")
    if not data:
        raise UploadError("分片内容为空")

    # 除最后一片外，每片大小必须等于 chunk_size（最后一片允许小）
    expected = (
        up.chunk_size
        if index < up.total_chunks - 1
        else up.total_size - up.chunk_size * (up.total_chunks - 1)
    )
    if len(data) != expected:
        raise UploadError(f"分片大小不符：期望 {expected} 字节，实际 {len(data)}")

    d = _chunk_dir(up.id)
    d.mkdir(parents=True, exist_ok=True)
    # 重传覆盖：网络超时后客户端不确定是否写入，重传必须幂等
    (d / f"{index:06d}.part").write_bytes(data)

    received = set(json.loads(up.received_json or "[]"))
    received.add(index)
    up.received_json = json.dumps(sorted(received))
    up.updated_at = _now()
    session.add(up)
    session.commit()
    session.refresh(up)
    return sorted(received)


def complete(session: Session, up: UploadSession) -> UploadSession:
    """校验完整性并合并成分片文件。"""
    if up.status == "completed" and up.stored_path:
        return up                        # 幂等：重复调用直接返回

    received = set(json.loads(up.received_json or "[]"))
    missing = [i for i in range(up.total_chunks) if i not in received]
    if missing:
        raise UploadError(f"还有 {len(missing)} 个分片未上传（首个缺失：{missing[0]}）")

    ext = Path(up.filename or "").suffix.lower() or ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"
    dst = _root() / name
    d = _chunk_dir(up.id)

    total = 0
    tmp = dst.with_suffix(dst.suffix + ".merging")
    with tmp.open("wb") as out:
        for i in range(up.total_chunks):
            part = d / f"{i:06d}.part"
            if not part.exists():
                tmp.unlink(missing_ok=True)
                raise UploadError(f"分片 {i} 丢失，请重新上传该片")
            data = part.read_bytes()
            total += len(data)
            if total > up.total_size:
                tmp.unlink(missing_ok=True)
                raise UploadError("合并后体积超过声明大小，已中止")
            out.write(data)
    tmp.replace(dst)

    up.status = "completed"
    up.stored_path = name
    up.updated_at = _now()
    session.add(up)
    session.commit()
    session.refresh(up)

    shutil.rmtree(d, ignore_errors=True)     # 成功后才清理分片
    return up


def discard(session: Session, up: UploadSession) -> None:
    """放弃上传：删分片与记录。"""
    shutil.rmtree(_chunk_dir(up.id), ignore_errors=True)
    if up.stored_path:
        (_root() / up.stored_path).unlink(missing_ok=True)
    session.delete(up)
    session.commit()


def sweep_stale(session: Session, older_than: timedelta = SESSION_TTL) -> int:
    """清理超时未完成的上传（cron 或启动时调用）。"""
    cut = _now() - older_than
    n = 0
    for up in session.exec(
        select(UploadSession).where(UploadSession.status == "uploading")
    ).all():
        ts = up.updated_at or up.created_at
        if ts and ts.replace(tzinfo=ts.tzinfo or timezone.utc) < cut:
            shutil.rmtree(_chunk_dir(up.id), ignore_errors=True)
            session.delete(up)
            n += 1
    if n:
        session.commit()
    return n


def state_dict(up: UploadSession) -> dict:
    return {
        "upload_id": up.id,
        "filename": up.filename,
        "total_size": up.total_size,
        "chunk_size": up.chunk_size,
        "total_chunks": up.total_chunks,
        "received": json.loads(up.received_json or "[]"),
        "status": up.status,
        "path": up.stored_path,
    }
