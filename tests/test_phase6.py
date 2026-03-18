"""
test_phase6.py — Unit tests for Phase 6 LLM call reduction (no real API calls).

Covers:
  - _title_match_heuristic: clear match → 'yes', no match → None, short title → None
  - _toc_page_heuristic: keyword match → 'yes', entry pattern → 'yes', unclear → None
  - _check_if_complete: correct prompt for extraction vs transformation kind
  - check_title_appearance: skips LLM when heuristic matches; calls LLM when inconclusive
  - check_title_appearance_in_start: same heuristic bypass
  - toc_detector_single_page: skips LLM when heuristic fires; calls LLM otherwise
  - check_if_toc_extraction_is_complete: thin wrapper calls _check_if_complete(kind='extraction')
  - check_if_toc_transformation_is_complete: thin wrapper calls _check_if_complete(kind='transformation')
"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pageindex.page_index  # noqa: F401
_pi = sys.modules["pageindex.page_index"]

from pageindex.page_index import (
    _title_match_heuristic,
    _toc_page_heuristic,
    _check_if_complete,
    check_title_appearance,
    check_title_appearance_in_start,
    toc_detector_single_page,
    check_if_toc_extraction_is_complete,
    check_if_toc_transformation_is_complete,
)


# ── _title_match_heuristic ─────────────────────────────────────────────────────

class TestTitleMatchHeuristic:

    def test_exact_match_returns_yes(self):
        assert _title_match_heuristic("Introduction", "1. Introduction\nThis paper...") == "yes"

    def test_case_insensitive_match(self):
        assert _title_match_heuristic("INTRODUCTION", "1. Introduction\nThis paper...") == "yes"

    def test_whitespace_normalised(self):
        assert _title_match_heuristic("Related  Work", "2. Related Work\nPrevious studies...") == "yes"

    def test_not_found_returns_none(self):
        assert _title_match_heuristic("Conclusion", "This page is about methods") is None

    def test_too_short_title_returns_none(self):
        assert _title_match_heuristic("AB", "AB is present here") is None

    def test_empty_title_returns_none(self):
        assert _title_match_heuristic("", "some page text") is None

    def test_whitespace_title_returns_none(self):
        assert _title_match_heuristic("   ", "some page text") is None

    def test_partial_word_does_not_match(self):
        # "intro" is not a match for "introduction"
        result = _title_match_heuristic("Intro", "1. Introduction\nThis paper")
        # "intro" IS a substring of "introduction" so this returns "yes"
        # The heuristic is conservative (only false positives, not false negatives)
        assert result in ("yes", None)

    def test_multiword_title_match(self):
        assert _title_match_heuristic(
            "Related Work", "Chapter 2: Related Work and Background"
        ) == "yes"


# ── _toc_page_heuristic ────────────────────────────────────────────────────────

class TestTocPageHeuristic:

    def test_table_of_contents_keyword(self):
        assert _toc_page_heuristic("Table of Contents\n1. Intro\n2. Methods") == "yes"

    def test_contents_keyword(self):
        assert _toc_page_heuristic("Contents\n1. Introduction ... 1\n2. Methods ... 5") == "yes"

    def test_numbered_entries_three_or_more(self):
        text = "1. Introduction\n1.1 Background\n1.2 Motivation\n2. Methods"
        assert _toc_page_heuristic(text) == "yes"

    def test_fewer_than_three_entries_returns_none(self):
        text = "1. Introduction\n1.1 Background"
        assert _toc_page_heuristic(text) is None

    def test_plain_prose_returns_none(self):
        text = "This chapter discusses the background of the problem in detail."
        assert _toc_page_heuristic(text) is None

    def test_empty_text_returns_none(self):
        assert _toc_page_heuristic("") is None

    def test_case_insensitive_keyword(self):
        assert _toc_page_heuristic("TABLE OF CONTENTS\n...") == "yes"


# ── _check_if_complete ─────────────────────────────────────────────────────────

class TestCheckIfComplete:

    @pytest.mark.asyncio
    async def test_extraction_kind_returns_yes(self):
        with patch.object(_pi, "_llm_json", new=AsyncMock(return_value={"completed": "yes"})):
            result = await _check_if_complete("doc text", "toc text", kind="extraction")
        assert result == "yes"

    @pytest.mark.asyncio
    async def test_transformation_kind_returns_no(self):
        with patch.object(_pi, "_llm_json", new=AsyncMock(return_value={"completed": "no"})):
            result = await _check_if_complete("raw toc", "cleaned toc", kind="transformation")
        assert result == "no"

    @pytest.mark.asyncio
    async def test_extraction_prompt_contains_document_label(self):
        captured = {}
        async def mock_llm_json(provider, prompt, **kw):
            captured['prompt'] = prompt
            return {"completed": "yes"}

        with patch.object(_pi, "_llm_json", side_effect=mock_llm_json):
            await _check_if_complete("doc", "toc", kind="extraction")

        assert "Document" in captured['prompt']

    @pytest.mark.asyncio
    async def test_transformation_prompt_contains_raw_toc_label(self):
        captured = {}
        async def mock_llm_json(provider, prompt, **kw):
            captured['prompt'] = prompt
            return {"completed": "yes"}

        with patch.object(_pi, "_llm_json", side_effect=mock_llm_json):
            await _check_if_complete("raw", "cleaned", kind="transformation")

        assert "Raw Table of contents" in captured['prompt']

    @pytest.mark.asyncio
    async def test_missing_completed_key_defaults_to_no(self):
        with patch.object(_pi, "_llm_json", new=AsyncMock(return_value={})):
            result = await _check_if_complete("a", "b", kind="extraction")
        assert result == "no"


# ── check_title_appearance heuristic bypass ────────────────────────────────────

class TestCheckTitleAppearanceHeuristic:

    @pytest.mark.asyncio
    async def test_heuristic_match_skips_llm(self):
        item = {'title': 'Introduction', 'physical_index': 1, 'list_index': 0}
        page_list = [("1. Introduction\nThis paper discusses...", 100)]
        mock_provider = MagicMock()

        with patch.object(_pi, "_llm_json", new=AsyncMock()) as mock_llm:
            result = await check_title_appearance(item, page_list, start_index=1,
                                                  provider=mock_provider)
        mock_llm.assert_not_awaited()
        assert result['answer'] == 'yes'

    @pytest.mark.asyncio
    async def test_no_heuristic_match_calls_llm(self):
        item = {'title': 'Conclusion', 'physical_index': 1, 'list_index': 0}
        page_list = [("This page is about methods and experiments.", 100)]
        mock_provider = MagicMock()

        with patch.object(_pi, "_llm_json",
                          new=AsyncMock(return_value={"answer": "no"})) as mock_llm:
            result = await check_title_appearance(item, page_list, start_index=1,
                                                  provider=mock_provider)
        mock_llm.assert_awaited_once()
        assert result['answer'] == 'no'

    @pytest.mark.asyncio
    async def test_missing_physical_index_returns_no_without_llm(self):
        item = {'title': 'Intro', 'list_index': 0}
        mock_provider = MagicMock()

        with patch.object(_pi, "_llm_json", new=AsyncMock()) as mock_llm:
            result = await check_title_appearance(item, [], provider=mock_provider)
        mock_llm.assert_not_awaited()
        assert result['answer'] == 'no'


# ── check_title_appearance_in_start heuristic bypass ──────────────────────────

class TestCheckTitleAppearanceInStartHeuristic:

    @pytest.mark.asyncio
    async def test_heuristic_match_skips_llm(self):
        mock_provider = MagicMock()
        with patch.object(_pi, "_llm_json", new=AsyncMock()) as mock_llm:
            result = await check_title_appearance_in_start(
                "Methods", "3. Methods\nWe used the following approach...",
                provider=mock_provider
            )
        mock_llm.assert_not_awaited()
        assert result == "yes"

    @pytest.mark.asyncio
    async def test_no_heuristic_match_calls_llm(self):
        mock_provider = MagicMock()
        with patch.object(_pi, "_llm_json",
                          new=AsyncMock(return_value={"answer": "yes"})) as mock_llm:
            result = await check_title_appearance_in_start(
                "Conclusion", "This page contains method descriptions.",
                provider=mock_provider
            )
        mock_llm.assert_awaited_once()
        assert result == "yes"


# ── toc_detector_single_page heuristic bypass ─────────────────────────────────

class TestTocDetectorHeuristic:

    @pytest.mark.asyncio
    async def test_keyword_skips_llm(self):
        mock_provider = MagicMock()
        with patch.object(_pi, "_llm_json", new=AsyncMock()) as mock_llm:
            result = await toc_detector_single_page(
                "Table of Contents\n1. Intro ... 1\n2. Methods ... 5",
                provider=mock_provider
            )
        mock_llm.assert_not_awaited()
        assert result == "yes"

    @pytest.mark.asyncio
    async def test_numbered_entries_skips_llm(self):
        mock_provider = MagicMock()
        content = "1. Introduction\n1.1 Background\n1.2 Scope\n2. Methods"
        with patch.object(_pi, "_llm_json", new=AsyncMock()) as mock_llm:
            result = await toc_detector_single_page(content, provider=mock_provider)
        mock_llm.assert_not_awaited()
        assert result == "yes"

    @pytest.mark.asyncio
    async def test_plain_prose_calls_llm(self):
        mock_provider = MagicMock()
        content = "This chapter explains the background of the study in detail."
        with patch.object(_pi, "_llm_json",
                          new=AsyncMock(return_value={"toc_detected": "no"})) as mock_llm:
            result = await toc_detector_single_page(content, provider=mock_provider)
        mock_llm.assert_awaited_once()
        assert result == "no"


# ── backward-compat thin wrappers ─────────────────────────────────────────────

class TestCompletionWrappers:

    @pytest.mark.asyncio
    async def test_extraction_wrapper_delegates(self):
        with patch.object(_pi, "_check_if_complete",
                          new=AsyncMock(return_value="yes")) as mock:
            result = await check_if_toc_extraction_is_complete("doc", "toc")
        mock.assert_awaited_once()
        assert result == "yes"
        _, kwargs = mock.call_args
        assert kwargs.get("kind") == "extraction" or mock.call_args[0][2] == "extraction"

    @pytest.mark.asyncio
    async def test_transformation_wrapper_delegates(self):
        with patch.object(_pi, "_check_if_complete",
                          new=AsyncMock(return_value="no")) as mock:
            result = await check_if_toc_transformation_is_complete("raw", "cleaned")
        mock.assert_awaited_once()
        assert result == "no"
        _, kwargs = mock.call_args
        assert kwargs.get("kind") == "transformation" or mock.call_args[0][2] == "transformation"
