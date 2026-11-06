"""个性画像服务：信号入账 → 掌握度更新 → 薄弱度计算 → md 文档生成。

信号设计（依据最新论证结论）：
- **主信号**：用户在答疑后自报的错误原因（多选 + 自定义）——比模型推断准确得多
- **确定性信号**：自测判分结果（客观题直接判对错），不依赖用户主观报告
- **弱信号**：仅拍照提问未反馈（记一次求助，但错因权重按中性处理）

低级错误（careless 看错题等）权重低，不会把马虎误判成知识漏洞。
"""

import json
from datetime import datetime, timedelta, timezone
from math import exp
from pathlib import Path

from sqlmodel import Session, select

from ..config import BASE_DIR
from ..models import KnowledgePoint, Mastery, ProfileMeta, Question, utcnow

PROFILE_DIR = BASE_DIR / "profiles"

# 错因权重：真正没掌握的原因权重高，低级错误权重低
ERR_WEIGHTS = {
    "concept_unclear": 1.0,   # 概念没理解
    "method_missing": 1.0,    # 方法没想到
    "no_idea": 1.2,           # 完全没思路
    "knowledge_gap": 1.1,     # 知识点没学过/忘了
    "misread": 0.2,           # 看错题（低级）
    "careless": 0.2,          # 粗心算错（低级）
    "calculation": 0.3,       # 计算失误
    "condition_miss": 0.4,    # 漏看条件
    "other": 0.6,             # 自定义
}
DEFAULT_WEIGHT = 0.6
# 低级错误：只反映"这次没做对"，不代表知识漏洞
LOW_LEVEL_TAGS = {"careless", "misread", "calculation", "condition_miss"}

# 模型常自创 tag 变体名（如 missing_method），此处归一化到标准集合，
# 否则权重查表失败会退化成默认值，低级错误的"免判薄弱"保护也会失效。
TAG_ALIASES = {
    "missing_method": "method_missing",
    "method_lack": "method_missing",
    "no_method": "method_missing",
    "method_unknown": "method_missing",
    "carelessness": "careless",
    "silly_mistake": "careless",
    "read_wrong": "misread",
    "misreading": "misread",
    "misunderstood_problem": "misread",
    "calculation_error": "calculation",
    "calc_error": "calculation",
    "miscalculation": "calculation",
    "missed_condition": "condition_miss",
    "miss_condition": "condition_miss",
    "concept_confusion": "concept_unclear",
    "unclear_concept": "concept_unclear",
    "concept_missing": "concept_unclear",
    "no_clue": "no_idea",
    "no_thinking": "no_idea",
    "knowledge_forgotten": "knowledge_gap",
    "forgot_knowledge": "knowledge_gap",
}


def normalize_tag(tag: str) -> str:
    """把模型自创的错因 tag 归一化到标准集合。"""
    t = (tag or "").strip().lower().replace("-", "_").replace(" ", "_")
    if t in ERR_WEIGHTS or t in LOW_LEVEL_TAGS:
        return t
    return TAG_ALIASES.get(t, t)


DECAY_DAYS = 30.0            # 时间衰减常数
EMA_OLD = 0.7                # 掌握度 EMA 系数
WEAK_THRESHOLD = 0.35        # 薄弱判定阈值
STRONG_THRESHOLD = 0.75      # 优势判定阈值


def _weight(tag: str) -> float:
    return ERR_WEIGHTS.get(tag, DEFAULT_WEIGHT)


def _norm_weights(meta_json: str | None) -> dict:
    """从 questions.meta_json 取出模型给的选项权重表 {tag: weight}。"""
    if not meta_json:
        return {}
    try:
        meta = json.loads(meta_json)
    except json.JSONDecodeError:
        return {}
    out = {}
    for opt in meta.get("feedback_options") or []:
        tag = (opt.get("tag") or "").strip()
        if tag:
            try:
                out[tag] = float(opt.get("weight", DEFAULT_WEIGHT))
            except (TypeError, ValueError):
                out[tag] = DEFAULT_WEIGHT
    return out


def _find_mastery(session: Session, user_id: int, kp_id: int) -> Mastery | None:
    stmt = select(Mastery).where(Mastery.user_id == user_id, Mastery.kp_id == kp_id)
    return session.exec(stmt).first()


