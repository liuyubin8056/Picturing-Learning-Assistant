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
    "feedback_options": [
      {"tag": "concept_unclear", "label": "看不懂解析里的某个概念", "weight": 1.0}
    ],
    "profile_delta": {"confusion": "学生可能的困惑点", "hint": "下次讲解建议"}
  }
}
3. meta 用于学习诊断，尽力填写；不确定的字段填空字符串或空数组，不要编造。
4. **重要格式约束**：answer 与 meta 的所有文本内容中，禁止使用英文双引号 " 和反斜杠以外的特殊转义；需要引用词语时请用中文引号「」。公式请直接写 LaTeX（如 \\frac{1}{2}、\\lim_{x\\to0}）。违反会导致你的输出无法被解析。

关于 feedback_options（学生看完答案后可选的「我不会的原因」多选项，用于生成个性化画像）：
- 给 4~6 个候选，按本题最可能的原因排序；label 要具体（如"没记住洛必达法则的适用条件"），不要写泛泛的"概念不清"。
- 必须包含以下通用选项中的至少 3 个（它们是最常见的低级错误，必须给学生选出来的机会，避免把粗心误判成知识漏洞）：
  · careless：「会做但粗心/算错了」，weight 0.2
  · misread：「看错题目了或漏看了条件」，weight 0.2
  · no_idea：「完全没思路，从第一步就不会」，weight 1.2
- weight 表示该原因对「知识薄弱」的贡献：真正没掌握的原因权重高（0.8~1.2），低级错误权重低（0.2~0.3）。
"""


class LLMNotConfiguredError(RuntimeError):
    """DEEPSEEK_API_KEY 未配置。"""


class LLMCallError(RuntimeError):
    """大模型调用失败（网络 / 非 200 / 响应结构异常）。"""


class LLMResult:
    def __init__(self, answer: str, meta: dict | None, raw: str):
        self.answer = answer
        self.meta = meta
        self.raw = raw


_HEXDIGITS = set("0123456789abcdefABCDEF")


def _escape_control_chars(text: str) -> str:
    """修复模型输出的两类 JSON 违规，保证 LaTeX 公式原样保留。

    1. 字符串内的裸控制字符（真实换行/制表符）→ 转义为 \\n \\t
    2. 非法或有歧义的转义序列：LaTeX 的 \\frac \\cdot \\infty 等被 JSON 当成
       非法转义（\\f \\c \\i 都不合法，\\f 还会被误解析为 formfeed）→ 双写反斜杠，
       解析后仍是原文 \\frac；而 \\" \\\\ \\uXXXX 这类合法转义原样保留。
    """
    out: list[str] = []
    in_str = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue

        # 字符串内部
        if ch == "\\":
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt in ('"', "\\"):  # 合法且必须保留
                out.append(ch)
                out.append(nxt)
                i += 2
                continue
            if nxt == "u" and all(c in _HEXDIGITS for c in text[i + 2 : i + 6]):
                out.append(text[i : i + 6])
                i += 6
                continue
            out.append("\\\\")  # 双写：\frac → \\frac，解析后还原为 \frac
            i += 1
            continue

        if ch == '"':
            in_str = False
        elif ch == "\n":
            out.append("\\n")
            i += 1
            continue
        elif ch == "\r":
            out.append("\\r")
            i += 1
            continue
        elif ch == "\t":
            out.append("\\t")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _loads(text: str) -> dict | None:
    """先严格解析，失败则转义修复后再解析。"""
    for candidate in (text, _escape_control_chars(text)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _extract_json(raw: str) -> dict | None:
    """容错解析模型输出：裸 JSON → 转义修复 → ```json 围栏 → 首个平衡大括号块
    → 兜底字段提取。"""
    text = raw.strip()

    obj = _loads(text)
    if obj is not None:
        return obj

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        obj = _loads(fence.group(1))
        if obj is not None:
            return obj

    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    obj = _loads(text[start : i + 1])
                    if obj is not None:
                        return obj
                    break
    return _salvage(text)


def _unescape(text: str) -> str:
    return (
        text.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\r", "\r")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _salvage(text: str) -> dict | None:
    """兜底提取：JSON 因未转义引号等损坏时，尽力取出 answer 与 meta。

    模型偶发在文本里写英文双引号（如「沿法向"压"到平面」），会提前闭合 JSON 字符串，
    导致整体解析失败。此时用结构标记做宽松切分，保证核心字段不丢。
    """
    if '"answer"' not in text:
        return None
    m = re.search(r'"answer"\s*:\s*"', text)
    if not m:
        return None
    body = text[m.end() :]
    end = re.search(r'"\s*,\s*"meta"\s*:', body)
    if not end:
        # 没有 meta 段：取到下一个未转义的收尾引号
        close = re.search(r'"\s*\}\s*$', body)
        if not close:
            return None
        return {"answer": _unescape(body[: close.start()])}

    out: dict = {"answer": _unescape(body[: end.start()])}
    tail = body[end.end() :]
    last = tail.rfind("}")
    meta = _loads(tail[: last + 1]) if last > 0 else None
    if isinstance(meta, dict):
        out["meta"] = meta
    return out


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
