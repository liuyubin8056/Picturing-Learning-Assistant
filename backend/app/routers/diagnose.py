"""D 模块接口：诊断报告生成、列表、版本对比。"""

import json

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_session
from ..llm.deepseek import DeepSeekClient
from ..models import DiagnosisReport
from ..services import diagnose_service as ds
from ..services.token_service import record_usage

router = APIRouter(prefix="/api/v1/diagnose", tags=["诊断报告"])


@router.post("/users/{user_id}", summary="生成诊断报告（规则算分 + LLM 撰写）")
async def generate(user_id: int, use_llm: bool = Query(True), session: Session = Depends(get_session)):
    llm = DeepSeekClient(get_settings())
    report = await ds.generate_report(session, user_id, llm, use_llm=use_llm)
    if report.token_used:
        record_usage(
            session,
            user_id=user_id,
            scene="diagnose",
            model=get_settings().deepseek_model,
            completion_tokens=report.token_used,
        )
        session.commit()
    return {
        "id": report.id,
        "version": report.version,
        "title": report.title,
        "content_md": report.content_md,
        "evidence": json.loads(report.evidence_json) if report.evidence_json else None,
        "weak_kp_ids": json.loads(report.weak_kp_ids or "[]"),
        "radar": json.loads(report.radar_json) if report.radar_json else None,
        "confidence": report.confidence,
        "signal_count": report.signal_count,
        "token_used": report.token_used,
        "created_at": report.created_at,
    }


@router.get("/users/{user_id}", summary="报告列表")
def list_reports(user_id: int, limit: int = Query(10, ge=1, le=50), session: Session = Depends(get_session)):
    rows = session.exec(
        select(DiagnosisReport)
        .where(DiagnosisReport.user_id == user_id)
        .order_by(DiagnosisReport.version.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "version": r.version,
            "title": r.title,
            "confidence": r.confidence,
            "signal_count": r.signal_count,
            "weak_count": len(json.loads(r.weak_kp_ids or "[]")),
            "token_used": r.token_used,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/users/{user_id}/latest", summary="最新报告")
def latest(user_id: int, session: Session = Depends(get_session)):
    r = session.exec(
        select(DiagnosisReport)
        .where(DiagnosisReport.user_id == user_id)
        .order_by(DiagnosisReport.version.desc())
    ).first()
    if r is None:
        return {"message": "尚无报告，请先生成"}
    return {
        "id": r.id,
        "version": r.version,
        "content_md": r.content_md,
        "radar": json.loads(r.radar_json) if r.radar_json else None,
        "evidence": json.loads(r.evidence_json) if r.evidence_json else None,
        "confidence": r.confidence,
        "created_at": r.created_at,
    }


@router.get("/users/{user_id}/compare", summary="两个版本对比")
def compare(
    user_id: int,
    from_version: int = Query(..., alias="v1"),
    to_version: int = Query(..., alias="v2"),
    session: Session = Depends(get_session),
):
    return ds.compare_reports(session, user_id, from_version, to_version)