"""统一重裁：用最新的题干/解析切分逻辑重裁所有已提取页（不调模型，零成本）。

用途：提取过程中修复了切分逻辑（行顶部吸附、最小高度保护、语义锚点），
      旧逻辑产出的图可能有"细边""解析混入题干"等问题，此脚本一次性重裁。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/kb/08_recrop_all.py
再把新的图路径同步进数据库：
    .venv/Scripts/python.exe scripts/kb/04_extract.py --pages 1-501 --ingest   # 全部命中缓存，只更新库
"""

import json
import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
mod = import_module("04_extract")

KB_OUT = mod.BACKEND_DIR / "_kb_out"


def main() -> int:
    files = sorted(KB_OUT.glob("extract_p*.json"))
    pages = total_q = separated = rejected = no_split = 0

    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if "_page" not in d or not d.get("problems"):
            continue

        mod.crop_problems(d["_page"], d["problems"])
        mod.save_json(f.name, d)

        pages += 1
        for p in d["problems"]:
            total_q += 1
            if p.get("stem_image_path"):
                separated += 1
            elif p.get("split_rejected"):
                rejected += 1
            else:
                no_split += 1

    print(f"重裁完成：{pages} 页 / {total_q} 道题")
    print(f"  已分离题干+解析：{separated}")
    print(f"  题干过短被拒（回退整题图）：{rejected}")
    print(f"  无分界点（回退整题图）：{no_split}")
    if total_q:
        print(f"  分离成功率：{separated / total_q * 100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
