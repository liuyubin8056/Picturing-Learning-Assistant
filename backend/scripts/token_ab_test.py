"""画像注入与上下文裁剪的 A/B 实测（token 开销 + 缓存命中率 + 响应质量）。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/token_ab_test.py --user 7 --rounds 3

对照组 A：仅基础指令
实验组 B：基础指令 + L1 画像摘要（context_manager.compose）
实验组 C：B + L2 会话摘要 + L3 短期窗口（完整分层上下文）

输出：每组的 prompt/completion/reasoning/cache_hit 实测均值 + 结论。
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

from sqlmodel import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.llm.deepseek import DeepSeekClient  # noqa: E402
from app.services import context_manager as cm  # noqa: E402

TASK = """下面是一道题的库内解析，请按学生水平改写成讲解，控制在 200 字以内：
{stem}
库内解析：{solution}"""


async def run_once(llm, system: str, user_prompt: str, label: str, out: list) -> None:
    t0 = time.time()
    try:
        res = await llm.ask_text(system, user_prompt, max_tokens=2000)
    except Exception as e:  # noqa: BLE001
        print(f"  [{label}] 失败: {e}")
        return
    u = res.usage or {}
    dt = int((time.time() - t0) * 1000)
    rec = {
        "label": label,
        "prompt_tokens": u.get("prompt_tokens", 0),
        "completion_tokens": u.get("completion_tokens", 0),
        "reasoning_tokens": u.get("reasoning_tokens", 0),
        "cache_hit": u.get("cache_hit_tokens", 0),
        "cache_miss": u.get("cache_miss_tokens", 0),
        "latency_ms": dt,
        "answer_chars": len(res.answer or ""),
    }
    out.append(rec)
    hit = rec["cache_hit"]
    total_p = max(rec["prompt_tokens"], 1)
    print(
        f"  [{label}] prompt={rec['prompt_tokens']} (命中 {hit}, {hit/total_p*100:.0f}%) "
        f"completion={rec['completion_tokens']} reasoning={rec['reasoning_tokens']} "
        f"耗时={dt}ms"
    )


def summary(out: list) -> dict:
    groups: dict[str, list] = {}
    for r in out:
        groups.setdefault(r["label"], []).append(r)
    res = {}
    for k, rows in groups.items():
        res[k] = {
            "n": len(rows),
            "avg_prompt": round(statistics.mean(r["prompt_tokens"] for r in rows)),
            "avg_completion": round(statistics.mean(r["completion_tokens"] for r in rows)),
            "avg_reasoning": round(statistics.mean(r["reasoning_tokens"] for r in rows)),
            "avg_cache_hit": round(statistics.mean(r["cache_hit"] for r in rows)),
            "avg_latency_ms": round(statistics.mean(r["latency_ms"] for r in rows)),
        }
    return res


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=7)
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    from app.models import KBProblem
    from sqlmodel import select

    with Session(engine) as s:
        probs = s.exec(
            select(KBProblem).where(KBProblem.solution.is_not(None)).limit(args.rounds)
        ).all()
        base = "你是高数教师，讲清楚每一步在做什么。禁止使用英文双引号。"
        turns = [{"question": f"第{i}题", "verdict": "没懂"} for i in range(3)]
        sys_b = cm.compose(s, args.user, base_prompt=base)                    # 基础 + L1
        sys_c = cm.compose(s, args.user, turns=turns, base_prompt=base)      # 基础 + L1 + L2
        l1 = cm.build_l1_profile(s, args.user)

    if not probs:
        print("题库为空，先跑 scripts/kb/04_extract.py")
        return

    llm = DeepSeekClient(get_settings())
    out: list = []
    print(f"用户 {args.user} 的 L1 画像：{len(l1)} 字符；样本题 {len(probs)} 道\n")
    print(f"A 基础指令：{len(base)} 字符")
    print(f"B 加 L1：{len(sys_b)} 字符")
    print(f"C 全分层：{len(sys_c)} 字符\n")

    for p in probs:
        user_prompt = TASK.format(stem=(p.stem or "")[:400], solution=(p.solution or "")[:600])
        print(f"题【{p.problem_no}】：")
        await run_once(llm, base, user_prompt, "A_无注入", out)
        await run_once(llm, sys_b, user_prompt, "B_加L1画像", out)
        await run_once(llm, sys_c, user_prompt, "C_全分层", out)

    print("\n===== 汇总 =====")
    s = summary(out)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    if "A_无注入" in s and "B_加L1画像" in s:
        a, b = s["A_无注入"]["avg_prompt"], s["B_加L1画像"]["avg_prompt"]
        print(f"\n画像注入带来的 prompt 增量：{b - a} token（{(b-a)/max(a,1)*100:.1f}%）")
    print("缓存命中率对比见 avg_cache_hit；注意同一前缀重复调用才会命中缓存")


if __name__ == "__main__":
    asyncio.run(main())