"""清理超时未完成的分片上传（默认 24 小时）。

用法：
    python scripts/sweep_uploads.py            # 清理 24 小时前的
    python scripts/sweep_uploads.py --hours 6  # 自定义阈值

建议配 cron 每天跑一次，避免用户传到一半就放弃的分片长期占用磁盘。
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.services.upload_service import sweep_stale  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()

    with Session(engine) as s:
        n = sweep_stale(s, timedelta(hours=args.hours))
    print(f"清理超时上传 {n} 个（阈值 {args.hours} 小时）")


if __name__ == "__main__":
    main()
