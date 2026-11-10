#!/usr/bin/env python
"""SQLite 数据库备份：安全、可校验、自动清理旧文件。

为什么不用 cp：
    SQLite 在写入过程中直接复制文件，可能拿到「半写」状态，恢复后报
    "database disk image is malformed"。sqlite3 的 backup API 会加锁做一致性快照。

用法：
    python scripts/backup_db.py                    # 备份到 ./backups，保留 7 天
    python scripts/backup_db.py --keep 30          # 保留 30 天
    python scripts/backup_db.py --out /data/bak    # 指定目录
    python scripts/backup_db.py --db other.db      # 指定数据库

cron（宿主机部署，每天 3:20）：
    20 3 * * * cd /opt/learnmate/backend && .venv/bin/python scripts/backup_db.py --keep 7 >> /var/log/learnmate-backup.log 2>&1

cron（Docker 部署，容器里有 Python）：
    20 3 * * * cd /opt/learnmate && docker compose -f deploy/docker-compose.yml exec -T api python scripts/backup_db.py --out /app/backups --keep 7 >> /var/log/learnmate-backup.log 2>&1

退出码：0 成功；1 失败（便于 cron 报警）。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def backup(src: Path, dst: Path) -> int:
    """用 backup API 做一致性快照，返回备份文件大小。"""
    if not src.exists():
        raise FileNotFoundError(f"数据库不存在：{src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    # src 用普通连接（需要读锁），dst 新建
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30) as s, \
         sqlite3.connect(dst, timeout=30) as d:
        s.backup(d)
    return dst.stat().st_size


def verify(path: Path) -> tuple[bool, str]:
    """校验备份可打开且完整，顺便报一下主要表的行数。"""
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
            ok = c.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                return False, f"完整性检查失败：{ok}"
            rows = []
            for table in ("users", "kb_problems", "questions", "test_sessions", "wrong_books"):
                try:
                    n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    rows.append(f"{table}={n}")
                except sqlite3.Error:
                    pass
            return True, " ".join(rows)
    except sqlite3.Error as e:
        return False, str(e)


def cleanup(folder: Path, keep_days: int) -> int:
    """删除超过保留期的备份（只匹配本脚本的命名模式）。"""
    if keep_days <= 0:
        return 0
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for f in folder.glob("dev-*.db"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="SQLite 一致性备份")
    ap.add_argument("--db", default=str(BASE_DIR / "dev.db"), help="源数据库")
    ap.add_argument("--out", default=str(BASE_DIR / "backups"), help="备份目录")
    ap.add_argument("--keep", type=int, default=7, help="保留天数（0 表示不清理）")
    args = ap.parse_args()

    src = Path(args.db)
    folder = Path(args.out)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = folder / f"dev-{stamp}.db"

    try:
        size = backup(src, dst)
    except Exception as e:  # noqa: BLE001 - 备份失败要让 cron 看到
        print(f"[失败] 备份出错：{e}", file=sys.stderr)
        return 1

    ok, info = verify(dst)
    if not ok:
        print(f"[失败] 备份文件校验不通过：{dst}\n       {info}", file=sys.stderr)
        return 1

    removed = cleanup(folder, args.keep)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 备份完成 {dst.name} "
          f"({human(size)})  {info}"
          + (f"  清理旧备份 {removed} 个" if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
