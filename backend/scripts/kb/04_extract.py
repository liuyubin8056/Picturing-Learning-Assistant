"""步骤 4：多模态提取整页题目（题干/选项/答案/详解/知识点/难度/错因）+ 题目图像裁剪。

用法（在 backend/scripts/kb 下）：
    ../../.venv/Scripts/python.exe 04_extract.py --pages 51,13 --concurrency 2 --crop

结果缓存 _kb_out/extract_p{page}.json，失败可重跑；--ingest 写入 kb_problems 表。
"""

import argparse
import asyncio
import json
import re
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
7. kp_names：从下面知识点清单中挑选**本题涉及的全部知识点**，通常 2~3 个（每题至少 1 个）；
   原题若有多个考点（如既考极限又考连续）都要标出，便于后续按知识点搜索与组卷。
   必须原样使用清单中的名称，不要自己改写。
8. difficulty：1=基础 2=中等 3=挑战。
9. error_tags：本题的典型易错点，取值从 概念不清 / 方法缺失 / 审题偏差 / 计算粗心 里选，可多选，无则填 []。
10. crop_ratio：该题内容（题号到解答最后一行）在本页中的**纵向范围** [起, 止]，取值 0~1，精确到两位小数。务必让区间恰好框住本题，不要框入相邻题目。
11. split_ratio：本题**题干结束、解答开始**的分界位置（单个数字，0~1，两位小数）。判断依据：最后一行选项（或题干末句）之后就是分界点，紧接着的推导/证明/计算内容属于解答。
    - 若本题没有解答（只有题干），split_ratio 填 null。
    - **重要**：题干如果附带坐标系、函数图像、几何示意图，这些图属于题干，分界点必须在图的下方，不能把图切到解答区。
12. 若某题内容跨页未完整显示，仍然提取可见部分，并在 solution 末尾加 "[跨页续]"。

只输出 JSON，不要解释文字。输出格式：
{"problems":[{"no":"140","type":"choice","stem":"...","options":[{"key":"A","text":"..."}],"answer":"A","solution":"...","kp_names":["..."],"difficulty":2,"error_tags":["概念不清"],"crop_ratio":[0.12,0.42],"split_ratio":0.27}]}

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
    # 提取任务输出较大（多题题干+详解）。deepseek-flash 是推理模型，
    # 思考 token 与正文共享 max_tokens：实测常见页面推理 18000~38600 字符
    # （约 12000 token），原设 12000 会被推理吃满导致正文为空
    # （finish_reason=length）。这里给到 32000，留足"思考 + JSON 正文"额度。
    res = await call_llm(prompt, images=[img], max_tokens=32000)
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


def resolve_split(
    page: int,
    lo: float,
    hi: float,
    model_split: float | None,
    crop_ratio: list | None,
) -> float | None:
    """把模型给的分界点落到 OCR 定位的本题区间内。

    模型对整页绝对坐标的估计存在偏移（实测题 10 给 0.42，实际本题在 0.48~0.58），
    但「题干占本题的比例」相对稳定，因此：
      - 绝对坐标在区间内 → 直接用；
      - 不在区间内 → 用 crop_ratio 换算成相对比例，再映射回 OCR 区间。
    """
    if model_split is None:
        return None
    if lo < model_split < hi:
        return model_split

    if isinstance(crop_ratio, list) and len(crop_ratio) == 2:
        try:
            c0, c1 = float(crop_ratio[0]), float(crop_ratio[1])
        except (TypeError, ValueError):
            return None
        if c1 - c0 > 0.01:
            rel = (model_split - c0) / (c1 - c0)
            rel = max(0.10, min(0.90, rel))  # 极端值夹紧，避免切到首尾行
            return lo + rel * (hi - lo)
    return None