def _or_create(session: Session, user_id: int, kp_id: int) -> Mastery:
    m = _find_mastery(session, user_id, kp_id)
    if m is None:
        m = Mastery(user_id=user_id, kp_id=kp_id)
        session.add(m)
        session.flush()
    return m


def resolve_kp_ids(session: Session, names: list[str]) -> list[int]:
    """知识点名称 → id（答疑时模型给的是 kp_tags 名称，此处映射到库内 id）。

    四级匹配：精确 → 去噪精确 → 双向包含 → 去噪包含，尽量提高命中率。
    模型常写「函数的定义域」「定义域求法」，库内是「函数定义域」，故需要去噪。
    """
    names = [n.strip() for n in (names or []) if n and n.strip()]
    if not names:
        return []
    rows = session.exec(
        select(KnowledgePoint).where(KnowledgePoint.level == 3)
    ).all()
    name_map = {r.name: r.id for r in rows}

    def denoise(s: str) -> str:
        """归一化名称：先剥离常见后缀词，再删去结构助词「的」。

        例：「函数的定义域」→「函数定义域」「定义域求法」→「定义域」。
        两侧名称都走同样归一化后再比较，避免误伤（如「函数的连续性」）。
        """
        s = s.strip()
        for suf in ("的求法", "求法", "的计算", "计算", "及应用", "应用"):
            if s.endswith(suf) and len(s) > len(suf):
                s = s[: -len(suf)]
        return s.replace("的", "").strip()

    denoised_map = {
        dn: r.id for r in rows if (dn := denoise(r.name))
    }
    ids: list[int] = []

    def add(i: int) -> None:
        if i not in ids:
            ids.append(i)

    for n in names:
        if n in name_map:                      # ① 精确
            add(name_map[n])
            continue
        dn = denoise(n)
        if dn in denoised_map:                 # ② 去噪精确
            add(denoised_map[dn])
            continue
        hit = None
        for r in rows:                         # ③ 双向包含（原逻辑）
            if n in r.name or r.name in n:
                hit = r.id
                break
        if hit is None and dn:                 # ④ 去噪包含
            for r in rows:
                rn = denoise(r.name)
                if dn and (dn in rn or rn in dn):
                    hit = r.id
                    break
        if hit is not None:
            add(hit)
    return ids


