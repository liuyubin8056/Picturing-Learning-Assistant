"""D 模块：诊断报告生成（规则算分 + LLM 撰写 + 原题证据 + 版本对比）。"""

import json

from sqlmodel import Session, select

from ..llm.deepseek import DeepSeekClient
from ..models import DiagnosisReport, KBProblem, Mastery, Question, utcnow
from . import profile_service as ps

REPORT_SYSTEM = """你是资深高数教师，要为学生写一份基于学习数据的个性化诊断报告。

写作要求：
1. 先给一句总体判断（当前主要问题是什么）。
2. 分点列出薄弱环节，每个薄弱点必须引用具体证据（哪道题、错因是什么），不要空泛。
3. 给出 2~3 条可执行的学习建议，按优先级排序。
4. 用学生能懂的话，避免说教口吻。禁止使用英文双引号。
5. 全程 Markdown，控制在 600 字以内。"""

USER_TEMPLATE = """以下是该学生的画像数据（由系统统计得出，请以此为准）：

{radar_table}

薄弱知识点明细：
{detail}

请生成诊断报告。若薄弱点证据不足，请如实说明"数据较少，建议先多练习"，不要编造。"""


def _evidence(
    session: Session, user_id: int, kp_ids: list[int], limit: int = 3
) -> list[dict]:
    """为薄弱知识点找原题证据，按可信度排序：

    1. 自测做错的题（含题干快照 + 学生答案，最具体）
    2. 答疑反馈记录（含学生自报错因）
    3. 都没有 → 标记证据不足，不编造
    """
    from ..models import TestQuestion, TestSession

    out: list[dict] = []
    sessions = {
        s.id
        for s in session.exec(select(TestSession).where(TestSession.user_id == user_id)).all()
    }

    for kp_id in kp_ids:
        hit = None
        if sessions:
            rows = session.exec(
                select(TestQuestion).where(TestQuestion.session_id.in_(sessions))
            ).all()
            for tq in rows:
                if tq.kp_ids and kp_id in json.loads(tq.kp_ids) and tq.is_correct is False:
                    hit = {
                        "kp_id": kp_id,
                        "type": "test",
                        "stem": (tq.stem or "")[:120],
                        "user_answer": tq.user_answer,
                        "correct_answer": tq.answer,
                    }
                    break
        if hit is None:
            for q in session.exec(select(Question).where(Question.user_id == user_id)).all():
                fb = json.loads(q.feedback_result) if q.feedback_result else None
                if not fb:
                    continue
                try:
                    tags = (json.loads(q.meta_json or "{}") or {}).get("kp_tags") or []
                except json.JSONDecodeError:
                    tags = []
                if kp_id in ps.resolve_kp_ids(session, tags):
                    hit = {
                        "kp_id": kp_id,
                        "type": "qa",
                        "question_id": q.id,
                        "feedback": fb,
                    }
                    break
        out.append(hit or {"kp_id": kp_id, "type": "none", "note": "证据不足"})
        if len([x for x in out if x["type"] != "none"]) >= limit * 2:
            break
    return out


def _radar_table(radar: dict) -> str:
    lines = ["| 章节 | 平均掌握度 | 知识点数 |", "|---|---|---|"]
    for a in radar.get("axes", []):
        lines.append(f"| {a['axis']} | {a['value']:.2f} | {a['kp_count']} |")
    return "\n".join(lines)


def _detail_table(stats: list[dict]) -> str:
    lines = ["| 知识点 | 掌握度 | 薄弱度 | 错因 |", "|---|---|---|---|"]
    for s in stats[:8]:
        tags = "、".join(ps._fmt_tag(t) for t in s["error_tags"]) or "未反馈"
        lines.append(f"| {s['kp_name']} | {s['score']:.2f} | {s['weak']:.2f} | {tags} |")
    return "\n".join(lines)


def confidence_of(stats: list[dict]) -> float:
    """置信度：信号越少越低，样本 <5 时显著降低。"""
    n = sum(
        s["ask_count"] + s["wrong_count"] + s["right_count"] + s["feedback_count"]
        for s in stats
    )
    if n == 0:
        return 0.0
    if n < 5:
        return round(min(0.4, n / 12), 2)
    if n < 20:
        return round(0.5 + n / 40, 2)
    return 0.9


