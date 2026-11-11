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


# ---------- 结构不完整的 JSON：漏括号 / 截断 / 尾逗号（公网实测故障的回归测试） ----------
#
# 真实事故（2026-11-11 部署后）：模型输出以 `}}` 结尾，正确应为 `}}}`，
# 旧逻辑解析失败后退化成纯文本，把整段 JSON 源码当讲解显示给学生，
# 知识点与反馈候选（在 meta 里）全部丢失。

MISSING_BRACE = (
    '{"answer":"第一步：赋值法令 $x=1$ 得系数和。",'
    '"problems":[{"no":"10","title":"求系数和","answer":"详解见上"}],'
    '"meta":{"kp_tags":["二项式定理"],"difficulty":3,'
    '"feedback_options":[{"tag":"careless","weight":0.2}]}'
)

TRUNCATED = '{"answer":"第一步：先求导 $f\'(x)=2x$，再令其为 0 得'

TRAILING_COMMA = '{"answer":"结论：$a_7=1$","meta":{"kp_tags":["数列"],'


def test_missing_closing_brace_is_repaired():
    obj = _extract_json(MISSING_BRACE)
    assert obj is not None
    assert obj["answer"].startswith("第一步：赋值法")
    assert obj["meta"]["kp_tags"] == ["二项式定理"]
    assert obj["meta"]["difficulty"] == 3
    assert obj["meta"]["feedback_options"][0]["tag"] == "careless"
    assert obj["problems"][0]["no"] == "10"


def test_truncated_output_keeps_partial_answer():
    obj = _extract_json(TRUNCATED)
    assert obj is not None
    assert "第一步" in obj["answer"]
    assert not obj["answer"].startswith("{")


def test_trailing_comma_and_unclosed_object():
    obj = _extract_json(TRAILING_COMMA)
    assert obj is not None
    assert obj["answer"] == "结论：$a_7=1$"
    assert obj["meta"]["kp_tags"] == ["数列"]


def test_repair_preserves_latex_backslashes():
    """括号配平不能破坏 LaTeX：\\frac 解析后应还原为 \\frac，而不是被吃掉。"""
    raw = '{"answer":"$$\\frac{1}{2}+\\cdots$$","meta":{"kp_tags":["分式"]}'
    obj = _extract_json(raw)
    assert obj is not None
    assert "\\frac" in obj["answer"]
    assert "\\cdots" in obj["answer"]