def kp_ids_of(session: Session, question: Question) -> list[int]:
    """取题目关联的知识点 id：优先用已存的 kp_ids，否则按 kp_tags 名称解析。"""
    try:
        meta = json.loads(question.meta_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(meta, dict):
        return []
    raw_ids = meta.get("kp_ids")
    if isinstance(raw_ids, list) and raw_ids:
        out = []
        for i in raw_ids:
            try:
                out.append(int(i))
            except (TypeError, ValueError):
                continue
        if out:
            return list(dict.fromkeys(out))
    return resolve_kp_ids(session, meta.get("kp_tags") or [])


def record_ask(session: Session, user_id: int, question: Question) -> int:
    """弱信号：拍照提问本身计入求助（错因中性权重 0.6）。"""
    ids = kp_ids_of(session, question)
    n = 0
    for kp_id in ids:
        m = _or_create(session, user_id, kp_id)
        m.ask_count += 1
        m.last_active_at = utcnow()
        m.updated_at = utcnow()
        session.add(m)
        n += 1
    return n


def record_feedback(
    session: Session,
    user_id: int,
    question: Question,
    selected: list[str],
    custom: list[str] | None = None,
    solved: bool = False,
) -> dict:
    """主信号：用户自报错因。

    solved=True 表示用户反馈"我看懂了/会了"，直接按掌握度上调处理。
    """
    # tag 归一化：模型/前端传来的可能是自创变体（如 missing_method）
    tags = [normalize_tag(t) for t in (selected or []) if t]
    tags = list(dict.fromkeys(tags))
    notes = [c.strip() for c in (custom or []) if c and c.strip()]
    model_w = _norm_weights(question.meta_json)

    ids = kp_ids_of(session, question)

    # 掌握度变化：取最强错因（与 weak_score 口径一致，避免多选被平均稀释）
    if solved and not tags:
        delta = 0.15
    else:
        cw = max((model_w.get(t, DEFAULT_WEIGHT) for t in tags), default=DEFAULT_WEIGHT)
        delta = -0.12 * cw

    touched = 0
    has_real_gap = any(t not in LOW_LEVEL_TAGS for t in tags)
    for kp_id in ids:
        m = _or_create(session, user_id, kp_id)
        m.score = max(0.0, min(1.0, m.score * EMA_OLD + (1.0 + delta) * (1 - EMA_OLD)))
        m.feedback_count += 1
        if has_real_gap:
            # 反馈确认"这题确实不会"，补记一次真实求助（纯低级错误不记）
            m.ask_count += 1
        m.last_active_at = utcnow()
        m.updated_at = utcnow()
        if tags:
            counter = json.loads(m.error_tags or "{}")
            for t in tags:
                counter[t] = counter.get(t, 0) + 1
            m.error_tags = json.dumps(counter, ensure_ascii=False)
        if notes:
            old = json.loads(m.custom_notes or "[]")
            old.extend(notes)
            m.custom_notes = json.dumps(old[-10:], ensure_ascii=False)
        session.add(m)
        touched += 1

    return {
        "kp_updated": touched,
        "tags": tags,
        "custom": notes,
        "score_delta": round(delta, 3),
    }


def record_test_result(
    session: Session,
    user_id: int,
    kp_ids: list[int],
    correct: bool,
    subjective_self: bool | None = None,
) -> None:
    """确定性信号：自测判分（客观题直接判分；主观题用用户自评）。"""
    if subjective_self is not None:
        correct = bool(subjective_self)
    for kp_id in kp_ids or []:
        m = _or_create(session, user_id, kp_id)
        if correct:
            m.right_count += 1
            target = 1.0
        else:
            m.wrong_count += 1
            target = 0.0
        m.score = max(0.0, min(1.0, m.score * EMA_OLD + target * (1 - EMA_OLD)))
        m.last_active_at = utcnow()
        m.updated_at = utcnow()
        session.add(m)


def weak_score(m: Mastery, now: datetime | None = None) -> float:
    """实时计算薄弱度 0~1（不落库）。

    设计要点：错因权重是**乘性主因子**，而非微调项——否则「粗心/看错题」
    反复出现时仍会被误判为知识薄弱。实测：
      单次概念不清 → 1.00（薄弱）；单次粗心 → 0.32（不算薄弱）
    """
    now = now or utcnow()
    total = m.ask_count + m.wrong_count + m.right_count + m.feedback_count
    if total == 0:
        return 0.0

    # 错误率：自测错权重高于求助（求助只说明"不会"，自测错还可能含笔误）
    err = (m.ask_count + 2 * m.wrong_count) / max(total, 1)

    # 错因加权：取**最强错因**而非平均——多选时不能被低级错误稀释真问题。
    # 例：学生同时勾「概念不清」和「粗心」，若不取 max，平均后 0.6 会把
    #     概念不清（1.0）的真实信号冲淡，导致该知识点漏判为不薄弱（实测 0.33）。
    tags = json.loads(m.error_tags or "{}")
    if tags:
        cw = max(_weight(t) for t in tags)
    else:
        cw = 0.5

    # 错因修正因子 0.15~1.0：低级错误即使反复出现也不构成知识漏洞
    cw_adj = 0.15 + 0.85 * cw

    # 时间衰减：久未练习的薄弱点权重下降（按艾宾浩斯遗忘）
    ref = m.last_active_at or m.created_at or now
    days = max((now - ref).days, 0)
    decay = exp(-days / DECAY_DAYS)

    score = min(1.0, err * cw_adj * decay)
    return round(score, 3)


def user_kp_stats(session: Session, user_id: int) -> list[dict]:
    """全部掌握度记录 + 实时薄弱度，按薄弱度降序。"""
    rows = session.exec(select(Mastery).where(Mastery.user_id == user_id)).all()
    kp_ids = [r.kp_id for r in rows]
    names: dict[int, tuple[str, str]] = {}
    if kp_ids:
        kps = session.exec(
            select(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids))
        ).all()
        for k in kps:
            names[k.id] = (k.name, k.chapter or "")
    now = utcnow()
    out = []
    for r in rows:
        name, chapter = names.get(r.kp_id, (f"知识点#{r.kp_id}", ""))
        out.append(
            {
                "kp_id": r.kp_id,
                "kp_name": name,
                "chapter": chapter,
                "score": round(r.score, 3),
                "weak": weak_score(r, now),
                "ask_count": r.ask_count,
                "wrong_count": r.wrong_count,
                "right_count": r.right_count,
                "feedback_count": r.feedback_count,
                "error_tags": json.loads(r.error_tags or "{}"),
                "custom_notes": json.loads(r.custom_notes or "[]"),
                "last_active_at": r.last_active_at,
            }
        )
    return sorted(out, key=lambda x: -x["weak"])


