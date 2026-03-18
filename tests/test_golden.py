"""
test_golden.py — Phase 0 slow regression tests (require live OpenAI API calls).

These establish the BASELINE: the current unmodified pipeline must produce
output that matches the golden files in tests/results/ before any refactoring.

Run with:
    pytest tests/test_golden.py -m slow -v -s

The -s flag lets you see LLM call progress printed by page_index_main.
"""
import json
from pathlib import Path
from types import SimpleNamespace as config

import pytest

from compare import compare_structures

# Tolerance for live runs — slightly looser than the default comparator values
# because LLMs have minor non-determinism even at temperature=0.
TITLE_THRESHOLD = 0.80
PAGE_TOLERANCE  = 2


def _run_pipeline(pdf_path: Path, tmp_path: Path) -> dict:
    """
    Run the current unmodified pipeline on pdf_path and return the output dict.
    Also writes the output to tmp_path for post-failure inspection.
    Uses minimal options (no summaries) to keep test runtime short.
    """
    from pageindex.utils import ConfigLoader
    from pageindex.page_index import page_index_main

    opt = ConfigLoader().load({
        "if_add_node_summary":    "no",
        "if_add_doc_description": "no",
        "if_add_node_text":       "no",
    })

    actual = page_index_main(str(pdf_path), opt)

    out_file = tmp_path / f"{pdf_path.stem}_actual.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(actual, f, indent=2, ensure_ascii=False)

    print(f"\n  [golden] actual output saved → {out_file}")
    return actual


def _load_golden(golden_path: Path) -> dict:
    with open(golden_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _assert_matches(actual: dict, golden: dict, label: str, tmp_path: Path) -> None:
    result = compare_structures(
        actual, golden,
        title_threshold=TITLE_THRESHOLD,
        page_tolerance=PAGE_TOLERANCE,
    )
    print(f"\n  [golden] {label}:\n{result.summary()}")
    assert result.passed, (
        f"\n{label} output does not match golden.\n"
        f"{result.summary()}\n"
        f"Inspect actual output in tmp_path: {tmp_path}"
    )


# ── Fast PDF ──────────────────────────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.requires_api
class TestGoldenFastPDF:
    """
    Primary regression: q1-fy25-earnings.pdf (~100 KB, ~10 pages).
    Expected runtime: ~30 s with OpenAI gpt-4o.
    """

    def test_structure_matches_golden(
        self, fast_pdf, fast_golden, tmp_path, openai_api_key
    ):
        actual = _run_pipeline(fast_pdf, tmp_path)
        golden = _load_golden(fast_golden)
        _assert_matches(actual, golden, "q1-fy25-earnings", tmp_path)


# ── Medium PDF ────────────────────────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.requires_api
class TestGoldenMediumPDF:
    """
    Secondary regression: 2023-annual-report-truncated.pdf (~1.4 MB).
    Expected runtime: ~2 min with OpenAI gpt-4o.
    """

    def test_structure_matches_golden(
        self, medium_pdf, medium_golden, tmp_path, openai_api_key
    ):
        actual = _run_pipeline(medium_pdf, tmp_path)
        golden = _load_golden(medium_golden)
        _assert_matches(actual, golden, "2023-annual-report-truncated", tmp_path)


# ── Large PDF (manual / CI nightly only) ─────────────────────────────────────

@pytest.mark.slow
@pytest.mark.requires_api
class TestGoldenLargePDF:
    """
    PRML textbook (18 MB, ~700 pages).  Run manually or in nightly CI only.

    pytest tests/test_golden.py::TestGoldenLargePDF -m slow -v -s
    """

    def test_structure_matches_golden(
        self, large_pdf, large_golden, tmp_path, openai_api_key
    ):
        actual = _run_pipeline(large_pdf, tmp_path)
        golden = _load_golden(large_golden)
        _assert_matches(actual, golden, "PRML", tmp_path)
