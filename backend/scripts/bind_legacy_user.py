"""把历史匿名账号绑定到指定邮箱（一次性数据迁移）。

背景：账户体系上线前，用户只有自增 id（1 / 7 / 1001），没有邮箱。
本脚本给某个老账号补上邮箱，让它能通过「邮箱验证码登录」进入，且原有
答疑 / 练习 / 错题 / 画像数据全部保留（数据都按 user_id 挂在原记录上）。

注意：email 有唯一约束（部分索引，NULL 可重复），**一个邮箱只能绑一个账号**。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/bind_legacy_user.py --user-id 1 --email you@qq.com
    .venv/Scripts/python.exe scripts/bind_legacy_user.py --user-id 1 --email you@qq.com --nickname 刘同学
    .venv/Scripts/python.exe scripts/bind_legacy_user.py --user-id 1 --email you@qq.com --dry-run
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.models import (  # noqa: E402
    Mastery,
    Question,
    TestSession,
    User,
    WrongBook,
)
from app.services import auth_service as auth  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, required=True, help="要绑定的历史账号 id")
    ap.add_argument("--email", required=True, help="绑定到的邮箱")
    ap.add_argument("--nickname", default=None, help="顺带设置昵称（可选）")
    ap.add_argument("--dry-run", action="store_true", help="只看结果不写库")
    args = ap.parse_args()

    email = auth.normalize_email(args.email)
    if not auth.is_valid_email(email):
        print(f"[错误] 邮箱格式不正确：{args.email}")
        return 1

    with Session(engine) as s:
        user = s.get(User, args.user_id)
        if not user:
            print(f"[错误] 用户 {args.user_id} 不存在")
            return 1

        if user.email and user.email != email:
            print(f"[错误] 用户 {args.user_id} 已绑定邮箱 {user.email}，请先解绑")
            return 1

        occupied = auth.get_user_by_email(s, email)
        if occupied and occupied.id != user.id:
            print(f"[错误] 邮箱 {email} 已被用户 {occupied.id} 占用（一个邮箱只能绑一个账号）")
            return 1

        # 统计该账号现有数据，确认绑定后能继续使用
        stats = {
            "答疑": len(s.exec(select(Question).where(Question.user_id == user.id)).all()),
            "练习": len(s.exec(select(TestSession).where(TestSession.user_id == user.id)).all()),
            "掌握度": len(s.exec(select(Mastery).where(Mastery.user_id == user.id)).all()),
            "错题": len(s.exec(select(WrongBook).where(WrongBook.user_id == user.id)).all()),
        }

        print(f"账号 {user.id}：" + "，".join(f"{k} {v} 条" for k, v in stats.items()))
        print(f"将绑定邮箱：{email}" + (f"，昵称：{args.nickname}" if args.nickname else ""))
        if args.dry_run:
            print("[dry-run] 未写入")
            return 0

        user.email = email
        if args.nickname:
            user.nickname = args.nickname
        s.add(user)
        s.commit()
        print(f"[完成] 账号 {user.id} 已绑定 {email}，可用邮箱验证码登录")
    return 0


if __name__ == "__main__":
    sys.exit(main())