def radar_data(session: Session, user_id: int) -> dict:
    """雷达图数据（后端出 JSON，前端画）：按章聚合平均掌握度 + 薄弱点。

    轴是**全书章节骨架**（按书序），用户没练过的章节值为 0 并标 practiced=False，
    这样雷达图始终是完整的正 N 边形（如全书 12 章 → 正十二边形），
    能一眼看出"哪些章节还没开始学"，而不是只画有数据的几章。
    """
    from ..models import KnowledgePoint

    stats = user_kp_stats(session, user_id)
    by_chapter: dict[str, list[float]] = {}
    for s in stats:
        by_chapter.setdefault(s["chapter"] or "未分类", []).append(s["score"])

    # 全书章节骨架（L1 按 id 顺序 = 教材顺序）
    all_chapters = session.exec(
        select(KnowledgePoint)
        .where(KnowledgePoint.level == 1)
        .order_by(KnowledgePoint.id)
    ).all()
    order = [c.name for c in all_chapters]
    # 兜底：不在骨架里的章节（如自建测试数据）追加在后面
    for ch in by_chapter:
        if ch not in order:
            order.append(ch)

    axes = []
    for ch in order:
        vals = by_chapter.get(ch)
        if vals:
            axes.append(
                {
                    "axis": ch,
                    "value": round(sum(vals) / len(vals), 3),
                    "kp_count": len(vals),
                    "practiced": True,
                }
            )
        else:
            axes.append({"axis": ch, "value": 0.0, "kp_count": 0, "practiced": False})
    weak = [s for s in stats if s["weak"] >= WEAK_THRESHOLD]
    return {
        "axes": axes,  # 已按教材章序排列，含未练习章节（value=0）
        "weak_points": [
            {
                "kp_id": s["kp_id"],
                "kp_name": s["kp_name"],
                "chapter": s["chapter"],
                "weak": s["weak"],
                "score": s["score"],
                "error_tags": list(s["error_tags"].keys()),
            }
            for s in weak[:20]
        ],
        "signal_count": sum(
            s["ask_count"] + s["wrong_count"] + s["right_count"] + s["feedback_count"]
            for s in stats
        ),
        "generated_at": utcnow().isoformat(),
    }


def _fmt_tag(tag: str) -> str:
    labels = {
        "concept_unclear": "概念没理解",
        "method_missing": "方法没想到",
        "no_idea": "完全没思路",
        "knowledge_gap": "知识点忘了/没学过",
        "misread": "看错题",
        "careless": "粗心算错",
        "calculation": "计算失误",
        "condition_miss": "漏看条件",
        "other": "其他",
    }
    return labels.get(tag, tag)


