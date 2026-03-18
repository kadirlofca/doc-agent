"""
test_phase7.py — Unit tests for Phase 7 large-document scaling (no real API calls).

Covers:
  - _chunk_budget: reads opt.pipeline.chunk_token_budget, caps at 75% context_window,
                   falls back to 20_000, never returns below 1_000
  - page_list_to_group_text: respects passed max_tokens (indirect via _chunk_budget)
  - process_no_toc / process_toc_no_page_numbers: pass opt-derived budget to grouper
"""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pageindex.page_index  # noqa: F401
_pi = sys.modules["pageindex.page_index"]

from pageindex.page_index import _chunk_budget, page_list_to_group_text


# ── _chunk_budget ──────────────────────────────────────────────────────────────

class TestChunkBudget:

    def _make_opt(self, chunk_token_budget=None, context_window=None):
        pipeline = SimpleNamespace()
        if chunk_token_budget is not None:
            pipeline.chunk_token_budget = chunk_token_budget
        opt = SimpleNamespace(pipeline=pipeline)
        if context_window is not None:
            provider = MagicMock()
            provider.context_window = context_window
            opt.provider = provider
        return opt

    def test_default_fallback_is_20000(self):
        assert _chunk_budget(None) == 20_000

    def test_reads_pipeline_chunk_token_budget(self):
        opt = self._make_opt(chunk_token_budget=50_000)
        assert _chunk_budget(opt) == 50_000

    def test_caps_at_75_percent_of_context_window(self):
        # budget=100_000 but context_window=40_000 → cap = 30_000
        opt = self._make_opt(chunk_token_budget=100_000, context_window=40_000)
        assert _chunk_budget(opt) == 30_000

    def test_budget_below_cap_is_unchanged(self):
        # budget=10_000, context_window=128_000 → cap=96_000, budget wins
        opt = self._make_opt(chunk_token_budget=10_000, context_window=128_000)
        assert _chunk_budget(opt) == 10_000

    def test_minimum_is_1000(self):
        # Pathological case: tiny context window
        opt = self._make_opt(chunk_token_budget=500, context_window=500)
        assert _chunk_budget(opt) == 1_000

    def test_no_pipeline_section_returns_default(self):
        opt = SimpleNamespace()  # no pipeline attribute
        assert _chunk_budget(opt) == 20_000

    def test_no_provider_uses_budget_as_is(self):
        opt = SimpleNamespace(pipeline=SimpleNamespace(chunk_token_budget=30_000))
        assert _chunk_budget(opt) == 30_000

    def test_large_context_window_allows_large_budget(self):
        # GPT-4.1: 1M context, budget=700_000 → cap=750_000 → budget wins
        opt = self._make_opt(chunk_token_budget=700_000, context_window=1_000_000)
        assert _chunk_budget(opt) == 700_000

    def test_budget_exactly_at_cap_is_accepted(self):
        # budget == 75% of context_window → accepted unchanged
        opt = self._make_opt(chunk_token_budget=75_000, context_window=100_000)
        assert _chunk_budget(opt) == 75_000


# ── page_list_to_group_text chunk count ───────────────────────────────────────

class TestPageListToGroupText:

    def _make_pages(self, n, tokens_each=5_000):
        contents = [f"page {i} text" for i in range(n)]
        lengths  = [tokens_each] * n
        return contents, lengths

    def test_single_chunk_when_total_fits(self):
        contents, lengths = self._make_pages(3, tokens_each=5_000)
        groups = page_list_to_group_text(contents, lengths, max_tokens=20_000)
        assert len(groups) == 1

    def test_splits_into_multiple_chunks_when_over_budget(self):
        # 10 pages × 5_000 = 50_000 tokens, budget=10_000 → should split
        contents, lengths = self._make_pages(10, tokens_each=5_000)
        groups = page_list_to_group_text(contents, lengths, max_tokens=10_000)
        assert len(groups) > 1

    def test_larger_budget_fewer_chunks(self):
        contents, lengths = self._make_pages(20, tokens_each=5_000)
        groups_small = page_list_to_group_text(contents, lengths, max_tokens=10_000)
        groups_large = page_list_to_group_text(contents, lengths, max_tokens=50_000)
        assert len(groups_large) < len(groups_small)

    def test_empty_page_list_returns_empty(self):
        groups = page_list_to_group_text([], [], max_tokens=20_000)
        assert groups == [] or groups == ['']

    def test_single_page_fits_in_budget(self):
        # Page (100 tokens) fits inside budget (1_000) → one chunk
        groups = page_list_to_group_text(["hello"], [100], max_tokens=1_000)
        assert len(groups) == 1
        assert "hello" in groups[0]


# ── process_no_toc passes budget to grouper ───────────────────────────────────

