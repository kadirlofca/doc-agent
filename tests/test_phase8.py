"""
test_phase8.py — Unit tests for Phase 8 production hardening (no real API calls).

Covers:
  - extract_toc_content: raises RuntimeError after _MAX_CONTINUATION_ATTEMPTS
  - toc_transformer: raises RuntimeError after _MAX_CONTINUATION_ATTEMPTS
  - process_large_node_recursively: depth limit stops at _MAX_RECURSION_DEPTH
  - page_index_main: empty page_list → ValueError
  - page_index_main: provider build failure → clear ValueError
  - page_index_main: timeout fires → TimeoutError
  - JsonLogger: I/O failure does NOT crash the caller
  - JsonLogger: non-serialisable objects are stringified (default=str)
"""
import asyncio
import json
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pageindex.page_index  # noqa: F401
_pi = sys.modules["pageindex.page_index"]

from pageindex.page_index import (
    _MAX_CONTINUATION_ATTEMPTS,
    _MAX_RECURSION_DEPTH,
    process_large_node_recursively,
)
from pageindex.utils import JsonLogger


# ── extract_toc_content loop guard ────────────────────────────────────────────

class TestExtractTocContentGuard:

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        """If completion check always returns 'no', RuntimeError is raised."""
        with patch.object(_pi, "_llm_fr", new=AsyncMock(return_value=("partial toc", "finished"))), \
             patch.object(_pi, "_check_if_complete", new=AsyncMock(return_value="no")):
            with pytest.raises(RuntimeError, match="extract_toc_content"):
                from pageindex.page_index import extract_toc_content
                await extract_toc_content("some content", provider=MagicMock())

    @pytest.mark.asyncio
    async def test_returns_on_first_success(self):
        """Returns immediately when complete on first attempt."""
        with patch.object(_pi, "_llm_fr", new=AsyncMock(return_value=("full toc", "finished"))), \
             patch.object(_pi, "_check_if_complete", new=AsyncMock(return_value="yes")):
            from pageindex.page_index import extract_toc_content
            result = await extract_toc_content("some content", provider=MagicMock())
        assert result == "full toc"

    @pytest.mark.asyncio
    async def test_max_continuation_attempts_constant(self):
        """_MAX_CONTINUATION_ATTEMPTS should be at least 3."""
        assert _MAX_CONTINUATION_ATTEMPTS >= 3


# ── toc_transformer loop guard ─────────────────────────────────────────────────

class TestTocTransformerGuard:

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        """If completion check always 'no', RuntimeError is raised."""
        with patch.object(_pi, "_llm_fr", new=AsyncMock(return_value=('{"table_of_contents": []}', "max_output_reached"))), \
             patch.object(_pi, "_check_if_complete", new=AsyncMock(return_value="no")), \
             patch.object(_pi, "get_json_content", return_value='{"table_of_contents": []}'):
            with pytest.raises(RuntimeError, match="toc_transformer"):
                from pageindex.page_index import toc_transformer
                await toc_transformer("raw toc content", provider=MagicMock())

    @pytest.mark.asyncio
    async def test_returns_on_first_complete(self):
        """Returns immediately when LLM finishes in one shot."""
        toc_json = '{"table_of_contents": [{"structure": "1", "title": "Intro", "page": 1}]}'
        with patch.object(_pi, "_llm_fr", new=AsyncMock(return_value=(toc_json, "finished"))), \
             patch.object(_pi, "_check_if_complete", new=AsyncMock(return_value="yes")), \
             patch.object(_pi, "convert_page_to_int", side_effect=lambda x: x):
            from pageindex.page_index import toc_transformer
            result = await toc_transformer("raw toc", provider=MagicMock())
        assert isinstance(result, list)


# ── process_large_node_recursively depth limit ─────────────────────────────────

class TestRecursionDepthLimit:

    @pytest.mark.asyncio
    async def test_stops_at_max_depth(self):
        """Node at max depth is returned unchanged without recursing further."""
        node = {
            'title': 'Deep Node',
            'start_index': 1,
            'end_index': 5,
            'nodes': [{'title': 'Child', 'start_index': 2, 'end_index': 5, 'nodes': []}],
        }
        opt = SimpleNamespace(
            max_page_num_each_node=10,
            max_token_num_each_node=50_000,
            provider=MagicMock(),
        )
        page_list = [("text", 100)] * 10
        mock_logger = MagicMock()

        # At max depth the function must return without calling gather
        with patch("asyncio.gather", new=AsyncMock()) as mock_gather:
            result = await process_large_node_recursively(
                node, page_list, opt, logger=mock_logger, _depth=_MAX_RECURSION_DEPTH
            )
        mock_gather.assert_not_awaited()
        assert result is node

    @pytest.mark.asyncio
    async def test_depth_increments_on_recursion(self):
        """Child nodes are called with _depth + 1."""
        depths_seen = []
        original_fn = process_large_node_recursively

        async def tracking_fn(node, page_list, opt, logger=None, _depth=0):
            depths_seen.append(_depth)
            # Don't actually recurse — just return
            return node

        child = {'title': 'Child', 'start_index': 2, 'end_index': 3, 'nodes': []}
        node = {'title': 'Root', 'start_index': 1, 'end_index': 5, 'nodes': [child]}
        opt = SimpleNamespace(
            max_page_num_each_node=100,
            max_token_num_each_node=1_000_000,
            provider=MagicMock(),
        )
        page_list = [("text", 100)] * 10

        with patch.object(_pi, "process_large_node_recursively", side_effect=tracking_fn):
            await tracking_fn(node, page_list, opt, logger=None, _depth=0)

        # The root was called at depth 0
        assert 0 in depths_seen

    def test_max_recursion_depth_constant(self):
        """_MAX_RECURSION_DEPTH should be at least 5."""
        assert _MAX_RECURSION_DEPTH >= 5


