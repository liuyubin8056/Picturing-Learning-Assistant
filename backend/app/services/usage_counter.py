"""接口访问计数（按人按天）。

只在登录用户通过认证时 +1，用来在管理后台展示「API 访问量」。
内存累加 + 定时批量落库：SQLite 逐条写会 fsync，热路径上没必要。
"""

import threading
from collections import Counter
from datetime import datetime, timezone

from sqlmodel import Session, select

from ..models import ApiHit

_lock = threading.Lock()
_hits: Counter[tuple[int, str]] = Counter()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def hit(user_id: int | None) -> None:
    """记录一次访问。失败绝不影响主流程，调用方不用 try。"""
    if not user_id:
        return
    try:
        with _lock:
            _hits[(user_id, _today())] += 1
    except Exception:
        pass


def flush(session: Session) -> int:
    """把内存计数落库，返回写入的条目数。"""
    with _lock:
        if not _hits:
            return 0
        batch = dict(_hits)
        _hits.clear()

    n = 0
    for (uid, day), cnt in batch.items():
        row = session.exec(
            select(ApiHit).where(ApiHit.user_id == uid, ApiHit.day == day)
        ).first()
        if row:
            row.count += cnt
            session.add(row)
        else:
            session.add(ApiHit(user_id=uid, day=day, count=cnt))
        n += 1
    session.commit()
    return n


def pending() -> int:
    with _lock:
        return sum(_hits.values())