def refine_split(page: int, lo: float, hi: float, model_split: float | None) -> float | None:
    """用 OCR 行边界校正「题干/解析」分界点（比例坐标）。

    模型对像素位置的估计只能到"大概"，实测会把选择题的 (C)(D) 选项切到解析图里。
    OCR 能给出每行的精确上下边界，因此：
      1. 分界不得高于**最后一个选项行**的底边（保证选项完整落在题干图里）；
      2. 分界吸附到最近的**行边界**，避免把某一行切成两半。
    """
    ocr = load_json(f"ocr_p{page}.json")
    if not ocr:
        return None
    h = ocr["img_size"][1]
    blocks = [
        b for b in ocr.get("blocks", [])
        if b["y0"] / h >= lo - 0.005 and b["y1"] / h <= hi + 0.005
    ]
    if not blocks:
        return None

    # ① 选项行下限
    opt_bottom = max(
        (
            b["y1"] / h
            for b in blocks
            if re.match(r"^[（(]?[A-D][）)．.、]", b["text"].strip())
        ),
        default=lo,
    )

    target = max(model_split or lo, opt_bottom + 0.004)

    # ② 语义锚点：解析通常以「解 / 证明 / 由 / 因为 / 根据」开头，
    #    OCR 对汉字识别较准，命中则直接作为分界（比纯几何吸附可靠）。
    #    注意用 startswith("解") 而非枚举"解设/解由/解令"——书中写法很多（解令、解当…）。
    #    "解"字在题干中出现极少，配合「在选项之后 + 距离约束」可避免误判。
    head_words = ("解", "证明", "由", "因为", "根据", "可见", "分析")
    for b in blocks:
        t = b["text"].strip()
        y0b = b["y0"] / h
        if y0b < opt_bottom - 0.002:      # 必须在所有选项之后
            continue
        if y0b <= lo + 0.012:
            continue
        if any(t.startswith(w) for w in head_words) and abs(y0b - target) < 0.15:
            return y0b if y0b < hi - 0.012 else None

    # ③ 回退：吸附到 target **之后**最近的行顶部。
    #    不能取"绝对值最近"——若 target 略高于题干行顶，会吸附回题干行本身，
    #    导致题干图只切到半行（实测 p23 题42 只剩一条细边）。
    edges = sorted({b["y0"] / h for b in blocks})
    if not edges:
        return None
    after = [e for e in edges if e >= target]
    snapped = min(after) if after else max(edges)
    # 题干至少要有 2 行高度；分界太靠上时往后找第一个满足的行顶部
    floor = lo + 0.030
    if snapped < floor:
        cand = [e for e in edges if e >= floor]
        snapped = min(cand) if cand else None
    if snapped is None or not (lo + 0.012 < snapped < hi - 0.012):
        return None
    return snapped


