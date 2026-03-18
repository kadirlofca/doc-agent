"""
test_phase4.py — Unit tests for Phase 4 async parallelization (no real API calls).

Covers:
  - _gather_bounded: respects concurrency cap, preserves order, handles empty input
  - find_toc_pages: all page checks run in parallel, TOC block reconstructed correctly,
                    works with no-TOC pages, works with TOC in middle of window
"""
import asyncio
import time
from types import SimpleNamespace
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import pytest

# pageindex/__init__.py does `from .page_index import *` which shadows the
# submodule name with the exported function. Import the submodule first so it
# gets registered in sys.modules, then retrieve it from there.
import pageindex.page_index  # noqa: F401 — registers the module
_pi = sys.modules["pageindex.page_index"]

from pageindex.page_index import _gather_bounded, find_toc_pages


# ── _gather_bounded ────────────────────────────────────────────────────────────

class TestGatherBounded:

    @pytest.mark.asyncio
    async def test_returns_results_in_order(self):
        async def coro(n):
            return n * 2

        results = await _gather_bounded([coro(i) for i in range(5)], concurrency=3)
        assert results == [0, 2, 4, 6, 8]

    @pytest.mark.asyncio
    async def test_empty_list(self):
        results = await _gather_bounded([], concurrency=4)
        assert results == []

    @pytest.mark.asyncio
    async def test_single_item(self):
        async def coro():
            return 42

        results = await _gather_bounded([coro()], concurrency=4)
        assert results == [42]

    @pytest.mark.asyncio
    async def test_respects_concurrency_cap(self):
        """Peak concurrent executions must not exceed the cap."""
        concurrent = 0
        peak = 0
        concurrency_cap = 3

        async def slow_coro(n):
            nonlocal concurrent, peak
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.02)
            concurrent -= 1
            return n

        results = await _gather_bounded(
            [slow_coro(i) for i in range(10)], concurrency=concurrency_cap
        )
        assert peak <= concurrency_cap
        assert results == list(range(10))

    @pytest.mark.asyncio
    async def test_concurrency_1_serialises(self):
        """concurrency=1 must force sequential execution."""
        order = []

        async def coro(n):
            order.append(f"start-{n}")
            await asyncio.sleep(0.005)
            order.append(f"end-{n}")
            return n

        await _gather_bounded([coro(i) for i in range(3)], concurrency=1)
        # With concurrency=1 each must finish before the next starts
        assert order == ["start-0", "end-0", "start-1", "end-1", "start-2", "end-2"]

    @pytest.mark.asyncio
    async def test_parallel_is_faster_than_serial(self):
        """concurrency=N should finish faster than N * task_duration."""

        async def slow_coro(_):
            await asyncio.sleep(0.05)

        n = 8
        t0 = time.perf_counter()
        await _gather_bounded([slow_coro(i) for i in range(n)], concurrency=n)
        elapsed = time.perf_counter() - t0

        # All n tasks run simultaneously → should finish in ~0.05s, not 8*0.05=0.4s
        assert elapsed < 0.15, f"Expected ~0.05s, got {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_concurrency_zero_treated_as_one(self):
        """concurrency=0 should not raise — treated as 1."""
        async def coro():
            return 7

        results = await _gather_bounded([coro()], concurrency=0)
        assert results == [7]

    @pytest.mark.asyncio
    async def test_exceptions_propagate(self):
        async def bad_coro():
            raise ValueError("oops")

        with pytest.raises(ValueError, match="oops"):
            await _gather_bounded([bad_coro()], concurrency=4)


# ── find_toc_pages ─────────────────────────────────────────────────────────────

def _make_opt(toc_check_page_num: int = 20, concurrency: int = 8,
              provider=None) -> SimpleNamespace:
    pipeline = SimpleNamespace(concurrency=concurrency)
    return SimpleNamespace(
        toc_check_page_num=toc_check_page_num,
        pipeline=pipeline,
        provider=provider or MagicMock(),
    )


def _make_page_list(n: int) -> List:
    """Return a list of (text, tokens) tuples."""
    return [(f"page text {i}", 100) for i in range(n)]


