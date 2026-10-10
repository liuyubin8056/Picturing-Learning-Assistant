"""DeepSeek 多模态大模型客户端（OpenAI 兼容协议）。

答疑与打标搭车同一次调用：prompt 要求模型输出含 answer + meta 的 JSON，
服务端容错解析（meta 即方案文档 3.2 / 11.5 节的搭车结构）。
API Key 在 backend/.env 的 DEEPSEEK_API_KEY 填入。
"""

import base64
import json
import re

import httpx

from ..config import Settings

ANSWER_SYSTEM_PROMPT = """你是「智能拍照学习助手」的答疑老师，负责解答学生拍摄上传的题目照片。

要求：
1. answer 内给出分步推导过程：先结论，再过程，语言简洁、由浅入深，适合中学生阅读。
2. 严格只输出一个 JSON 对象，不要输出 markdown 代码块标记或其他任何文字，结构如下：
{
  "answer": "……分步讲解……",
  "meta": {
    "subject": "学科，如：数学",
    "chapter": "章节，如：二次函数",
    "kp_tags": ["知识点1", "知识点2"],
    "difficulty": 3,
    "suspected_error_type": "概念不清 / 方法缺失 / 审题偏差 / 计算粗心 / 无",
    "profile_delta": {"confusion": "学生可能的困惑点", "hint": "下次讲解建议"}
  }
}
3. meta 用于学习诊断，尽力填写；不确定的字段填空字符串或空数组，不要编造。"""


class LLMNotConfiguredError(RuntimeError):
    """DEEPSEEK_API_KEY 未配置。"""


class LLMCallError(RuntimeError):
    """大模型调用失败（网络 / 非 200 / 响应结构异常）。"""


class LLMResult:
    def __init__(self, answer: str, meta: dict | None, raw: str):
        self.answer = answer
        self.meta = meta
        self.raw = raw


def _extract_json(raw: str) -> dict | None:
    """容错解析模型输出：裸 JSON → ```json 围栏 → 首个平衡大括号块。"""
    text = raw.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            obj = json.loads(fence.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
    return None


def extract_content(data: dict) -> str:
    """从 chat/completions 响应提取正文 content。

    空 content / 截断 / 结构异常一律抛 LLMCallError（上层落 failed、可重试），
    绝不静默返回空字符串（否则会被标记 answered 且幂等命中空结果）。
    """
    choices = data.get("choices") or []
    if not choices:
        raise LLMCallError(f"大模型响应无 choices：{str(data)[:300]}")
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    message = choice.get("message") or {}
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""

    if not content.strip():
        if reasoning:
            raise LLMCallError(
                f"模型仅产出推理内容、正文为空（finish_reason={finish_reason}，"
                f"推理 {len(reasoning)} 字符）：推理 token 疑似耗尽 DEEPSEEK_MAX_TOKENS，"
                "请在 backend/.env 调大后重试"
            )
        raise LLMCallError(f"模型返回空正文（finish_reason={finish_reason}）")
    if finish_reason == "length":
        raise LLMCallError(
            "输出被 DEEPSEEK_MAX_TOKENS 截断（finish_reason=length），"
            "请在 backend/.env 调大后重试"
        )
    return content


class DeepSeekClient:
    def __init__(self, settings: Settings):
        self._s = settings

    def _parse(self, raw: str) -> LLMResult:
        """解析模型输出；解析失败时降级为纯文本 answer（meta 为空）。"""
        obj = _extract_json(raw)
        if obj is None:
            return LLMResult(answer=raw.strip(), meta=None, raw=raw)
        answer = str(obj.get("answer") or "").strip() or raw.strip()
        meta = obj.get("meta")
        return LLMResult(
            answer=answer, meta=meta if isinstance(meta, dict) else None, raw=raw
        )

    async def ask_with_image(
        self, image_bytes: bytes, mime: str = "image/jpeg"
    ) -> LLMResult:
        if not self._s.llm_configured:
            raise LLMNotConfiguredError(
                "DEEPSEEK_API_KEY 未配置，请在 backend/.env 中填入后重启服务"
            )

        b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": self._s.deepseek_model,
            "messages": [
                {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请解答照片中的题目。"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                },
            ],
            "temperature": 0.2,
            "max_tokens": self._s.deepseek_max_tokens,
        }
        headers = {"Authorization": f"Bearer {self._s.deepseek_api_key}"}
        url = f"{self._s.deepseek_base_url.rstrip('/')}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=self._s.deepseek_timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise LLMCallError(f"调用大模型失败：{e}") from e

        if resp.status_code != 200:
            raise LLMCallError(
                f"大模型返回 {resp.status_code}：{resp.text[:300]}"
            )

        try:
            data = resp.json()
        except ValueError as e:
            raise LLMCallError(f"大模型响应非 JSON：{resp.text[:300]}") from e

        raw = extract_content(data)
        result = self._parse(raw)
        if not result.answer.strip():
            # 双保险：extract_content 已拦空正文，此处防解析层意外丢内容
            raise LLMCallError("模型正文解析结果为空")
        return result
