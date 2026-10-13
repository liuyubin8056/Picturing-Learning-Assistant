"""知识库构建共用工具（PDF 定位 / LLM 并发调用 / 结果缓存）。"""

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.llm.deepseek import _extract_json  # noqa: E402

OUT_DIR = BACKEND_DIR / "_kb_out"
LLM_TIMEOUT = 300  # 推理型模型较慢，放宽超时


def find_pdf() -> Path:
    for p in BACKEND_DIR.parent.glob("*.pdf"):
        return p
    raise FileNotFoundError("工作区根目录未找到 PDF")


async def call_llm(
    prompt: str,
    images: list[str] | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.2,
) -> dict:
    """调用 DeepSeek（OpenAI 兼容协议），images 为 base64 PNG 列表。"""
    s = get_settings()
    if not s.llm_configured:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in images or []:
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}
        )
    payload = {
        "model": s.deepseek_model,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": max_tokens or s.deepseek_max_tokens,
    }
    url = f"{s.deepseek_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {s.deepseek_api_key}"}

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        r = await client.post(url, json=payload, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")

    data = r.json()
    choice = data["choices"][0]
    msg = choice.get("message") or {}
    raw = msg.get("content") or ""
    if not raw.strip():
        rc = msg.get("reasoning_content") or ""
        raise RuntimeError(
            f"空正文（finish_reason={choice.get('finish_reason')}, 推理 {len(rc)} 字符），"
            "可能需调大 DEEPSEEK_MAX_TOKENS"
        )
    return _extract_json(raw) or {"_raw_text": raw}


async def run_pool(coros, concurrency: int = 6, desc: str = ""):
    """并发执行 coroutine 列表，失败返回 {_error}，保持顺序。"""
    sem = asyncio.Semaphore(concurrency)
    done = {"n": 0}

    async def guarded(i, c):
        async with sem:
            done["n"] += 1
            print(f"  [{desc}] 启动 {done['n']}/{len(coros)}", flush=True)
            try:
                r = await c
                print(f"  [{desc}] 完成 {i + 1}", flush=True)
                return r
            except Exception as e:  # noqa: BLE001
                print(f"  [{desc}] 失败 {i + 1}: {e}", flush=True)
                return {"_error": str(e)}

    return await asyncio.gather(*[guarded(i, c) for i, c in enumerate(coros)])


def save_json(name: str, obj) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已保存 {p.name}（{p.stat().st_size // 1024} KB）")
    return p


def load_json(name: str):
    p = OUT_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def b64_image(png_path: Path) -> str:
    return base64.b64encode(Path(png_path).read_bytes()).decode()