def crop_problems(page: int, problems: list[dict]) -> list[str | None]:
    """裁剪题目图像：整题图 + 题干图 + 解析图（题干/解析分离）。

    分工：
    - OCR（05_ocr_probe.py）负责**每题的上下边界**（题号顶 → 下一题号顶），精确且零成本；
    - 模型负责**题干与解析的分界点** split_ratio（语义判断，OCR 做不到）。

    这样练习时只给 stem 图（不含解析），判分后才给 solution 图，
    避免"题目里带着答案"。
    """
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(find_pdf())
    pg = doc[page - 1]
    rect = pg.rect
    # 1.5x 渲染：约 135dpi，公式清晰度足够；2.0x 时 3600 张图共 194MB，
    # 仓库随代码分发体积过大，降到 1.5x 后约减少 45%
    zoom = 1.5
    ocr = load_json(f"ocr_p{page}.json")
    img_h = ocr["img_size"][1] if ocr else 0

    def cut(y0: float, y1: float, suffix: str, no) -> str:
        """按纵向比例裁一张图并返回相对路径。

        整题图（suffix 为空）单独放 whole/：它只用于人工校对，
        体积占全部图片的三分之一，因此不随仓库分发（见 .gitignore）。
        """
        clip = pymupdf.Rect(
            rect.x0, rect.y0 + rect.height * y0, rect.x1, rect.y0 + rect.height * y1
        )
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        if suffix == "":
            out_dir = CROP_DIR / "whole"
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"p{page:04d}_q{no}.png"
            pix.save(out)
            return f"kb_images/whole/{out.name}"
        out = CROP_DIR / f"p{page:04d}_q{no}{suffix}.png"
        pix.save(out)
        return f"kb_images/problems/{out.name}"

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

        # ① 整题图（兼容旧逻辑）
        whole = cut(y0, y1, "", no if no is not None else i)
        p["crop_image_path"] = whole

        # ② 题干图 / 解析图：模型给大致分界，OCR 行边界做精确校正
        split = p.get("split_ratio")
        try:
            split = float(split) if split is not None else None
        except (TypeError, ValueError):
            split = None

        margin = (y1 - y0) * 0.04  # 分界处留少量余量，避免切掉半行
        split = resolve_split(page, y0, y1, split, ratio)
        refined = None
        if split is not None:
            refined = refine_split(page, y0, y1, split) or split
            p["split_refined"] = round(refined, 4)
        else:
            # 模型没给分界（早期 prompt 提取的旧数据）：
            # 以「题干约占本题 1/3」为先验，再让 OCR 锚点（选项行 / 解-证明-由 / 行顶部）校正。
            # 这比直接放弃多救回相当一批题，且零 token 成本。
            guess = y0 + (y1 - y0) * 0.35
            refined = refine_split(page, y0, y1, guess)
            if refined:
                p["split_refined"] = round(refined, 4)
                p["split_guess"] = "ocr_only"

        # 题干图必须有足够高度（约 2 行）。太薄说明分界点落在题干行内部，
        # 生成出来只会是一条细边，练习时看不到完整题目 → 宁可不分离。
        min_stem = 0.030
        if refined is not None and not (y0 + min_stem < refined < y1 - margin):
            p["split_rejected"] = "stem_too_short"
            refined = None
            # 清理上一轮可能残留的分离图路径，避免"拒绝了却还挂着旧图"
            p.pop("stem_image_path", None)
            p.pop("solution_image_path", None)

        if refined is not None:
            p["stem_image_path"] = cut(y0, refined, "_stem", no)
            p["solution_image_path"] = cut(refined, y1, "_sol", no)
            p["split_source"] = "model+ocr" if p.get("split_refined") else "model"
        else:
            # 没有可靠分界点：不生成分离图，前端回退用整题图
            p["split_source"] = "none"

        paths.append(str(CROP_DIR / f"p{page:04d}_q{no if no is not None else i}.png"))
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
        updated = 0
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
                pno = str(p.get("no")) if p.get("no") is not None else None
                payload = dict(
                    problem_no=pno,
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
                    stem_image_path=p.get("stem_image_path"),
                    solution_image_path=p.get("solution_image_path"),
                    raw_json=json.dumps(p, ensure_ascii=False),
                )
                # 按题号 upsert：全书题号唯一，重复跑脚本只更新不重复插入
                exist = (
                    s.exec(select(KBProblem).where(KBProblem.problem_no == pno)).first()
                    if pno
                    else None
                )
                if exist:
                    for k, v in payload.items():
                        setattr(exist, k, v)
                    updated += 1
                else:
                    s.add(KBProblem(**payload))
                    added += 1
        s.commit()
        print(f"已入库：新增 {added} 道，更新 {updated} 道")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", help="如 51,13-16")
    ap.add_argument(
        "--pages-file",
        help="从文件读取页码（每行/空格分隔），用于按待提取清单续跑，与 --pages 二选一",
    )
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--crop", action="store_true", help="生成题目裁剪图")
    ap.add_argument("--ingest", action="store_true", help="写入 kb_problems 表")
    args = ap.parse_args()

    doc = pymupdf.open(find_pdf())
    pages = []
    if args.pages_file:
        txt = Path(args.pages_file).read_text(encoding="utf-8")
        pages = [int(t) for t in txt.replace(",", " ").split() if t.isdigit()]
    elif args.pages:
        for part in args.pages.split(","):
            if "-" in part:
                a, b = part.split("-")
                pages.extend(range(int(a), int(b) + 1))
            else:
                pages.append(int(part))
    else:
        print("请用 --pages 或 --pages-file 指定页码")
        return
    pages = [p for p in dict.fromkeys(pages) if 1 <= p <= doc.page_count]

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