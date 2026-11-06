"""步骤 6：跨页题目补全。

背景：一页放不下题目时，「题干/答案/详解」会跨页，导致答案缺失或详解被截断
（提取时模型会打上 [跨页续] 标记）。

做法：把「本页底部条带 + 下页顶部条带」纵向拼接成一张图，带题干上下文送模型补全，
再回写 answer / solution。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/kb/06_crosspage.py --dry-run     # 只看会处理哪些题
    .venv/Scripts/python.exe scripts/kb/06_crosspage.py --concurrency 2
"""

import argparse
import asyncio
import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.kb.common import BACKEND_DIR, call_llm, run_pool  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module  # noqa: E402

_c = import_module("04_extract")

sys.path.insert(0, str(BACKEND_DIR))
from app.db import engine  # noqa: E402
from app.models import KBProblem  # noqa: E402

PAGES_DIR = BACKEND_DIR / "_kb_out" / "pages"
BOTTOM_RATIO = 0.22   # 取本页底部 22%
TOP_RATIO = 0.26      # 取下页顶部 26%

PROMPT = """图片是同一道题跨页的两部分：上半部分来自本页末尾（含题干/选项/解答开头），下半部分来自下一页开头（解答续）。两图已纵向拼接，中间的空白是拼接缝。

请补全这道题，**只输出 JSON**：
{"answer":"最终答案（简明）","solution":"完整的解答步骤（合并两段，衔接自然，去掉跨页造成的断句）","continued":true}

要求：
- 如果解答在图片中已完整可见，也照样完整转写。
- 不要添加图片中没有的内容；看不清的地方用 "[不清晰]" 标记。
- 只输出 JSON。"""


def candidates(session) -> list[KBProblem]:
    """需要补全的题：答案缺失 或 详解带跨页标记。"""
    rows = session.exec(select(KBProblem).order_by(KBProblem.source_page)).all()
    return [
        p
        for p in rows
        if p.source_page and (not p.answer or "[跨页续]" in (p.solution or ""))
    ]


def build_context_image(p: KBProblem) -> str | None:
    """拼接「本页底部 + 下页顶部」为一张 base64 PNG。"""
    cur = PAGES_DIR / f"page_{p.source_page:04d}.png"
    nxt = PAGES_DIR / f"page_{p.source_page + 1:04d}.png"
    if not cur.exists():
        import_module("03_render").render([p.source_page], 2.0)
    if not nxt.exists():
        import_module("03_render").render([p.source_page + 1], 2.0)
    if not (cur.exists() and nxt.exists()):
        return None

    with Image.open(cur) as a, Image.open(nxt) as b:
        a = a.convert("RGB")
        b = b.convert("RGB")
        ta = a.crop((0, int(a.height * (1 - BOTTOM_RATIO)), a.width, a.height))
        tb = b.crop((0, 0, b.width, int(b.height * TOP_RATIO)))
        gap = 12
        canvas = Image.new("RGB", (max(ta.width, tb.width), ta.height + gap + tb.height), "white")
        canvas.paste(ta, (0, 0))
        canvas.paste(tb, (0, ta.height + gap))
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()


async def fix_one(p_id: int, dry_run: bool) -> dict:
    with Session(engine) as s:
        p = s.get(KBProblem, p_id)
        if p is None:
            return {"_error": "题目不存在", "id": p_id}
        info = {
            "id": p.id,
            "no": p.problem_no,
            "page": p.source_page,
            "has_answer": bool(p.answer),
            "has_continue_mark": "[跨页续]" in (p.solution or ""),
        }
        if dry_run:
            return info

        img = build_context_image(p)
        if not img:
            return {"_error": "拼接图构建失败", **info}

        prompt = (
            f"题号【{p.problem_no}】，题干：{(p.stem or '')[:200]}\n"
            f"已有部分解答：{(p.solution or '')[:300]}\n\n" + PROMPT
        )
        res = await call_llm(prompt, images=[img], max_tokens=8000)
        ans = (res.get("answer") or "").strip()
        sol = (res.get("solution") or "").strip()
        if not ans and not sol:
            return {"_error": "模型未返回内容", **info}

        with Session(engine) as s:
            p = s.get(KBProblem, p_id)
            if ans:
                p.answer = ans
            if sol:
                p.solution = sol.replace("[跨页续]", "").strip()
            p.extract_status = "ok"
            s.add(p)
            s.commit()
            return {
                "id": p.id,
                "no": p.problem_no,
                "page": p.source_page,
                "fixed": True,
                **info,
            }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()

    with Session(engine) as s:
        cands = candidates(s)
    print(f"跨页候选题：{len(cands)} 道")
    for p in cands:
        print(f"  【{p.problem_no}】p{p.source_page} 有答案={bool(p.answer)} 跨页标记={'[跨页续]' in (p.solution or '')}")
    if args.dry_run or not cands:
        return

    print(f"\n开始补全（并发 {args.concurrency}）…")
    results = await run_pool(
        [fix_one(p.id, False) for p in cands],
        concurrency=args.concurrency,
        desc="跨页补全",
    )
    ok = [r for r in results if r.get("fixed")]
    print(f"\n补全完成：{len(ok)}/{len(cands)}")

    with Session(engine) as s:
        remain = candidates(s)
        if remain:
            print(f"仍需人工处理：{[(p.problem_no, p.source_page) for p in remain]}")
        else:
            print("全部跨页题已补全 ✓")


if __name__ == "__main__":
    asyncio.run(main())