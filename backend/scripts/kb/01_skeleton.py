"""步骤 1：导出 PDF 书签骨架（章 / 节）并写入 knowledge_points 表。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/kb/01_skeleton.py
"""

import sys

import pymupdf
from sqlmodel import Session

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from scripts.kb.common import find_pdf, save_json  # noqa: E402

from app.db import engine  # noqa: E402
from app.models import KnowledgePoint  # noqa: E402


def build_skeleton():
    doc = pymupdf.open(find_pdf())
    toc = doc.get_toc()  # [level, title, page(0-based)]
    n_pages = doc.page_count

    chapters, sections = [], []
    for level, title, page in toc:
        if level == 1 and ("第" in title and "章" in title):
            chapters.append({"name": title.strip(), "page": page + 1})
        elif level == 2:
            sections.append({"name": title.strip(), "page": page + 1})

    # 节的起止页：由下一节/下一章书签推导
    marks = sorted(
        [{"page": s["page"], "kind": "section"} for s in sections]
        + [{"page": c["page"], "kind": "chapter"} for c in chapters],
        key=lambda m: m["page"],
    )

    def next_mark_page(page: int, kind: str = "any") -> int | None:
        """下一个标记的页码（严格大于当前页）；kind 限定章/节；无则 None。"""
        for m in marks:
            if m["page"] > page and (kind == "any" or m["kind"] == kind):
                return m["page"]
        return None

    # 章的结束页由「下一章」决定，节的结束页由「下一节或下一章」决定
    for c in chapters:
        nxt = next_mark_page(c["page"], "chapter")
        c["end_page"] = (nxt - 1) if nxt else n_pages
        c["order"] = chapters.index(c) + 1
    for s in sections:
        nxt = next_mark_page(s["page"])
        s["end_page"] = (nxt - 1) if nxt else n_pages
        # 归属章：节页码之前的最近一章
        s["chapter"] = None
        for c in chapters:
            if c["page"] <= s["page"]:
                s["chapter"] = c["name"]
            else:
                break
    return chapters, sections


def main():
    chapters, sections = build_skeleton()
    print(f"章：{len(chapters)}  节：{len(sections)}")
    for c in chapters:
        print(f"  {c['name']}  p{c['page']}~p{c['end_page']}")
    save_json("skeleton.json", {"chapters": chapters, "sections": sections})

    with Session(engine) as s:
        if s.query(KnowledgePoint).count() > 0:
            print("骨架已存在，跳过入库")
            return
        id_map = {}
        for c in chapters:
            kp = KnowledgePoint(
                level=1,
                name=c["name"],
                parent_id=None,
                chapter=c["name"],
                order_no=c["order"],
                start_page=c["page"],
                end_page=c["end_page"],
                source="吉米多维奇题集/书签目录",
            )
            s.add(kp)
            s.commit()
            s.refresh(kp)
            id_map[c["name"]] = kp.id
        for i, sec in enumerate(sections, 1):
            kp = KnowledgePoint(
                level=2,
                name=sec["name"],
                parent_id=id_map.get(sec["chapter"]),
                chapter=sec["chapter"],
                order_no=i,
                start_page=sec["page"],
                end_page=sec["end_page"],
                source="吉米多维奇题集/书签目录",
            )
            s.add(kp)
            s.commit()
            s.refresh(kp)
            id_map[sec["name"]] = kp.id
        print(f"已入库：章 {len(chapters)} 条 + 节 {len(sections)} 条 = {s.query(KnowledgePoint).count()} 条")


if __name__ == "__main__":
    main()