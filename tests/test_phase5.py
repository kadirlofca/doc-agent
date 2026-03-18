"""
test_phase5.py — Unit tests for Phase 5 JSON reliability (no real API calls).

Covers:
  - _clean_json_text: markdown fences, Python literals, trailing commas, single quotes
  - parse_json_robust: valid JSON, cleaned JSON, fallback bracket extraction, raises on failure
  - _llm_json: success on first attempt, retries on parse failure, returns {} after exhaustion
"""
import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# pageindex/__init__.py does `from .page_index import *` which shadows the
# submodule name with the exported function. Import the submodule first.
import pageindex.page_index  # noqa: F401 — registers the module
_pi = sys.modules["pageindex.page_index"]

from pageindex.page_index import _llm_json
from pageindex.utils import _clean_json_text, parse_json_robust


# ── _clean_json_text ───────────────────────────────────────────────────────────

class TestCleanJsonText:

    def test_strips_markdown_json_fence(self):
        text = "```json\n{\"key\": \"value\"}\n```"
        result = _clean_json_text(text)
        assert "{" in result
        assert "```" not in result

    def test_strips_plain_code_fence(self):
        text = "```\n{\"key\": 1}\n```"
        result = _clean_json_text(text)
        assert "```" not in result

    def test_converts_none_to_null(self):
        text = '{"a": None}'
        result = _clean_json_text(text)
        assert "null" in result
        assert "None" not in result

    def test_converts_true_false(self):
        text = '{"a": True, "b": False}'
        result = _clean_json_text(text)
        assert "true" in result
        assert "false" in result
        assert "True" not in result
        assert "False" not in result

    def test_removes_trailing_comma_before_brace(self):
        text = '{"a": 1,}'
        result = _clean_json_text(text)
        # Should parse after cleaning
        parsed = json.loads(result)
        assert parsed["a"] == 1

    def test_removes_trailing_comma_before_bracket(self):
        text = '[1, 2, 3,]'
        result = _clean_json_text(text)
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def test_passthrough_valid_json(self):
        text = '{"key": "value", "num": 42}'
        result = _clean_json_text(text)
        assert json.loads(result) == {"key": "value", "num": 42}


# ── parse_json_robust ──────────────────────────────────────────────────────────

class TestParseJsonRobust:

    def test_valid_json_object(self):
        result = parse_json_robust('{"answer": "yes"}')
        assert result == {"answer": "yes"}

    def test_valid_json_array(self):
        result = parse_json_robust('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_json_with_markdown_fence(self):
        result = parse_json_robust('```json\n{"answer": "yes"}\n```')
        assert result["answer"] == "yes"

    def test_json_with_preamble_text(self):
        result = parse_json_robust('Here is the result:\n{"answer": "yes"}')
        assert result["answer"] == "yes"

    def test_python_none_literal(self):
        result = parse_json_robust('{"val": None}')
        assert result["val"] is None

    def test_python_true_false_literals(self):
        result = parse_json_robust('{"a": True, "b": False}')
        assert result["a"] is True
        assert result["b"] is False

    def test_trailing_comma(self):
        result = parse_json_robust('{"a": 1, "b": 2,}')
        assert result["a"] == 1

    def test_raises_on_unparseable_text(self):
        with pytest.raises(json.JSONDecodeError):
            parse_json_robust("this is not json at all")

    def test_raises_on_empty_string(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            parse_json_robust("")

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = parse_json_robust(text)
        assert result["outer"]["inner"] == [1, 2, 3]


# ── _llm_json ──────────────────────────────────────────────────────────────────

class TestLlmJson:

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Valid JSON on first call — no retries needed."""
        mock_provider = MagicMock()
        with patch.object(_pi, "_llm", new=AsyncMock(return_value='{"answer": "yes"}')):
            result = await _llm_json(mock_provider, "some prompt")
        assert result == {"answer": "yes"}

    @pytest.mark.asyncio
    async def test_retries_on_parse_failure(self):
        """First call returns garbage, second returns valid JSON."""
        mock_provider = MagicMock()
        call_count = 0

        async def mock_llm(provider, prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "not json at all"
            return '{"answer": "yes"}'

        with patch.object(_pi, "_llm", side_effect=mock_llm):
            result = await _llm_json(mock_provider, "some prompt", max_retries=3)
        assert result == {"answer": "yes"}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_dict_after_all_retries_fail(self):
        """All attempts return unparseable text → returns {}."""
        mock_provider = MagicMock()
        with patch.object(_pi, "_llm", new=AsyncMock(return_value="definitely not json")):
            result = await _llm_json(mock_provider, "some prompt", max_retries=3)
        assert result == {}

    @pytest.mark.asyncio
    async def test_retry_prompt_includes_critical_instruction(self):
        """On retry attempts, the prompt should include JSON instruction."""
        mock_provider = MagicMock()
        prompts_sent = []

        async def mock_llm(provider, prompt):
            prompts_sent.append(prompt)
            if len(prompts_sent) == 1:
                return "bad response"
            return '{"ok": true}'

        with patch.object(_pi, "_llm", side_effect=mock_llm):
            await _llm_json(mock_provider, "original prompt", max_retries=3)

        assert prompts_sent[0] == "original prompt"
        assert "CRITICAL" in prompts_sent[1]
        assert "JSON" in prompts_sent[1]

    @pytest.mark.asyncio
    async def test_json_with_markdown_fence_succeeds(self):
        """Markdown-fenced JSON should be parsed successfully on first attempt."""
        mock_provider = MagicMock()
        with patch.object(_pi, "_llm",
                          new=AsyncMock(return_value='```json\n{"toc_detected": "yes"}\n```')):
            result = await _llm_json(mock_provider, "prompt")
        assert result["toc_detected"] == "yes"

    @pytest.mark.asyncio
    async def test_max_retries_one_no_extra_calls(self):
        """max_retries=1 should only call LLM once even on failure."""
        mock_provider = MagicMock()
        call_count = 0

        async def mock_llm(provider, prompt):
            nonlocal call_count
            call_count += 1
            return "not json"

        with patch.object(_pi, "_llm", side_effect=mock_llm):
            result = await _llm_json(mock_provider, "prompt", max_retries=1)
        assert result == {}
        assert call_count == 1