def render_markdown(
    user_id: int, stats: list[dict], radar: dict, questions_count: int, tests_count: int
) -> str:
    now = utcnow().strftime("%Y-%m-%d %H:%M")
    strong = [s for s in stats if s["score"] >= STRONG_THRESHOLD and s["weak"] < WEAK_THRESHOLD]
    weak = [s for s in stats if s["weak"] >= WEAK_THRESHOLD]

    lines = [
        f"# 用户画像 · {user_id}",
        "",
        f"更新：{now}（答疑即时更新）",
        "",
        "## 总览",
        f"- 拍照提问：{questions_count} 次",
        f"- 自测记录：{tests_count} 次",
        f"- 累计信号：{radar['signal_count']} 条",
        f"- 覆盖知识点：{len(stats)} 个（其中薄弱 {len(weak)} 个）",
        "",
    ]

    if stats and len(stats) < 5:
        lines += [
            "> ⚠️ 样本较少（不足 5 个知识点），结论仅供参考；多拍几题或做一次自测会更准。",
            "",
        ]

    lines += ["## 薄弱环节（按薄弱度排序）", ""]
    if not weak:
        lines.append("暂无明显薄弱点。")
    else:
        lines += [
            "| 知识点 | 章节 | 掌握度 | 薄弱度 | 证据 | 错因倾向 |",
            "|---|---|---|---|---|---|",
        ]
        for s in weak:
            ev = []
            if s["ask_count"]:
                ev.append(f"求助 {s['ask_count']}")
            if s["wrong_count"]:
                ev.append(f"自测错 {s['wrong_count']}")
            if s["right_count"]:
                ev.append(f"自测对 {s['right_count']}")
            tags = "、".join(_fmt_tag(t) for t in s["error_tags"]) or "（未反馈）"
            lines.append(
                f"| {s['kp_name']} | {s['chapter']} | {s['score']:.2f} | **{s['weak']:.2f}** "
                f"| {' · '.join(ev) or '—'} | {tags} |"
            )

    # 学生自述独立成节：即使某个知识点判定为优势，其自述也有诊断价值
    all_notes = [(s["kp_name"], n) for s in stats for n in s["custom_notes"]]
    if all_notes:
        lines += ["", "## 学生自述（原文）", ""]
        for name, n in all_notes[-10:]:
            lines.append(f"- 〔{name}〕{n}")

    lines += ["", "## 优势章节（可跳过复习）", ""]
    if strong:
        for s in strong[:10]:
            lines.append(f"- {s['kp_name']}（{s['chapter']}）掌握度 {s['score']:.2f}")
    else:
        lines.append("尚未形成优势知识点。")

    lines += ["", "## 雷达图数据（各章平均掌握度）", ""]
    if radar["axes"]:
        lines += ["| 章节 | 平均掌握度 | 知识点数 |", "|---|---|---|"]
        for a in radar["axes"]:
            lines.append(f"| {a['axis']} | {a['value']:.2f} | {a['kp_count']} |")
    else:
        lines.append("（暂无数据）")

    lines += [
        "",
        "## 下一步建议",
        "",
    ]
    if weak:
        for i, s in enumerate(weak[:3], 1):
            tags = "、".join(_fmt_tag(t) for t in s["error_tags"]) or "原因待反馈"
            lines.append(f"{i}. 优先练「{s['kp_name']}」（{s['chapter']}）—— 错因：{tags}")
    else:
        lines.append("1. 继续拍照提问，或做一次自测以收集数据。")

    lines += [
        "",
        "## 数据来源",
        f"- 答疑反馈：{sum(s['feedback_count'] for s in stats)} 条",
        f"- 自测结果：{sum(s['right_count'] + s['wrong_count'] for s in stats)} 条",
        f"- 拍照求助：{sum(s['ask_count'] for s in stats)} 条",
        f"- 生成时间：{now}（由后端 profile_service 自动渲染）",
        "",
    ]
    return "\n".join(lines)


def rebuild_profile(session: Session, user_id: int) -> dict:
    """重建画像：写 md 文件 + 更新 profile_meta（答疑反馈/自测后即时调用）。"""
    stats = user_kp_stats(session, user_id)
    radar = radar_data(session, user_id)
    questions_count = len(
        session.exec(select(Question).where(Question.user_id == user_id)).all()
    )
    tests_count = sum(s["right_count"] + s["wrong_count"] for s in stats)

    md = render_markdown(user_id, stats, radar, questions_count, tests_count)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILE_DIR / f"{user_id}.md"
    path.write_text(md, encoding="utf-8")

    meta = session.get(ProfileMeta, user_id)
    if meta is None:
        meta = ProfileMeta(user_id=user_id)
    weak_ids = [s["kp_id"] for s in stats if s["weak"] >= WEAK_THRESHOLD]
    strong_ids = [s["kp_id"] for s in stats if s["score"] >= STRONG_THRESHOLD]
    meta.md_path = f"profiles/{user_id}.md"
    meta.weak_kp_ids = json.dumps(weak_ids)
    meta.strong_kp_ids = json.dumps(strong_ids)
    meta.radar = json.dumps(radar, ensure_ascii=False)
    meta.signal_count = radar["signal_count"]
    meta.updated_at = utcnow()
    session.add(meta)
    session.commit()
    return {"md_path": str(path), "weak_count": len(weak_ids), "radar": radar}