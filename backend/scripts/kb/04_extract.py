"""步骤 4：多模态提取整页题目（题干/选项/答案/详解/知识点/难度/错因）+ 题目图像裁剪。

用法（在 backend/scripts/kb 下）：
    ../../.venv/Scripts/python.exe 04_extract.py --pages 51,13 --concurrency 2 --crop

结果缓存 _kb_out/extract_p{page}.json，失败可重跑；--ingest 写入 kb_problems 表。
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pymupdf
from sqlmodel import Session, select

from common import (
    BACKEND_DIR,
    b64_image,
    call_llm,
    find_pdf,
    load_json,
    run_pool,
    save_json,
)

sys.path.insert(0, str(BACKEND_DIR))
from app.db import engine  # noqa: E402
from app.models import KBProblem, KnowledgePoint  # noqa: E402

RENDER_DIR = BACKEND_DIR / "_kb_out" / "pages"
CROP_DIR = BACKEND_DIR / "kb_images" / "problems"

# 页面上下有页眉/页脚，正文大致在 6%~95% 之间，裁剪时做下限保护
BODY_TOP, BODY_BOTTOM = 0.055, 0.955

PROMPT = """你是高等数学题库的题目录入助手。图片是《高等数学习题精选精解》的一整页扫描图，页眉是「章 / 节」，页脚是页码。请把这一页中的**每一道题**完整提取为结构化数据。

要求：
1. 只提取题目本身（从题号到解答结束），不要提取页眉、页脚、页码。
2. 题号取【】中的数字，如 140 → "no": "140"。
3. type 取值：choice 单选 / multiple 多选 / judge 判断 / fill 填空 / solve 解答题。
4. stem 为题干纯文本，数学公式用 LaTeX（行内 $...$）。选择/判断题不要把选项写进 stem。
5. options 仅选择题有，格式 [{"key":"A","text":"..."}]；answer 给出标准答案（选择题填字母，如 "A"）。
6. solution 为书上的解答步骤（可用 LaTeX，转成简洁文本，去掉"故选(A)"之外的冗余）。填空/解答题给出完整推导。
7. kp_names 从下面给定的知识点清单中挑选最匹配的 1~3 个（必须原样使用清单中的名称）。
8. difficulty：1=基础 2=中等 3=挑战。
9. error_tags：本题的典型易错点，取值从 概念不清 / 方法缺失 / 审题偏差 / 计算粗心 里选，可多选，无则填 []。
10. crop_ratio：该题内容（题干到解答最后一行）在本页中的**纵向范围** [起, 止]，取值 0~1，精确到两位小数。务必让区间恰好框住本题，不要框入相邻题目。
11. 若某题内容跨页未完整显示，仍然提取可见部分，并在 solution 末尾加 "[跨页续]"。

只输出 JSON，不要解释文字。输出格式：
{"problems":[{"no":"140","type":"choice","stem":"...","options":[{"key":"A","text":"..."}],"answer":"A","solution":"...","kp_names":["..."],"difficulty":2,"error_tags":["概念不清"],"crop_ratio":[0.12,0.42]}]}