class TestProcessNoTocUsesChunkBudget:

    @pytest.mark.asyncio
    async def test_small_budget_creates_more_chunks(self):
        """With a tiny budget, more groups → more generate_toc_continue calls."""
        from pageindex.page_index import process_no_toc

        # Build a fake page_list with enough content to split
        page_list = [(f"page text {i}", 5_000) for i in range(6)]  # 30_000 tokens total

        mock_provider = MagicMock()
        mock_provider.context_window = 1_000_000
        mock_provider.count_tokens = MagicMock(return_value=5_000)

        # opt with tiny budget → should split into multiple groups
        opt = SimpleNamespace(
            pipeline=SimpleNamespace(chunk_token_budget=8_000),
            provider=mock_provider,
        )

        init_result = [{"structure": "1", "title": "Intro", "physical_index": "<physical_index_1>"}]
        continue_result = [{"structure": "2", "title": "Methods", "physical_index": "<physical_index_3>"}]

        generate_init_calls = []
        generate_continue_calls = []

        async def mock_init(part, provider):
            generate_init_calls.append(part)
            return list(init_result)

        async def mock_continue(toc, part, provider):
            generate_continue_calls.append(part)
            return list(continue_result)

        mock_logger = MagicMock()
        mock_logger.info = MagicMock()

        with patch.object(_pi, "generate_toc_init", side_effect=mock_init), \
             patch.object(_pi, "generate_toc_continue", side_effect=mock_continue), \
             patch.object(_pi, "convert_physical_index_to_int", side_effect=lambda x: x):
            await process_no_toc(page_list, start_index=1, provider=mock_provider,
                                 opt=opt, logger=mock_logger)

        total_calls = len(generate_init_calls) + len(generate_continue_calls)
        assert total_calls > 1, "small budget should create multiple groups → multiple LLM calls"

    @pytest.mark.asyncio
    async def test_large_budget_single_chunk(self):
        """With a large budget, all pages fit in one group → only generate_toc_init called."""
        from pageindex.page_index import process_no_toc

        page_list = [(f"page text {i}", 500) for i in range(4)]  # 2_000 tokens total

        mock_provider = MagicMock()
        mock_provider.context_window = 1_000_000
        mock_provider.count_tokens = MagicMock(return_value=500)

        opt = SimpleNamespace(
            pipeline=SimpleNamespace(chunk_token_budget=50_000),
            provider=mock_provider,
        )

        generate_continue_calls = []

        async def mock_init(part, provider):
            return [{"structure": "1", "title": "Intro", "physical_index": "<physical_index_1>"}]

        async def mock_continue(toc, part, provider):
            generate_continue_calls.append(part)
            return []

        mock_logger = MagicMock()
        mock_logger.info = MagicMock()

        with patch.object(_pi, "generate_toc_init", side_effect=mock_init), \
             patch.object(_pi, "generate_toc_continue", side_effect=mock_continue), \
             patch.object(_pi, "convert_physical_index_to_int", side_effect=lambda x: x):
            await process_no_toc(page_list, start_index=1, provider=mock_provider,
                                 opt=opt, logger=mock_logger)

        assert generate_continue_calls == [], "single chunk → generate_toc_continue never called"

    @pytest.mark.asyncio
    async def test_context_window_cap_applied(self):
        """Budget larger than 75% of context_window gets capped."""
        from pageindex.page_index import process_no_toc

        # 4 pages × 10_000 = 40_000 tokens
        # budget=80_000 but context_window=40_000 → cap=30_000 → splits into 2
        page_list = [(f"page {i}", 10_000) for i in range(4)]

        mock_provider = MagicMock()
        mock_provider.context_window = 40_000
        mock_provider.count_tokens = MagicMock(return_value=10_000)

        opt = SimpleNamespace(
            pipeline=SimpleNamespace(chunk_token_budget=80_000),
            provider=mock_provider,
        )

        generate_continue_calls = []

        async def mock_init(part, provider):
            return [{"structure": "1", "title": "A", "physical_index": "<physical_index_1>"}]

        async def mock_continue(toc, part, provider):
            generate_continue_calls.append(1)
            return [{"structure": "2", "title": "B", "physical_index": "<physical_index_3>"}]

        mock_logger = MagicMock()
        mock_logger.info = MagicMock()

        with patch.object(_pi, "generate_toc_init", side_effect=mock_init), \
             patch.object(_pi, "generate_toc_continue", side_effect=mock_continue), \
             patch.object(_pi, "convert_physical_index_to_int", side_effect=lambda x: x):
            await process_no_toc(page_list, start_index=1, provider=mock_provider,
                                 opt=opt, logger=mock_logger)

        assert len(generate_continue_calls) >= 1, \
            "capped budget should force a split → generate_toc_continue called"
