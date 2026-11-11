"""分片上传接口（断点续传）。

Web 与 App 共用同一套协议：前端把文件切成固定大小的分片逐片 PUT，
网络中断后先 GET 查已收到的分片，从缺口处继续。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..db import get_session
from ..deps import current_user
from ..models import User
from ..services import upload_service as us

router = APIRouter(prefix="/api/v1/uploads", tags=["分片上传"])


class InitIn(BaseModel):
    filename: str = Field(..., max_length=200)
    size: int = Field(..., gt=0, le=us.MAX_UPLOAD_BYTES)
    content_type: str | None = None
    chunk_size: int | None = None


def _guard(fn, *args, **kwargs):
    """把业务异常统一转成 4xx，避免 500。"""
    try:
        return fn(*args, **kwargs)
    except us.UploadError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/init", summary="创建分片上传会话")
def init(
    body: InitIn,
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    up = _guard(
        us.init_upload,
        session,
        me.id,
        body.filename,
        body.size,
        body.content_type,
        body.chunk_size,
    )
    return us.state_dict(up)


@router.put("/{upload_id}/chunks/{index}", summary="上传一个分片（可重传、可乱序）")
async def put_chunk(
    upload_id: str,
    index: int,
    request: Request,
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    up = _guard(us.get_owned, session, upload_id, me.id)
    data = await request.body()
    received = _guard(us.save_chunk, session, up, index, data)
    return {
        "upload_id": up.id,
        "received": received,
        "total_chunks": up.total_chunks,
        "done": len(received) >= up.total_chunks,
    }


@router.get("/{upload_id}", summary="查询上传进度（续传用）")
def status(
    upload_id: str,
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    up = _guard(us.get_owned, session, upload_id, me.id)
    return us.state_dict(up)


@router.post("/{upload_id}/complete", summary="校验并合并分片")
def complete(
    upload_id: str,
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    up = _guard(us.get_owned, session, upload_id, me.id)
    up = _guard(us.complete, session, up)
    return us.state_dict(up)


@router.delete("/{upload_id}", summary="放弃上传")
def discard(
    upload_id: str,
    me: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    up = _guard(us.get_owned, session, upload_id, me.id)
    _guard(us.discard, session, up)
    return {"deleted": True}
