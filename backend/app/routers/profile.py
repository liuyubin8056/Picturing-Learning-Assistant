"""个性画像接口：互动反馈提交、画像读取（md）、雷达图 JSON。"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..config import BASE_DIR
from ..db import get_session
from ..models import Question
from ..services import profile_service as ps

router = APIRouter(prefix="/api/v1/profile", tags=["个性画像"])


class FeedbackIn(BaseModel):
    """学生互动反馈：不限数量多选 + 自定义。"""

    selected: list[str] = Field(default_factory=list, description="选中的错因 tag，可多选")
    custom: list[str] = Field(default_factory=list, description="自定义原因（原文）")
    solved: bool = Field(default=False, description="是否已看懂/会做（选中项可为空）")


class ProfileOut(BaseModel):
    user_id: int
    markdown: str
    radar: dict
    stats: list[dict]


@router.post("/questions/{question_id}/feedback", summary="提交互动反馈（多选+自定义）")
def submit_feedback(
    question_id: int, body: FeedbackIn, session: Session = Depends(get_session)
):
    q = session.get(Question, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    if not body.selected and not body.custom and not body.solved:
        raise HTTPException(status_code=422, detail="请至少选择一个原因或填写自定义描述")

    # 记录反馈结果（可重复提交，以最后一次为准）
    q.feedback_result = json.dumps(
        {"selected": body.selected, "custom": body.custom, "solved": body.solved},
        ensure_ascii=False,
    )
    q.feedback_at = ps.utcnow()
    session.add(q)

    result = ps.record_feedback(
        session, q.user_id, q, body.selected, body.custom, solved=body.solved
    )
    session.commit()

    # 答疑即时更新画像
    profile = ps.rebuild_profile(session, q.user_id)
    return {
        "question_id": question_id,
        "profile_updated": True,
        "kp_updated": result["kp_updated"],
        "score_delta": result["score_delta"],
        "md_path": profile["md_path"],
    }


@router.get("/users/{user_id}", response_model=ProfileOut, summary="读取画像（md + 统计 + 雷达图）")
def get_profile(
    user_id: int,
    refresh: bool = Query(False, description="true 则强制重算"),
    session: Session = Depends(get_session),
):
    md_file = ps.PROFILE_DIR / f"{user_id}.md"
    if refresh or not md_file.exists():
        ps.rebuild_profile(session, user_id)
    md = md_file.read_text(encoding="utf-8") if md_file.exists() else ""
    stats = ps.user_kp_stats(session, user_id)
    radar = ps.radar_data(session, user_id)
    return ProfileOut(user_id=user_id, markdown=md, radar=radar, stats=stats)


@router.get("/users/{user_id}/markdown", summary="下载/预览画像 md 原文")
def get_profile_md(user_id: int, session: Session = Depends(get_session)):
    md_file = ps.PROFILE_DIR / f"{user_id}.md"
    if not md_file.exists():
        ps.rebuild_profile(session, user_id)
    if not md_file.exists():
        raise HTTPException(status_code=404, detail="画像尚未生成")
    return FileResponse(
        str(md_file), media_type="text/markdown", filename=f"profile_{user_id}.md"
    )


@router.get("/users/{user_id}/radar", summary="雷达图 JSON（前端直接渲染）")
def get_radar(user_id: int, session: Session = Depends(get_session)):
    return ps.radar_data(session, user_id)


@router.post("/users/{user_id}/refresh", summary="强制重建画像（自测后调用）")
def refresh_profile(user_id: int, session: Session = Depends(get_session)):
    return ps.rebuild_profile(session, user_id)