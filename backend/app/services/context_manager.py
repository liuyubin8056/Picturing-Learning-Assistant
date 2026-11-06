"""上下文管理：把画像压缩成可控体量的提示词，并管理 L1/L2/L3 三层上下文。

设计目标（对应 docs/token优化论证.md）：
- **L1 长期画像摘要**：每次 AI 调用都注入，控制 ≤ 300 token，且前缀稳定以命中服务端缓存
- **L2 会话摘要**：同一题的多轮追问压缩成短摘要，只保留结论
- **L3 短期窗口**：仅保留最近 N 轮原文，超出即裁剪

分层裁剪策略：
| 层 | 内容 | 体量上限 | 注入时机 | 缓存策略 |
|---|---|---|---|---|
| L1 | 掌握度/薄弱点/错因倾向 | 300 token | 每次调用 | 稳定前缀（末尾变化） |
| L2 | 本会话结论摘要 | 200 token | 同一会话内 | 追加在 L1 之后 |
| L3 | 最近 N 轮原文 | 1200 token | 仅追问时 | 变动部分，尽量靠后 |

裁剪原则：先丢最旧的 L3 轮次 → 再压缩 L2 → L1 不裁剪但限制条目数（只取 Top N 薄弱点）。
"""

import json

from sqlmodel import Session

from . import profile_service as ps

L1_MAX_CHARS = 1000  # ≈300 token（中文约 1 字 ≈ 0.6~1 token）
L2_MAX_CHARS = 600
L3_MAX_TURNS = 4
TOP_KP = 5  # L1 只带 Top5 薄弱 + Top3 优势


def build_l1_profile(session: Session, user_id: int) -> str:
    """L1 长期画像摘要：只保留对答题有指导价值的高密度信息。"""
    stats = ps.user_kp_stats(session, user_id)
    if not stats:
        return ""

    weak = [s for s in stats if s["weak"] >= ps.WEAK_THRESHOLD][:TOP_KP]
    if not weak:
        # 样本不足时取掌握度最低的 3 个，避免"无信息注入"
        weak = sorted(stats, key=lambda x: x["score"])[:3]
    strong = [s for s in stats if s["score"] >= ps.STRONG_THRESHOLD][:3]

    parts = [f"【学习画像】共{len(stats)}个知识点信号"]
    if weak:
        items = []
        for s in weak:
            tags = "、".join(ps._fmt_tag(t) for t in s["error_tags"]) or "原因未反馈"
            items.append(f"{s['kp_name']}(薄弱度{s['weak']:.2f},{tags})")
        parts.append("薄弱点：" + "；".join(items))
    if strong:
        parts.append("已掌握：" + "、".join(s["kp_name"] for s in strong))
    parts.append("作答要求：讲解时优先照顾薄弱点涉及的公式与条件；已知会的部分不必展开。")

    text = "\n".join(parts)
    return text[:L1_MAX_CHARS]


def build_l2_summary(turns: list[dict]) -> str:
    """L2 会话摘要：把本会话已完成轮次压缩成结论。

    turns 形如 [{"question": "...", "answer": "...", "verdict": "会了/没懂"}]
    """
    if not turns:
        return ""
    lines = ["【本会话已讨论】"]
    for i, t in enumerate(turns[-L3_MAX_TURNS:], 1):
        q = (t.get("question") or "")[:40]
        v = t.get("verdict") or ""
        lines.append(f"{i}. {q}{('（' + v + '）') if v else ''}")
    return "\n".join(lines)[:L2_MAX_CHARS]


def build_l3_window(turns: list[dict]) -> list[dict]:
    """L3 短期窗口：只保留最近 N 轮原文。"""
    return turns[-L3_MAX_TURNS:]


def compose(
    session: Session,
    user_id: int,
    turns: list[dict] | None = None,
    base_prompt: str = "",
    with_profile: bool = True,
) -> str:
    """拼装 system prompt：基础指令 + L1 画像 + L2 摘要（L3 由调用方按需带入 user）。

    顺序固定为「基础指令 → L1 → L2」：基础指令与 L1 前缀在同一用户下保持稳定，
    服务端缓存可命中前缀部分；变化最频繁的 L2/L3 放最靠后。
    """
    blocks = [base_prompt.strip()] if base_prompt.strip() else []
    if with_profile:
        l1 = build_l1_profile(session, user_id)
        if l1:
            blocks.append(l1)
    if turns:
        l2 = build_l2_summary(turns)
        if l2:
            blocks.append(l2)
    return "\n\n".join(blocks)


def profile_size(session: Session, user_id: int) -> dict:
    """度量画像注入体量（验证手段：观察注入前后的 prompt_tokens 变化）。"""
    text = build_l1_profile(session, user_id)
    return {
        "chars": len(text),
        "est_tokens": int(len(text) * 0.8),  # 中文按 0.8 字/token 粗估
        "limit_chars": L1_MAX_CHARS,
        "truncated": len(text) >= L1_MAX_CHARS,
        "content": text,
    }