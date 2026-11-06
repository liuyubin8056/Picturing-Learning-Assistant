"""清理测试用户数据，只保留演示用户（默认 1001）。

用途：把 dev.db 随仓库发布前，删除开发过程中的零散测试数据，
      让队友克隆后看到干净的起点 + 一个完整的演示账号。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/clean_test_users.py                # 保留 1001
    .venv/Scripts/python.exe scripts/clean_test_users.py --keep 1001,1  # 额外保留某用户
    .venv/Scripts/python.exe scripts/clean_test_users.py --dry-run      # 只看不动
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.models import (  # noqa: E402
    DiagnosisReport,
    Mastery,
    ProfileMeta,
    Question,
    TestQuestion,
    TestSession,
    TokenUsage,
    WrongBook,
)

DEMO_USER = 1001


def collect_user_ids(s: Session) -> set[int]:
    """从各表收集出现过的 user_id。"""
    ids: set[int] = set()
    for model in (Question, TestSession, Mastery, WrongBook, DiagnosisReport, TokenUsage):
        for uid in s.exec(select(model.user_id).distinct()).all():
            if uid is not None:
                ids.add(uid)
    for pm in s.exec(select(ProfileMeta)).all():
        ids.add(pm.user_id)
    return ids


def delete_user(s: Session, uid: int) -> dict[str, int]:
    """删除单个用户的全部学习数据，返回各类删除条数。"""
    counts: dict[str, int] = {}

    def wipe(model, *conds) -> int:
        stmt = select(model)
        if conds:
            stmt = stmt.where(*conds)
        rows = s.exec(stmt).all()
        for r in rows:
            s.delete(r)
        return len(rows)

    counts["questions"] = wipe(Question, Question.user_id == uid)
    sessions = s.exec(select(TestSession).where(TestSession.user_id == uid)).all()
    tq = 0
    for t in sessions:
        for row in s.exec(select(TestQuestion).where(TestQuestion.session_id == t.id)).all():
            s.delete(row)
            tq += 1
        s.delete(t)
    counts["test_sessions"] = len(sessions)
    counts["test_questions"] = tq
    counts["mastery"] = wipe(Mastery, Mastery.user_id == uid)
    counts["wrongbook"] = wipe(WrongBook, WrongBook.user_id == uid)
    counts["diagnosis"] = wipe(DiagnosisReport, DiagnosisReport.user_id == uid)
    counts["tokens"] = wipe(TokenUsage, TokenUsage.user_id == uid)
    pm = s.get(ProfileMeta, uid)
    if pm:
        s.delete(pm)
        counts["profile_meta"] = 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", default=str(DEMO_USER), help="要保留的用户 ID，逗号分隔")
    ap.add_argument("--dry-run", action="store_true", help="只统计不删除")
    args = ap.parse_args()

    keep = {int(x) for x in args.keep.replace(" ", "").split(",") if x.strip().isdigit()}
    print(f"保留用户：{sorted(keep)}")

    with Session(engine) as s:
        ids = collect_user_ids(s)
        targets = sorted(ids - keep)
        print(f"现存有数据的用户：{sorted(ids)}")
        print(f"将清理：{targets or '（无）'}")

        if not targets:
            print("无需清理。")
            return 0
        if args.dry_run:
            print("[dry-run] 未执行删除")
            return 0

        total: dict[str, int] = {}
        for uid in targets:
            c = delete_user(s, uid)
            print(f"  用户 {uid}: " + ", ".join(f"{k}={v}" for k, v in c.items() if v))
            for k, v in c.items():
                total[k] = total.get(k, 0) + v
        s.commit()
        print("清理完成，合计：" + ", ".join(f"{k}={v}" for k, v in total.items()))
        print(f"\n保留用户 {sorted(keep)} 的数据完好。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