class TestFindTocPages:

    @pytest.mark.asyncio
    async def test_no_toc_pages_returns_empty(self):
        """All pages return 'no' → empty list."""
        opt = _make_opt()
        page_list = _make_page_list(10)

        with patch.object(_pi, "toc_detector_single_page",
                   new=AsyncMock(return_value="no")):
            result = await find_toc_pages(0, page_list, opt)

        assert result == []

    @pytest.mark.asyncio
    async def test_all_toc_pages(self):
        """All pages return 'yes' → all indices returned."""
        opt = _make_opt(toc_check_page_num=5)
        page_list = _make_page_list(5)

        with patch.object(_pi, "toc_detector_single_page",
                   new=AsyncMock(return_value="yes")):
            result = await find_toc_pages(0, page_list, opt)

        assert result == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_toc_at_start_stops_at_first_no(self):
        """Pages 0,1,2 are yes; page 3 is no → returns [0,1,2]."""
        opt = _make_opt(toc_check_page_num=10)
        page_list = _make_page_list(10)
        answers = {0: "yes", 1: "yes", 2: "yes", 3: "no", 4: "no"}

        async def mock_detector(content, provider=None):
            idx = int(content.split()[-1])
            return answers.get(idx, "no")

        with patch.object(_pi, "toc_detector_single_page",
                   side_effect=mock_detector):
            result = await find_toc_pages(0, page_list, opt)

        assert result == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_toc_in_middle_of_window(self):
        """Pages 0,1 are no; pages 2,3 are yes; page 4 is no → [2,3]."""
        opt = _make_opt(toc_check_page_num=10)
        page_list = _make_page_list(10)
        answers = {0: "no", 1: "no", 2: "yes", 3: "yes", 4: "no"}

        async def mock_detector(content, provider=None):
            idx = int(content.split()[-1])
            return answers.get(idx, "no")

        with patch.object(_pi, "toc_detector_single_page",
                   side_effect=mock_detector):
            result = await find_toc_pages(0, page_list, opt)

        assert result == [2, 3]

    @pytest.mark.asyncio
    async def test_respects_toc_check_page_num_window(self):
        """Only checks up to toc_check_page_num pages, not the whole document."""
        opt = _make_opt(toc_check_page_num=5)
        page_list = _make_page_list(100)

        call_indices = []

        async def mock_detector(content, provider=None):
            idx = int(content.split()[-1])
            call_indices.append(idx)
            return "no"

        with patch.object(_pi, "toc_detector_single_page",
                   side_effect=mock_detector):
            await find_toc_pages(0, page_list, opt)

        assert max(call_indices) < 5  # never checked page 5+

    @pytest.mark.asyncio
    async def test_start_page_index_offset(self):
        """start_page_index shifts the window."""
        opt = _make_opt(toc_check_page_num=3)
        page_list = _make_page_list(10)
        answers = {5: "yes", 6: "yes", 7: "no"}

        async def mock_detector(content, provider=None):
            idx = int(content.split()[-1])
            return answers.get(idx, "no")

        with patch.object(_pi, "toc_detector_single_page",
                   side_effect=mock_detector):
            result = await find_toc_pages(5, page_list, opt)

        assert result == [5, 6]

    @pytest.mark.asyncio
    async def test_empty_page_list_returns_empty(self):
        opt = _make_opt(toc_check_page_num=10)

        with patch.object(_pi, "toc_detector_single_page",
                   new=AsyncMock(return_value="yes")):
            result = await find_toc_pages(0, [], opt)

        assert result == []

    @pytest.mark.asyncio
    async def test_checks_run_in_parallel(self):
        """All page checks must fire concurrently, not one-at-a-time."""
        opt = _make_opt(toc_check_page_num=5, concurrency=8)
        page_list = _make_page_list(5)

        call_times = []

        async def slow_detector(content, provider=None):
            call_times.append(time.perf_counter())
            await asyncio.sleep(0.05)
            return "no"

        with patch.object(_pi, "toc_detector_single_page",
                   side_effect=slow_detector):
            t0 = time.perf_counter()
            await find_toc_pages(0, page_list, opt)
            elapsed = time.perf_counter() - t0

        # 5 tasks × 0.05s each; parallel → ~0.05s, serial → 0.25s
        assert len(call_times) == 5
        assert elapsed < 0.15, f"Expected parallel (~0.05s), got {elapsed:.2f}s — looks serial"
        # All calls fired within a short burst (parallel start times close together)
        spread = max(call_times) - min(call_times)
        assert spread < 0.03, f"Calls should start near-simultaneously, spread={spread:.3f}s"
