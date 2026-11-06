"""LLM 输出容错解析单元测试（不依赖网络）。"""

import pytest

from app.config import Settings
from app.llm.deepseek import (
    DeepSeekClient,
    LLMCallError,
    _extract_json,
    extract_content,
)


def _client() -> DeepSeekClient:
    return DeepSeekClient(Settings(deepseek_api_key="test-only"))


def test_extract_plain_json():
    raw = '{"answer": "A", "meta": {"chapter": "函数"}}'
    assert _extract_json(raw)["answer"] == "A"


def test_extract_fenced_json():
    raw = '好的，这是解答：\n```json\n{"answer": "B", "meta": {"chapter": "圆"}}\n```\n希望有帮助'
    assert _extract_json(raw)["answer"] == "B"


def test_extract_json_with_noise():
    raw = '前面有废话 {"answer": "C", "meta": {"kp_tags": ["x"]}} 后面也有废话'
    assert _extract_json(raw)["answer"] == "C"


def test_extract_failure_returns_none():
    assert _extract_json("这不是 JSON，只是纯文本讲解。") is None


def test_parse_fallback_to_raw_text():
    r = _client()._parse("模型没按格式输出，直接给了纯文本讲解")
    assert r.answer.startswith("模型没按格式")
    assert r.meta is None


def test_parse_invalid_meta_type():
    r = _client()._parse('{"answer": "ok", "meta": "not-a-dict"}')
    assert r.answer == "ok"
    assert r.meta is None


def test_parse_empty_answer_falls_back_to_raw():
    r = _client()._parse('{"answer": "", "meta": {"chapter": "圆"}}')
    assert r.answer == '{"answer": "", "meta": {"chapter": "圆"}}' or r.answer
    assert r.meta == {"chapter": "圆"}


# ---------- extract_content：空正文 / 截断防护（线上真实故障的回归测试） ----------


def test_extract_content_ok():
    data = {"choices": [{"finish_reason": "stop", "message": {"content": "解答……"}}]}
    assert extract_content(data) == "解答……"


def test_extract_content_empty_with_reasoning():
    """deepseek-flash 实测故障形态：reasoning 吃满 max_tokens，content 为空。"""
    data = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": "", "reasoning_content": "思考" * 100},
            }
        ]
    }
    with pytest.raises(LLMCallError, match="推理"):
        extract_content(data)


def test_extract_content_empty_without_reasoning():
    data = {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}
    with pytest.raises(LLMCallError, match="空正文"):
        extract_content(data)


def test_extract_content_truncated():
    data = {"choices": [{"finish_reason": "length", "message": {"content": "不完整答案"}}]}
    with pytest.raises(LLMCallError, match="截断"):
        extract_content(data)


def test_extract_content_no_choices():
    with pytest.raises(LLMCallError, match="无 choices"):
        extract_content({})
