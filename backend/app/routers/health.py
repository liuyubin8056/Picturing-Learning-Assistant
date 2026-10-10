"""健康检查：同时暴露 LLM 配置状态，便于确认 API Key 是否生效。"""

from fastapi import APIRouter

from ..config import get_settings

router = APIRouter(tags=["health"])


@router.get("/api/v1/health")
def health():
    s = get_settings()
    return {
        "status": "ok",
        "llm_configured": s.llm_configured,  # False = .env 里 API Key 还没填
        "model": s.deepseek_model,
    }