def build_local_report(session: Session, user_id: int) -> dict:
    """规则版报告（不调 LLM）：LLM 不可用时仍能出报告，且零 token 成本。"""
    stats = ps.user_kp_stats(session, user_id)
    radar = ps.radar_data(session, user_id)
    weak = [s for s in stats if s["weak"] >= ps.WEAK_THRESHOLD][:5]
    lines = ["# 诊断报告", "", f"信号量：{radar['signal_count']} 条，覆盖 {len(stats)} 个知识点", ""]
    if not weak:
        lines.append("当前未发现明显薄弱点，建议继续积累练习数据。")
    else:
        lines += ["## 薄弱环节", ""]
        for s in weak:
            tags = "、".join(ps._fmt_tag(t) for t in s["error_tags"]) or "原因未反馈"
            lines.append(f"- **{s['kp_name']}**（薄弱度 {s['weak']:.2f}）：{tags}")
    lines += ["", "## 各章掌握度", "", _radar_table(radar)]
    return {
        "content_md": "\n".join(lines),
        "weak_kp_ids": [s["kp_id"] for s in weak],
        "strong_kp_ids": [
            s["kp_id"] for s in stats if s["score"] >= ps.STRONG_THRESHOLD
        ],
        "radar": radar,
        "confidence": confidence_of(stats),
        "token_used": 0,
    }


async def generate_report(
    session: Session, user_id: int, llm: DeepSeekClient, use_llm: bool = True
) -> DiagnosisReport:
    """生成诊断报告：默认走 LLM 撰写，算分与雷达图始终由规则负责。"""
    stats = ps.user_kp_stats(session, user_id)
    radar = ps.radar_data(session, user_id)
    local = build_local_report(session, user_id)

    content = local["content_md"]
    token_used = 0
    title = "学习诊断报告"
    # 证据与 LLM 无关：规则版同样要带原题证据
    weak_ids = local["weak_kp_ids"] or [s["kp_id"] for s in stats[:3]]
    evidence = _evidence(session, user_id, weak_ids) if stats else []

    if use_llm and stats:
        user_prompt = USER_TEMPLATE.format(
            radar_table=_radar_table(radar),
            detail=_detail_table(stats),
        )
        try:
            res = await llm.ask_text(REPORT_SYSTEM, user_prompt, max_tokens=4000)
            if res.answer.strip():
                content = res.answer.strip()
                token_used = res.usage.get("completion_tokens", 0)
        except Exception:  # noqa: BLE001 —— LLM 失败降级为规则版，不阻断业务
            pass

    prev = session.exec(
        select(DiagnosisReport)
        .where(DiagnosisReport.user_id == user_id)
        .order_by(DiagnosisReport.version.desc())
    ).first()
    version = (prev.version + 1) if prev else 1

    report = DiagnosisReport(
        user_id=user_id,
        version=version,
        prev_version=prev.version if prev else None,
        title=title,
        content_md=content,
        weak_kp_ids=json.dumps(local["weak_kp_ids"]),
        strong_kp_ids=json.dumps(local["strong_kp_ids"]),
        radar_json=json.dumps(radar, ensure_ascii=False),
        evidence_json=json.dumps(evidence, ensure_ascii=False),
        signal_count=radar["signal_count"],
        confidence=local["confidence"],
        token_used=token_used,
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


def compare_reports(session: Session, user_id: int, v1: int, v2: int) -> dict:
    """两个版本对比：薄弱点变化 + 掌握度变化。"""
    a = session.exec(
        select(DiagnosisReport).where(
            DiagnosisReport.user_id == user_id, DiagnosisReport.version == v1
        )
    ).first()
    b = session.exec(
        select(DiagnosisReport).where(
            DiagnosisReport.user_id == user_id, DiagnosisReport.version == v2
        )
    ).first()
    if a is None or b is None:
        return {"error": "版本不存在"}

    def weak_set(r: DiagnosisReport) -> set[int]:
        return set(json.loads(r.weak_kp_ids or "[]"))

    wa, wb = weak_set(a), weak_set(b)
    ra = json.loads(a.radar_json or "{}")
    rb = json.loads(b.radar_json or "{}")
    axes_a = {x["axis"]: x["value"] for x in ra.get("axes", [])}
    axes_b = {x["axis"]: x["value"] for x in rb.get("axes", [])}

    return {
        "from_version": v1,
        "to_version": v2,
        "signal_growth": b.signal_count - a.signal_count,
        "confidence": [a.confidence, b.confidence],
        "resolved": sorted(wa - wb),   # 已改善
        "new_weak": sorted(wb - wa),   # 新增薄弱
        "axis_change": [
            {"axis": k, "before": axes_a.get(k), "after": axes_b.get(k)}
            for k in sorted(set(axes_a) | set(axes_b))
        ],
    }