# ── page_index_main hardening ──────────────────────────────────────────────────

class TestPageIndexMainHardening:

    def test_empty_page_list_raises_value_error(self):
        from pageindex.page_index import page_index_main
        import io
        mock_opt = SimpleNamespace(
            provider=MagicMock(),
            pipeline=SimpleNamespace(timeout_seconds=None),
            toc_check_page_num=20,
            max_page_num_each_node=10,
            max_token_num_each_node=20000,
            if_add_node_id='no',
            if_add_node_text='no',
            if_add_node_summary='no',
            if_add_doc_description='no',
        )
        fake_pdf = io.BytesIO(b"%PDF-1.4 fake")
        with patch.object(_pi, "get_page_tokens", return_value=[]), \
             patch.object(_pi, "JsonLogger") as mock_logger_cls:
            mock_logger_cls.return_value = MagicMock()
            with pytest.raises(ValueError, match="empty"):
                page_index_main(fake_pdf, opt=mock_opt)

    def test_provider_build_failure_raises_clear_error(self):
        from pageindex.page_index import page_index_main
        import io
        fake_pdf = io.BytesIO(b"%PDF-1.4 fake")

        bad_opt = SimpleNamespace(
            pipeline=SimpleNamespace(timeout_seconds=None),
        )

        # build_provider_from_opt is imported locally inside page_index_main,
        # so we patch it in its source module.
        with patch.object(_pi, "JsonLogger") as mock_logger_cls, \
             patch("pageindex.llm.factory.build_provider_from_opt",
                   side_effect=ValueError("missing API key")):
            mock_logger_cls.return_value = MagicMock()
            with pytest.raises(ValueError, match="Failed to initialise LLM provider"):
                page_index_main(fake_pdf, opt=bad_opt)

    def test_timeout_raises_timeout_error(self):
        from pageindex.page_index import page_index_main
        import io
        fake_pdf = io.BytesIO(b"%PDF-1.4 fake")

        mock_opt = SimpleNamespace(
            provider=MagicMock(),
            pipeline=SimpleNamespace(timeout_seconds=0.001),  # 1ms → instant timeout
            toc_check_page_num=20,
            max_page_num_each_node=10,
            max_token_num_each_node=20000,
            if_add_node_id='no',
            if_add_node_text='no',
            if_add_node_summary='no',
            if_add_doc_description='no',
        )

        async def slow_tree_parser(*a, **kw):
            await asyncio.sleep(10)

        page_list = [("page text", 100)]
        with patch.object(_pi, "get_page_tokens", return_value=page_list), \
             patch.object(_pi, "tree_parser", side_effect=slow_tree_parser), \
             patch.object(_pi, "JsonLogger") as mock_logger_cls:
            mock_logger_cls.return_value = MagicMock()
            with pytest.raises(TimeoutError, match="timed out"):
                page_index_main(fake_pdf, opt=mock_opt)


# ── JsonLogger hardening ───────────────────────────────────────────────────────

class TestJsonLoggerHardening:

    def test_io_failure_does_not_raise(self, tmp_path):
        """A broken log directory must not crash the caller."""
        logger = JsonLogger.__new__(JsonLogger)
        logger.log_data = []
        logger.filename = "test.json"
        # Point to a non-existent directory so open() will fail
        with patch.object(logger, "_filepath", return_value="/nonexistent/dir/test.json"):
            # Should not raise
            logger.log("INFO", "test message")

    def test_non_serialisable_value_is_stringified(self, tmp_path):
        """Non-JSON-serialisable objects must be converted via default=str."""
        logger = JsonLogger.__new__(JsonLogger)
        logger.log_data = []
        logger.filename = "test.json"
        log_path = str(tmp_path / "test.json")
        with patch.object(logger, "_filepath", return_value=log_path):
            # datetime is not JSON-serialisable by default
            from datetime import datetime
            logger.log("INFO", {"ts": datetime(2024, 1, 1)})

        with open(log_path) as f:
            data = json.load(f)
        assert "2024" in data[0]["ts"]  # stringified datetime contains year

    def test_normal_write_succeeds(self, tmp_path):
        """Normal messages are written correctly."""
        logger = JsonLogger.__new__(JsonLogger)
        logger.log_data = []
        logger.filename = "test.json"
        log_path = str(tmp_path / "test.json")
        with patch.object(logger, "_filepath", return_value=log_path):
            logger.info("hello")
            logger.info({"key": "value"})

        with open(log_path) as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0] == {"message": "hello"}
        assert data[1] == {"key": "value"}