本节知识点清单（kp_names 只能从中选择）：
{kps}"""


def page_section_map() -> dict[int, tuple[str, str]]:
    """物理页 → (章, 节)。"""
    with Session(engine) as s:
        secs = [
            r for r in s.exec(select(KnowledgePoint).order_by(KnowledgePoint.id)).all()
            if r.level == 2
        ]
    out = {}
    for sec in secs:
        for p in range(sec.start_page, sec.end_page + 1):
            out[p] = (sec.chapter, sec.name)
    return out


def kps_by_section() -> dict[str, list[str]]:
    """节名 → L3 知识点名清单。"""
    with Session(engine) as s:
        rows = s.exec(select(KnowledgePoint).order_by(KnowledgePoint.id)).all()
    kp_parent = {r.id: r.name for r in rows if r.level == 2}
    out: dict[str, list[str]] = {}
    for r in rows:
        if r.level == 3 and r.parent_id in kp_parent:
            out.setdefault(kp_parent[r.parent_id], []).append(r.name)
    return out


async def extract_page(page: int, sec_name: str, kps: list[str], need_crop: bool):
    cached = load_json(f"extract_p{page}.json")
    if cached:
        print(f"  p{page} 已缓存，跳过")
        return cached

    png = RENDER_DIR / f"page_{page:04d}.png"
    if not png.exists():
        from importlib import import_module

        r = import_module("03_render")
        r.render([page], 2.0)

    prompt = PROMPT.replace("{kps}", "\n".join(f"- {k}" for k in kps) or "- （无）")
    img = b64_image(png)
    # 提取任务输出较大（多题题干+详解），显式给足 token
    res = await call_llm(prompt, images=[img], max_tokens=12000)
    problems = res.get("problems")
    if not isinstance(problems, list) or not problems:
        return {"_error": "未提取到题目", "raw": str(res)[:300]}
    res["_page"] = page
    res["_section"] = sec_name
    save_json(f"extract_p{page}.json", res)
    return res


def ocr_span(page: int, problem_no) -> dict | None:
    """取 OCR 定位的精确切分区间（题号顶 → 下一题号顶）。"""
    d = load_json(f"ocr_p{page}.json")
    if not d:
        return None
    for s in d.get("spans", []):
        if str(s.get("no")) == str(problem_no):
            return s
    return None


def crop_problems(page: int, problems: list[dict]) -> list[str | None]:
    """裁剪题目区域：优先用 OCR 精确定位，缺数据时回退模型给的 crop_ratio。

    OCR 用 05_ocr_probe.py 生成，能根治「顶部混入上一题末行」；
    OCR 未检出的题号（如题号压在页底）自动回退到模型比例。
    """
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(find_pdf())
    pg = doc[page - 1]
    rect = pg.rect
    zoom = 2.0
    ocr = load_json(f"ocr_p{page}.json")
    img_h = ocr["img_size"][1] if ocr else 0

    paths = []
    for i, p in enumerate(problems):
        no = p.get("no")
        ratio = p.get("crop_ratio")
        y0 = y1 = None

        sp = ocr_span(page, no)
        if sp:
            # OCR 像素坐标 → PDF 比例坐标
            y0 = max(BODY_TOP, sp["y_top"] / img_h)
            y1 = min(BODY_BOTTOM, sp["y_bottom"] / img_h)
            p["crop_source"] = "ocr"
        elif isinstance(ratio, list) and len(ratio) == 2:
            y0 = max(BODY_TOP, min(float(ratio[0]), BODY_BOTTOM - 0.02))
            y1 = min(BODY_BOTTOM, max(float(ratio[1]), y0 + 0.03))
            # 模型给的区间通常略宽，两端内收，避免混入相邻题目的残留行
            pad = min(0.015, (y1 - y0) * 0.12)
            y0 += pad
            y1 -= pad * 0.4
            p["crop_source"] = "model_ratio"

        if y0 is None or y1 is None:
            paths.append(None)
            continue
        clip = pymupdf.Rect(
            rect.x0, rect.y0 + rect.height * y0, rect.x1, rect.y0 + rect.height * y1
        )
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        out = CROP_DIR / f"p{page:04d}_q{no if no is not None else i}.png"
        pix.save(out)
        p["crop_image_path"] = f"kb_images/problems/{out.name}"
        paths.append(str(out))
    return paths


def ingest(results: list[dict]):
    with Session(engine) as s:
        all_rows = s.exec(select(KnowledgePoint)).all()
        sec_rows = {r.name: r for r in all_rows if r.level == 2}
        kp_parent_name = {r.id: r.name for r in all_rows if r.level == 2}
        kp_by_name: dict[str, int] = {}
        for r in all_rows:
            if r.level == 3:
                kp_by_name[r.name] = r.id
                if r.parent_id in kp_parent_name:
                    kp_by_name[f"{kp_parent_name[r.parent_id]}||{r.name}"] = r.id

        added = 0
        for res in results:
            if not res or "_error" in res:
                continue
            page = res.get("_page")
            section = res.get("_section")
            sec_row = sec_rows.get(section)
            chapter = sec_row.chapter if sec_row else (section or None)
            for p in res.get("problems", []):
                ids = [
                    kp_by_name.get(f"{section}||{n}") or kp_by_name.get(n)
                    for n in p.get("kp_names", [])
                ]
                ids = [i for i in ids if i]
                qtype = (p.get("type") or "").strip()
                s.add(
                    KBProblem(
                        problem_no=str(p.get("no")) if p.get("no") is not None else None,
                        chapter=chapter,
                        section=section,
                        kp_ids=json.dumps(ids, ensure_ascii=False),
                        question_type=qtype,
                        stem=(p.get("stem") or "").strip() or None,
                        options=json.dumps(p.get("options"), ensure_ascii=False)
                        if p.get("options")
                        else None,
                        answer=(p.get("answer") or "").strip() or None,
                        solution=(p.get("solution") or "").strip() or None,
                        difficulty=p.get("difficulty"),
                        error_tags=json.dumps(p.get("error_tags"), ensure_ascii=False)
                        if p.get("error_tags")
                        else None,
                        is_objective=qtype in ("choice", "multiple", "judge", "fill"),
                        source_page=page,
                        book_page=page - 10,
                        page_image_path=f"_kb_out/pages/page_{page:04d}.png",
                        crop_image_path=p.get("crop_image_path"),
                        raw_json=json.dumps(p, ensure_ascii=False),
                    )
                )
                added += 1
        s.commit()
        print(f"已入库题目：{added} 道")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", required=True, help="如 51,13-16")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--crop", action="store_true", help="生成题目裁剪图")
    ap.add_argument("--ingest", action="store_true", help="写入 kb_problems 表")
    args = ap.parse_args()

    doc = pymupdf.open(find_pdf())
    pages = []
    for part in args.pages.split(","):
        if "-" in part:
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    pages = [p for p in pages if 1 <= p <= doc.page_count]

    sec_map = page_section_map()
    kps_map = kps_by_section()
    print(f"待提取 {len(pages)} 页，并发 {args.concurrency}")

    coros = []
    for p in pages:
        chapter, sec = sec_map.get(p, (None, None))
        kps = kps_map.get(sec, [])
        coros.append(extract_page(p, sec, kps, args.crop))

    results = await run_pool(coros, concurrency=args.concurrency, desc="题目提取")

    ok = [r for r in results if r and "_error" not in r]
    total = sum(len(r.get("problems", [])) for r in ok)
    print(f"\n成功页面：{len(ok)}/{len(results)}，共提取 {total} 道题")

    for r in ok:
        print(f"  p{r['_page']} [{r['_section']}] {len(r['problems'])} 题")

    if args.crop:
        for r in ok:
            paths = crop_problems(r["_page"], r["problems"])
            n = sum(1 for x in paths if x)
            print(f"  p{r['_page']} 裁剪 {n}/{len(paths)} 张题目图")
        if ok:
            for r in ok:
                save_json(f"extract_p{r['_page']}.json", r)

    if args.ingest and ok:
        ingest(ok)


if __name__ == "__main__":
    asyncio.run(main())