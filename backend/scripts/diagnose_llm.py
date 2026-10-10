"""LLM 排障脚本：真实调用一次 DeepSeek，打印完整响应结构。

用法（在 backend/ 目录下）：
    .venv/Scripts/python.exe scripts/diagnose_llm.py [图片路径]
不打印 API Key。
"""

import base64
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.llm.deepseek import ANSWER_SYSTEM_PROMPT

s = get_settings()
print(f"base_url  = {s.deepseek_base_url}")
print(f"model     = {s.deepseek_model}")
print(f"timeout   = {s.deepseek_timeout}s")
print(f"max_tokens= {s.deepseek_max_tokens}")
print(f"configured= {s.llm_configured}")

image_path = (
    sys.argv[1]
    if len(sys.argv) > 1
    else str(Path(__file__).resolve().parents[1] / "uploads" / "23ebe00ec3db4ceea571789f8653b314.png")
)
data = Path(image_path).read_bytes()
print(f"image     = {image_path} ({len(data)} bytes)")

b64 = base64.b64encode(data).decode()
payload = {
    "model": s.deepseek_model,
    "messages": [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请解答照片中的题目。"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        },
    ],
    "temperature": 0.2,
    "max_tokens": s.deepseek_max_tokens,
}

url = f"{s.deepseek_base_url.rstrip('/')}/chat/completions"
resp = httpx.post(
    url, json=payload, headers={"Authorization": f"Bearer {s.deepseek_api_key}"}, timeout=300
)
print(f"\nHTTP {resp.status_code}")
try:
    body = resp.json()
except ValueError:
    print("非 JSON 响应：", resp.text[:500])
    raise SystemExit(1)

usage = body.get("usage")
if usage:
    print("usage:", json.dumps(usage, ensure_ascii=False))

for i, choice in enumerate(body.get("choices") or []):
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    print(f"\nchoice[{i}] finish_reason = {choice.get('finish_reason')}")
    print(f"  message keys          = {sorted(msg.keys())}")
    print(f"  content len           = {len(content)}")
    print(f"  reasoning_content len = {len(reasoning)}")
    if content:
        print("  content 前 400 字：")
        print("  " + content[:400].replace("\n", "\n  "))
    if reasoning:
        print("  reasoning 前 200 字：")
        print("  " + reasoning[:200].replace("\n", "\n  "))
