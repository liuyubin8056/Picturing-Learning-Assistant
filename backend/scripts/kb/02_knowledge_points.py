"""步骤 2：用 LLM 将每个小节细分为知识点（L3），写入 knowledge_points 表。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/kb/02_knowledge_points.py --limit 1   # 先验证一批
    .venv/Scripts/python.exe scripts/kb/02_knowledge_points.py             # 全量（断点续跑）

每个小节 4~10 个细粒度知识点，输出缓存到 _kb_out/kp_batch_N.json，失败可重跑。
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.kb.common import call_llm, load_json, run_pool, save_json  # noqa: E402

from app.db import engine  # noqa: E402
from app.models import KnowledgePoint  # noqa: E402

PROMPT = """你是高等数学教学专家。给定《高等数学习题精选精解》的一个章及其若干小节标题，请为每个小节拆解出**细粒度知识点**列表，用于后续题目归类、薄弱点诊断与针对性练习。

要求：
1. 每个小节拆 4~10 个知识点，粒度要细到能对应具体题型与判定条件。例如「洛必达法则」应拆成「洛必达法则适用条件」「0/0 型与 ∞/∞ 型处理」「洛必达与泰勒配合使用」等，而不是笼统一个「洛必达法则」。
2. name ≤ 20 字；desc 一句话说明（≤40 字），讲清知识点是什么/判什么；key_formula 写核心公式或判定条件（无则留空字符串）。
3. difficulty：1=基础 2=中等 3=挑战。
4. 知识点之间不要重复，包含该节涉及的所有常考细分点。
5. **只输出 JSON，不要任何解释文字。**

输出格式：
{"sections":[{"section":"小节名（照抄输入）","points":[{"name":"...","desc":"...","key_formula":"...","difficulty":2}]}]}

示例输入：
第二章  导数与微分
1．导数的概念

示例输出：
{"sections":[{"section":"1．导数的概念","points":[
{"name":"导数定义式","desc":"由极限定义导数，理解其几何意义","key_formula":"f'(x)=lim(h→0)[f(x+h)-f(x)]/h","difficulty":1},
{"name":"左右导数与可导","desc":"左右导数存在且相等才可导","key_formula":"f'_-(x)=f'_+(x)","difficulty":2},
{"name":"可导与连续的关系","desc":"可导必连续，连续未必可导","key_formula":"","difficulty":2},
{"name":"分段点可导性","desc":"分段函数在分界点需左右导数均存在","key_formula":"","difficulty":2},
{"name":"复合函数可导性","desc":"外层可导且内层在该点可导则复合可导","key_formula":"","difficulty":3},
{"name":"导数几何意义","desc":"切线斜率与法线方程","key_formula":"切线:y-f(x0)=f'(x0)(x-x0)","difficulty":1}
]}]}

现在处理：
章：{chapter}
小节：
{sections}
"""


PROMPT2 = PROMPT + """

