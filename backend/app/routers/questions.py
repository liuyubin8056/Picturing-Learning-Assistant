"""拍照答疑接口。"""

import json
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_session
from ..llm.deepseek import DeepSeekClient, LLMCallError, LLMNotConfiguredError
from ..models import Question
from ..schemas import QuestionOut
from ..services.question_service import MAX_IMAGE_BYTES, QuestionService
from ..storage import get_storage

router = APIRouter(prefix="/api/v1", tags=["拍照答疑"])


def to_out(q: Question, storage, duplicated: bool = False) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        user_id=q.user_id,
        client_question_id=q.client_question_id,
        image_url=storage.url_for(q.image_path),
        status=q.status,
        answer=q.answer,
        meta=json.loads(q.meta_json) if q.meta_json else None,
        error_msg=q.error_msg,
        duplicated=duplicated,
        created_at=q.created_at,
        answered_at=q.answered_at,
    )


@router.post(
    "/questions",
    response_model=QuestionOut,
    summary="上传题目照片并答疑（幂等）",
    description=(
        "multipart/form-data：image（照片）、user_id、client_question_id"
        "（端侧生成的 UUID，断网续传重试凭它去重；上次失败的记录可重试）"
    ),
)
async def create_question(
    image: UploadFile = File(..., description="题目照片"),
    user_id: int = Form(...),
    client_question_id: str = Form(..., description="端侧幂等 ID（UUID）"),
    session: Session = Depends(get_session),
):
    # 上传体积前置检查（避免先整读超大文件）
    if image.size is not None and image.size > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="图片超过 10MB 上限")

    storage = get_storage()
    svc = QuestionService(session, storage, DeepSeekClient(get_settings()))
    ext = Path(image.filename or "").suffix or ".jpg"
    image_bytes = await image.read()

    try:
        question, replay = await svc.submit(
            user_id, client_question_id, image_bytes, ext
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LLMNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY 未配置：请在 backend/.env 填入后重启服务",
        )
    except LLMCallError as e:
        raise HTTPException(status_code=502, detail=f"大模型调用失败：{e}")
    except IntegrityError:
        # 并发双插兜底：回滚后返回已存在的记录
        session.rollback()
        existing = svc.get_by_client_id(client_question_id)
        if existing is not None and existing.status == "answered":
            return to_out(existing, storage, duplicated=True)
        raise HTTPException(status_code=409, detail="并发冲突，请重试")

    return to_out(question, storage, duplicated=replay)


@router.get("/questions/{question_id}", response_model=QuestionOut, summary="查询单题")
def get_question(question_id: int, session: Session = Depends(get_session)):
    q = session.get(Question, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return to_out(q, get_storage())


@router.get(
    "/users/{user_id}/questions",
    response_model=list[QuestionOut],
    summary="用户的提问历史（倒序分页）",
)
def list_questions(
    user_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    storage = get_storage()
    stmt = (
        select(Question)
        .where(Question.user_id == user_id)
        .order_by(Question.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [to_out(q, storage) for q in session.exec(stmt)]
