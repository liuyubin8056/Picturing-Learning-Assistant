"""OCR 定位实测：验证 RapidOCR 能否稳定定位题号坐标，用于精确切分题目区域。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/kb/05_ocr_probe.py --pages 51,13
输出：
    _kb_out/ocr_p{page}.json  —— 每页 OCR 结果（文本块 + 坐标 + 是否题号）
    控制台报告：题号检出情况 / 坐标分布 / 与模型 crop_ratio 的偏差
"""

import argparse
import re
import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.kb.common import load_json, save_json  # noqa: E402

RENDER_DIR = import_module("03_render").RENDER_DIR

# 书内题号形如 【140】（OCR 常与题干合并在同一文本块内，故用 search）
NUM_RE = re.compile(r"【\s*(\d{1,4})\s*】")


def init_ocr():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def probe_page(page: int, ocr) -> dict:
    cached = load_json(f"ocr_p{page}.json")
    if cached:
        print(f"  p{page} 已缓存")
        return cached

    png = RENDER_DIR / f"page_{page:04d}.png"
    if not png.exists():
        from importlib import import_module

        import_module("03_render").render([page], 2.0)

    res, _ = ocr(str(png))
    blocks = []
    for item in res or []:
        box, text, score = item[0], item[1], item[2]
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        blocks.append(
            {
                "text": text.strip(),
                "score": round(float(score), 3),
                "x0": round(min(xs), 1),
                "y0": round(min(ys), 1),
                "x1": round(max(xs), 1),
                "y1": round(max(ys), 1),
            }
        )
    blocks.sort(key=lambda b: b["y0"])

    # 题号候选：在文本块内搜索「【数字】」（OCR 常把题号与题干合并成同一块）
    from PIL import Image

    with Image.open(png) as im:
        img_w, img_h = im.size

    numbers = []
    for b in blocks:
        # 「【数字】」在正文中极少见（仅题号使用），位置判定放宽到左侧 30%
        if b["x0"] > img_w * 0.30:
            continue
        m = NUM_RE.search(b["text"])
        if m and b["score"] >= 0.6:
            numbers.append(
                {
                    "no": m.group(1),
                    "y0": b["y0"],
                    "y1": b["y1"],
                    "x0": b["x0"],
                    "score": b["score"],
                    "text": b["text"][:40],
                }
            )
    numbers.sort(key=lambda n: n["y0"])

    # 精确切分区间：本题号顶 → 下一题号顶（末题取页面正文底部）
    spans = []
    for i, n in enumerate(numbers):
        top = n["y0"]
        bottom = numbers[i + 1]["y0"] - 4 if i + 1 < len(numbers) else img_h * 0.95
        spans.append({"no": n["no"], "y_top": top, "y_bottom": bottom})

    out = {
        "page": page,
        "img_size": [img_w, img_h],
        "block_count": len(blocks),
        "numbers": numbers,
        "spans": spans,
        "blocks": blocks,
    }
    save_json(f"ocr_p{page}.json", out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="51,13")
    args = ap.parse_args()

    pages = []
    for part in args.pages.split(","):
        if "-" in part:
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))

    print("初始化 OCR 引擎（首次较慢）…")
    ocr = init_ocr()
    print("OCR 就绪\n")

    for p in pages:
        d = probe_page(p, ocr)
        img_h = d["img_size"][1]
        nums = d["numbers"]
        print(f"=== p{p} ===")
        print(f"  图像尺寸 {d['img_size']}，文本块 {d['block_count']}，检出题号 {len(nums)}")
        for n in nums:
            print(
                f"    【{n['no']}】 y={n['y0']:.0f}~{n['y1']:.0f} "
                f"({n['y0']/img_h:.3f}) conf={n['score']} | {n['text']}"
            )
        if d["spans"]:
            print("  精确切分区间（OCR 定位）：")
            for s in d["spans"]:
                print(
                    f"    【{s['no']}】 y={s['y_top']:.0f}~{s['y_bottom']:.0f} "
                    f"比例 {s['y_top']/img_h:.3f}~{s['y_bottom']/img_h:.3f}"
                )
        print()


if __name__ == "__main__":
    main()