【重要】上一轮输出不完整，请务必覆盖上面列出的**每一个**小节，每个小节都要有 points。
若输出可能较长，请优先保证每个小节至少有 4 个知识点；只输出 JSON。"""


async def build_one(chapter: str, secs: list[dict], batch_id: int, retry: bool = False):
    name = f"kp_batch_{batch_id}.json" if not retry else f"kp_batch_{batch_id}_r1.json"
    cached = load_json(name)
    if cached:
        print(f"  批次 {batch_id} 已缓存，跳过")
        return cached

    base = PROMPT2 if retry else PROMPT
    # 注意：PROMPT 内含 JSON 示例（花括号），不能用 str.format
    prompt = base.replace("{chapter}", chapter).replace(
        "{sections}", "\n".join(f"- {x.name}" for x in secs)
    )
    res = await call_llm(prompt, max_tokens=12000)
    sections = res.get("sections") if isinstance(res, dict) else None
    got = {
        (s.get("section") or "").strip() for s in sections if isinstance(s, dict)
    } if isinstance(sections, list) else set()
    want = {x.name for x in secs}
    missing = want - got
    if missing:
        print(f"  批次 {batch_id} 缺 {len(missing)} 节：{list(missing)[:2]}")
    save_json(name, res)
    return res


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 批（调试）")
    args = ap.parse_args()

    with Session(engine) as s:
        secs = [
            r for r in s.exec(select(KnowledgePoint).order_by(KnowledgePoint.id)).all()
            if r.level == 2
        ]
        # 已入库的 (父节, 知识点名) 用于增量去重
        existing_keys = {
            (r.parent_id, r.name)
            for r in s.exec(select(KnowledgePoint)).all()
            if r.level == 3
        }
    if existing_keys:
        print(f"已存在 {len(existing_keys)} 个 L3 知识点，本次增量补齐")

    batches = [
        secs[i : i + args.batch_size] for i in range(0, len(secs), args.batch_size)
    ]
    if args.limit:
        batches = batches[: args.limit]
    print(f"共 {len(secs)} 节 → {len(batches)} 批（每批 {args.batch_size} 节），并发 {args.concurrency}")

    results = await run_pool(
        [build_one(b[0].chapter, b, i + 1) for i, b in enumerate(batches)],
        concurrency=args.concurrency,
        desc="知识点细分",
    )

    # 补跑：缺失小节的批次（重试提示词，仍失败则拆半再试）
    retry_jobs, retry_batches = [], []
    for i, b in enumerate(batches):
        r = results[i]
        sections = r.get("sections") if isinstance(r, dict) else None
        got = {
            (s.get("section") or "").strip()
            for s in sections
            if isinstance(s, dict)
        } if isinstance(sections, list) else set()
        want = {x.name for x in b}
        missing = [x for x in b if x.name not in got]
        if missing:
            retry_jobs.append(build_one(b[0].chapter, missing, i + 1, retry=True))
            retry_batches.append((i + 1, missing))
    if retry_jobs:
        print(f"\n补跑 {len(retry_jobs)} 个不完整批次")
        retry_results = await run_pool(
            retry_jobs, concurrency=args.concurrency, desc="补跑"
        )
        for (bid, missing), rr in zip(retry_batches, retry_results):
            results[bid - 1].setdefault("sections", [])
            if isinstance(rr, dict) and "_error" not in rr:
                results[bid - 1]["sections"].extend(rr.get("sections", []))

    ok = [r for r in results if r and "_error" not in r]
    print(f"\n成功批次：{len(ok)}/{len(results)}")
    total_pts = sum(
        len(sec.get("points", [])) for x in ok for sec in x.get("sections", [])
    )
    print(f"本批知识点：{total_pts} 个")

    # 入库
    with Session(engine) as s:
        name_map = {
            r.name: r.id for r in s.exec(select(KnowledgePoint)).all() if r.level == 2
        }
        existing_keys = {
            (r.parent_id, r.name)
            for r in s.exec(select(KnowledgePoint)).all()
            if r.level == 3
        }
        added = 0
        for x in ok:
            for sec in x.get("sections", []):
                sec_name = (sec.get("section") or "").strip()
                parent = name_map.get(sec_name)
                if parent is None:
                    # 名称不完全一致时按包含关系兜底
                    cand = [k for k in name_map if k and (k in sec_name or sec_name in k)]
                    parent = name_map[cand[0]] if cand else None
                if parent is None:
                    print(f"  ! 未找到节：{sec_name}")
                    continue
                parent_row = s.get(KnowledgePoint, parent)
                for order, p in enumerate(sec.get("points", []), 1):
                    nm = (p.get("name") or "").strip()
                    if not nm or (parent, nm) in existing_keys:
                        continue
                    s.add(
                        KnowledgePoint(
                            level=3,
                            name=nm,
                            parent_id=parent,
                            chapter=parent_row.chapter,
                            order_no=order,
                            desc=(p.get("desc") or "").strip() or None,
                            key_formula=(p.get("key_formula") or "").strip() or None,
                            difficulty_hint=p.get("difficulty"),
                            source="LLM从书签节标题细分",
                        )
                    )
                    existing_keys.add((parent, nm))
                    added += 1
        s.commit()
        total3 = len([r for r in s.exec(select(KnowledgePoint)).all() if r.level == 3])
        print(f"本次新增 L3 知识点：{added} 个（表内合计 {total3}）")


if __name__ == "__main__":
    asyncio.run(main())