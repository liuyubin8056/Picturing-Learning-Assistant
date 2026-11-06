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
2. **排版硬性要求（违反会导致公式显示错乱）**：
   - 每一步单独成段（分段分行，不要把所有步骤挤成一段），推荐写成「第一步：…」「第二步：…」的形式；
   - **所有数学式子必须用 LaTeX 定界符包裹**：行内公式用 $...$（如 $a_1+a_2$、$x^8$），独立公式用 $$...$$；
   - 禁止输出没有 $ 包裹的裸公式（例如禁止直接写 a_0+a_1x 或 x^8）；
   - 公式内只使用标准 LaTeX 命令（\\frac、\\cdots、\\times、\\lim 等），不要使用 \\f 开头的非标准写法。
3. 严格只输出一个 JSON 对象，不要输出 markdown 代码块标记或其他任何文字，结构如下：
{
  "answer": "……分步讲解……",
  "problems": [
    {"no": "1", "title": "8字内概括", "answer": "该题完整分步讲解"}
  ],
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
4. **一图多题的处理（重要）**：
   - 照片里只有一道题时，problems 只放一项，其 answer 与顶层 answer 内容一致；
   - 照片里有多道题时，problems 逐题给出完整讲解（每题的 answer 同样遵守第 2 条排版要求），
     no 用题号或序号（如 "1"、"(2)"），title 用 8 字以内概括（如「求极限」「判断收敛」）；
     此时顶层 answer 写一句总览，如「本页共 3 题，可在上方切换查看」。
5. meta 用于学习诊断，尽力填写；不确定的字段填空字符串或空数组，不要编造。
6. **格式约束**：answer 与 meta 的所有文本内容中，禁止使用英文双引号 " 和反斜杠以外的特殊转义；需要引用词语时请用中文引号「」。违反会导致你的输出无法被解析。

关于 feedback_options（学生看完答案后可选的「我不会的原因」多选项，用于生成个性化画像）：
- 给 4~6 个候选，按本题最可能的原因排序；label 要具体（如"没记住洛必达法则的适用条件"），不要写泛泛的"概念不清"。
- **tag 字段必须从以下固定集合中选择（严禁自创，否则系统无法识别）**：
  · concept_unclear —— 概念没理解（weight 0.8~1.0）
  · method_missing —— 方法没想到 / 不会转化
  · no_idea —— 完全没思路，从第一步就不会（weight 1.2）
  · knowledge_gap —— 知识点忘了 / 没学过（weight 1.1）
  · condition_miss —— 漏看条件（weight 0.4，低级错误）
  · calculation —— 计算失误（weight 0.3，低级错误）
  · careless —— 会做但粗心 / 算错（weight 0.2，低级错误）
  · misread —— 看错题目了（weight 0.2，低级错误）
- **必须包含 careless、misread、no_idea 这三个通用选项**（它们是最常见的低级错误，必须给学生选出来的机会，避免把粗心误判成知识漏洞）。
- weight 按上面括号中的建议值填写。

关于 kp_tags：请使用高数教材的标准术语（如「函数的定义域」而不是「定义域求法」），控制在 3 个以内，以便与题库知识点对齐。
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
        self.usage: dict = {}  # token 计量，由 _post 填充


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


def extract_usage(data: dict) -> dict:
    """从响应中提取 token 计量（缺失字段补 0）。"""
    u = data.get("usage") or {}
    details = u.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "reasoning_tokens": int(details.get("reasoning_tokens") or 0),
        "total_tokens": int(u.get("total_tokens") or 0),
        "cache_hit_tokens": int(u.get("prompt_cache_hit_tokens") or 0),
        "cache_miss_tokens": int(u.get("prompt_cache_miss_tokens") or 0),
    }


class DeepSeekClient:
    def __init__(self, settings: Settings):
        self._s = settings

    @property
    def model(self) -> str:
        return self._s.deepseek_model

    def _parse(self, raw: str) -> LLMResult:
        """解析模型输出；解析失败时降级为纯文本 answer（meta 为空）。"""
        obj = _extract_json(raw)
        if obj is None:
            return LLMResult(answer=raw.strip(), meta=None, raw=raw)
        answer = str(obj.get("answer") or "").strip() or raw.strip()
        meta = obj.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        # 多题照片的逐题讲解：随 meta 带出，service 层单独落库
        probs = obj.get("problems")
        if isinstance(probs, list) and probs:
            meta["problems"] = probs
        return LLMResult(answer=answer, meta=meta or None, raw=raw)

    async def _post(self, payload: dict) -> tuple[str, dict]:
        """统一发请求，返回 (正文, usage)。"""
        if not self._s.llm_configured:
            raise LLMNotConfiguredError(
                "DEEPSEEK_API_KEY 未配置，请在 backend/.env 中填入后重启服务"
            )
        headers = {"Authorization": f"Bearer {self._s.deepseek_api_key}"}
        url = f"{self._s.deepseek_base_url.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._s.deepseek_timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise LLMCallError(f"调用大模型失败：{e}") from e

        if resp.status_code != 200:
            raise LLMCallError(f"大模型返回 {resp.status_code}：{resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise LLMCallError(f"大模型响应非 JSON：{resp.text[:300]}") from e
        return extract_content(data), extract_usage(data)

    async def ask_with_image(
        self, image_bytes: bytes, mime: str = "image/jpeg"
    ) -> LLMResult:
        """答疑（多模态）：答疑 + 打标 + 反馈候选同一次调用。"""
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
        raw, usage = await self._post(payload)
        result = self._parse(raw)
        if not result.answer.strip():
            # 双保险：extract_content 已拦空正文，此处防解析层意外丢内容
            raise LLMCallError("模型正文解析结果为空")
        result.usage = usage
        return result

    async def ask_image_custom(
        self,
        system: str,
        user_text: str,
        image_bytes: bytes,
        mime: str = "image/jpeg",
        max_tokens: int | None = None,
    ) -> LLMResult:
        """自定义 prompt 的多模态调用（如手写解答阅卷）。

        与 ask_with_image 的区别：prompt 由调用方给，不走答疑的固定模板与搭车解析。
        """
        b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": self._s.deepseek_model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens or self._s.deepseek_max_tokens,
        }
        raw, usage = await self._post(payload)
        result = LLMResult(answer=raw.strip(), meta=None, raw=raw)
        result.usage = usage
        return result

    async def ask_text(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> LLMResult:
        """纯文本调用（诊断报告撰写、题目详解生成）。

        system 放稳定内容、user 放每次变化的内容：前缀一致可命中服务端缓存，
        画像摘要应放在 system 末尾以最大化缓存复用（见 docs/token优化论证.md）。
        """
        payload = {
            "model": self._s.deepseek_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens or self._s.deepseek_max_tokens,
        }
        raw, usage = await self._post(payload)
        result = LLMResult(answer=raw.strip(), meta=None, raw=raw)
        result.usage = usage
        return result
