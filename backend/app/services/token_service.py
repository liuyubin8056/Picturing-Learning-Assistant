"""Token 计量落库（service 层纯逻辑，接口见 app/routers/tokens.py）。"""

from sqlmodel import Session

from ..models import TokenUsage


def record_usage(
    session: Session,
    user_id: int | None,
    scene: str,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    reasoning_tokens: int = 0,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    latency_ms: int = 0,
) -> TokenUsage:
    """记录一次模型调用的 token 计量（调用方负责 commit）。"""
    u = TokenUsage(
        user_id=user_id,
        scene=scene,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cache_hit_tokens=cache_hit_tokens,
        cache_miss_tokens=cache_miss_tokens,
        latency_ms=latency_ms,
    )
    session.add(u)
    return u


FIELDS = (
    "calls",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "total_tokens",
    "cache_hit_tokens",
    "cache_miss_tokens",
    "latency_ms",
)


def aggregate(rows: list[TokenUsage]) -> dict:
    """按场景聚合，并算出缓存命中率 / 推理占比 / 单次均值。"""
    agg: dict[str, dict] = {}
    for r in rows:
        a = agg.setdefault(r.scene, {k: 0 for k in FIELDS})
        a["calls"] += 1
        for k in FIELDS[1:]:
            a[k] += getattr(r, k, 0)

    for a in agg.values():
        a["avg_per_call"] = round(a["total_tokens"] / max(a["calls"], 1))
        denom = a["cache_hit_tokens"] + a["cache_miss_tokens"]
        a["cache_hit_rate"] = round(a["cache_hit_tokens"] / denom * 100, 1) if denom else None
        a["reasoning_share"] = (
            round(a["reasoning_tokens"] / a["completion_tokens"] * 100, 1)
            if a["completion_tokens"]
            else 0.0
        )
        a["avg_latency_ms"] = round(a["latency_ms"] / max(a["calls"], 1))

    return {
        "scenes": agg,
        "total_calls": sum(a["calls"] for a in agg.values()),
        "total_tokens": sum(a["total_tokens"] for a in agg.values()),
    }