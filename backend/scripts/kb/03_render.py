"""步骤 3：渲染 PDF 页面为 PNG（知识库图像来源）。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/kb/03_render.py --pages 12-20 --zoom 2.0
    .venv/Scripts/python.exe scripts/kb/03_render.py --all --zoom 2.0
"""

import argparse
from pathlib import Path

import pymupdf

from common import BACKEND_DIR, find_pdf

RENDER_DIR = BACKEND_DIR / "_kb_out" / "pages"


def render(pages: list[int], zoom: float, out_dir: Path = RENDER_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(find_pdf())
    paths = []
    for pno in pages:
        if not (1 <= pno <= doc.page_count):
            print(f"  ! 页码越界：{pno}")
            continue
        out = out_dir / f"page_{pno:04d}.png"
        if not out.exists():
            pix = doc[pno - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            pix.save(out)
        paths.append(out)
    return paths


def parse_pages(spec: str, total: int) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return [p for p in pages if 1 <= p <= total]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="", help="如 12-20,25,30")
    ap.add_argument("--all", action="store_true", help="全书渲染")
    ap.add_argument("--zoom", type=float, default=2.0)
    args = ap.parse_args()

    doc = pymupdf.open(find_pdf())
    total = doc.page_count
    pages = list(range(1, total + 1)) if args.all else parse_pages(args.pages, total)
    if not pages:
        print("未指定页面")
        return
    paths = render(pages, args.zoom)
    size_kb = sum(p.stat().st_size for p in paths) // 1024
    print(f"已渲染 {len(paths)} 页 → {RENDER_DIR}（共 {size_kb // 1024} MB，zoom={args.zoom}）")
    if paths:
        print(f"示例：{paths[0].name}")


if __name__ == "__main__":
    main()