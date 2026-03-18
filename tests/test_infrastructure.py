"""
test_infrastructure.py — Phase 0 baseline tests (no API calls required).

Tests:
  1. Comparator unit tests      — verify compare.py logic is correct
  2. Golden file validity        — all existing golden JSONs are well-formed
  3. Import checks               — project code is importable without errors
  4. Config checks               — ConfigLoader returns correct defaults/overrides

Run with:
    pytest tests/test_infrastructure.py -v
or as part of the full fast suite:
    pytest -m "not slow" -v
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from compare import (
    CompareResult,
    compare_structures,
    compare_files,
    titles_match,
    page_range_matches,
)

GOLDEN_DIR = Path(__file__).parent / "results"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*_structure.json"))


# ── Helper ────────────────────────────────────────────────────────────────────

def _node(
    title: str,
    start: int,
    end: int,
    children: Optional[List[Dict[str, Any]]] = None,
    node_id: str = "0001",
    summary: str = "",
) -> Dict[str, Any]:
    """Build a minimal tree node dict for use in comparator tests."""
    n: Dict[str, Any] = {
        "title":       title,
        "start_index": start,
        "end_index":   end,
        "node_id":     node_id,
    }
    if summary:
        n["summary"] = summary
    if children is not None:
        n["nodes"] = children
    return n


# Cannot use `Optional` as a default argument annotation in Python 3.9 without
# importing it, and mypy is not in scope here — keep the helper untyped.
# Redefine without type hint to keep file clean:
def _node(title, start, end, children=None, node_id="0001", summary=""):  # noqa: F811
    n = {"title": title, "start_index": start, "end_index": end, "node_id": node_id}
    if summary:
        n["summary"] = summary
    if children is not None:
        n["nodes"] = children
    return n


# ── 1. Comparator unit tests ──────────────────────────────────────────────────

class TestTitlesMatch:

    def test_exact_match(self):
        assert titles_match("Introduction", "Introduction") is True

    def test_exact_match_is_always_true_regardless_of_threshold(self):
        # Even with threshold=1.0 an exact match must pass
        assert titles_match("Introduction", "Introduction", threshold=1.0) is True

    def test_case_insensitive(self):
        assert titles_match("introduction", "Introduction") is True

    def test_leading_trailing_whitespace(self):
        assert titles_match("  Introduction  ", "Introduction") is True

    def test_single_char_typo_passes(self):
        # "Introdction" vs "Introduction" — ratio well above 0.85
        assert titles_match("Introdction", "Introduction") is True

    def test_completely_different_titles_fail(self):
        assert titles_match("Chapter 1", "Appendix Z") is False

    def test_both_empty(self):
        assert titles_match("", "") is True

    def test_one_empty_fails(self):
        assert titles_match("", "Introduction") is False
        assert titles_match("Introduction", "") is False

    def test_custom_threshold_stricter(self):
        # "Intro" vs "Introduction" has low ratio — fails at high threshold
        assert titles_match("Intro", "Introduction", threshold=0.99) is False

    def test_custom_threshold_looser(self):
        assert titles_match("Intro", "Introduction", threshold=0.50) is True

    def test_numbered_sections_match(self):
        assert titles_match("1. Introduction", "1. Introduction") is True

    def test_short_common_words_distinct(self):
        # "Results" vs "Methods" — clearly different
        assert titles_match("Results", "Methods") is False


class TestPageRangeMatches:

    def test_exact_match(self):
        assert page_range_matches(
            {"start_index": 5, "end_index": 10},
            {"start_index": 5, "end_index": 10},
        ) is True

    def test_within_default_tolerance(self):
        assert page_range_matches(
            {"start_index": 5,  "end_index": 10},
            {"start_index": 6,  "end_index": 11},
        ) is True

    def test_at_exact_tolerance_boundary(self):
        assert page_range_matches(
            {"start_index": 5,  "end_index": 10},
            {"start_index": 6,  "end_index": 10},
            tolerance=1,
        ) is True

    def test_outside_tolerance_fails(self):
        assert page_range_matches(
            {"start_index": 5,  "end_index": 10},
            {"start_index": 9,  "end_index": 14},
        ) is False

    def test_missing_start_index_skipped(self):
        assert page_range_matches(
            {},
            {"start_index": 5, "end_index": 10},
        ) is True

    def test_missing_end_index_skipped(self):
        assert page_range_matches(
            {"start_index": 5},
            {"start_index": 5, "end_index": 10},
        ) is True

    def test_custom_tolerance_zero(self):
        assert page_range_matches(
            {"start_index": 5, "end_index": 10},
            {"start_index": 6, "end_index": 10},
            tolerance=0,
        ) is False

    def test_custom_tolerance_wide(self):
        assert page_range_matches(
            {"start_index": 5, "end_index": 10},
            {"start_index": 9, "end_index": 14},
            tolerance=5,
        ) is True


class TestCompareStructures:

    def test_identical_structures_pass(self):
        s = [_node("Introduction", 1, 5)]
        result = compare_structures({"structure": s}, {"structure": s})
        assert result.passed is True
        assert result.mismatches == []

    def test_title_fuzzy_match_passes(self):
        actual = {"structure": [_node("Introdction", 1, 5)]}   # typo
        golden = {"structure": [_node("Introduction", 1, 5)]}
        result = compare_structures(actual, golden)
        assert result.passed is True

    def test_completely_different_title_fails(self):
        actual = {"structure": [_node("Chapter One",  1, 5)]}
        golden = {"structure": [_node("Appendix Z",   1, 5)]}
        result = compare_structures(actual, golden)
        assert result.passed is False
        assert any("title mismatch" in m for m in result.mismatches)

    def test_page_range_within_tolerance_passes(self):
        actual = {"structure": [_node("Intro", 1, 5)]}
        golden = {"structure": [_node("Intro", 2, 6)]}   # off by 1
        result = compare_structures(actual, golden)
        assert result.passed is True

    def test_page_range_beyond_tolerance_fails(self):
        actual = {"structure": [_node("Intro", 1,  5)]}
        golden = {"structure": [_node("Intro", 8, 12)]}   # off by 7
        result = compare_structures(actual, golden)
        assert result.passed is False
        assert any("page range" in m for m in result.mismatches)

    def test_node_count_diff_by_one_is_warning_not_failure(self):
        actual = {"structure": [
            _node("Chapter 1", 1, 5),
            _node("Chapter 2", 6, 10),
        ]}
        golden = {"structure": [
            _node("Chapter 1", 1, 5),
            _node("Chapter 2", 6, 10),
            _node("Chapter 3", 11, 15),
        ]}
        result = compare_structures(actual, golden)
        assert result.passed is True                          # warnings don't fail
        assert any("node count" in w for w in result.warnings)

    def test_node_count_diff_by_three_is_hard_failure(self):
        actual = {"structure": [_node("Chapter 1", 1, 5)]}
        golden = {"structure": [
            _node("Chapter 1", 1, 5),
            _node("Chapter 2", 6, 10),
            _node("Chapter 3", 11, 15),
            _node("Chapter 4", 16, 20),
        ]}
        result = compare_structures(actual, golden)
        assert result.passed is False

    def test_node_id_differences_are_ignored(self):
        actual = {"structure": [{"title": "Intro", "start_index": 1,
                                 "end_index": 5, "node_id": "9999"}]}
        golden = {"structure": [{"title": "Intro", "start_index": 1,
                                 "end_index": 5, "node_id": "0001"}]}
        result = compare_structures(actual, golden)
        assert result.passed is True

    def test_summary_differences_are_ignored(self):
        actual = {"structure": [_node("Intro", 1, 5, summary="Different summary A")]}
        golden = {"structure": [_node("Intro", 1, 5, summary="Different summary B")]}
        result = compare_structures(actual, golden)
        assert result.passed is True

    def test_nested_children_are_compared(self):
        actual = {"structure": [_node("Part I", 1, 20, children=[
            _node("Chapter 1", 1, 10),
            _node("Chapter 2", 11, 20),
        ])]}
        golden = {"structure": [_node("Part I", 1, 20, children=[
            _node("Chapter 1", 1, 10),
            _node("Completely Different",  11, 20),   # mismatch at child level
        ])]}
        result = compare_structures(actual, golden)
        assert result.passed is False
        assert any("title mismatch" in m for m in result.mismatches)

    def test_nested_children_pass_when_matching(self):
        children = [_node("Chapter 1", 1, 10), _node("Chapter 2", 11, 20)]
        s = [_node("Part I", 1, 20, children=children)]
        result = compare_structures({"structure": s}, {"structure": s})
        assert result.passed is True

    def test_doc_name_mismatch_is_warning_not_failure(self):
        actual = {"doc_name": "fileA.pdf", "structure": [_node("Intro", 1, 5)]}
        golden = {"doc_name": "fileB.pdf", "structure": [_node("Intro", 1, 5)]}
        result = compare_structures(actual, golden)
        assert result.passed is True
        assert any("doc_name" in w for w in result.warnings)

    def test_structure_as_single_dict_is_normalised(self):
        # Some edge cases return a single dict instead of a list
        single = _node("Intro", 1, 5)
        result = compare_structures(
            {"structure": single},
            {"structure": [single]},
        )
        assert result.passed is True

    def test_empty_structures_match(self):
        result = compare_structures({"structure": []}, {"structure": []})
        assert result.passed is True

    def test_compare_result_bool_false_when_failed(self):
        actual = {"structure": [_node("Chapter One", 1, 5)]}
        golden = {"structure": [_node("Appendix Z",  1, 5)]}
        result = compare_structures(actual, golden)
        assert bool(result) is False

    def test_compare_result_bool_true_when_passed(self):
        s = [_node("Introduction", 1, 5)]
        result = compare_structures({"structure": s}, {"structure": s})
        assert bool(result) is True

    def test_summary_contains_passed(self):
        s = [_node("Introduction", 1, 5)]
        result = compare_structures({"structure": s}, {"structure": s})
        assert "PASSED" in result.summary()

    def test_summary_contains_failed_and_details(self):
        actual = {"structure": [_node("Wrong", 1, 5)]}
        golden = {"structure": [_node("Correct", 1, 5)]}
        result = compare_structures(actual, golden)
        summary = result.summary()
        assert "FAILED"   in summary
        assert "mismatch" in summary


# ── 2. Golden file validity ───────────────────────────────────────────────────

class TestGoldenFileValidity:
    """
    Validates every JSON in tests/results/ without running the pipeline.
    These tests run in milliseconds.
    """

    @pytest.mark.parametrize("golden_path", GOLDEN_FILES, ids=lambda p: p.name)
    def test_is_valid_json(self, golden_path):
        with open(golden_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), f"{golden_path.name}: root must be a dict"

    @pytest.mark.parametrize("golden_path", GOLDEN_FILES, ids=lambda p: p.name)
    def test_has_required_top_level_keys(self, golden_path):
        with open(golden_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "doc_name"  in data, f"{golden_path.name}: missing 'doc_name'"
        assert "structure" in data, f"{golden_path.name}: missing 'structure'"
        assert isinstance(data["structure"], list), \
            f"{golden_path.name}: 'structure' must be a list"
        assert len(data["structure"]) > 0, \
            f"{golden_path.name}: 'structure' must be non-empty"

    @pytest.mark.parametrize("golden_path", GOLDEN_FILES, ids=lambda p: p.name)
    def test_all_nodes_have_title_and_page_range(self, golden_path):
        with open(golden_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        def check_node(node: dict, path: str) -> None:
            assert "title"       in node, f"{path}: missing 'title'"
            assert "start_index" in node, f"{path}: missing 'start_index'"
            assert "end_index"   in node, f"{path}: missing 'end_index'"
            assert isinstance(node["start_index"], int), \
                f"{path}: 'start_index' is not int"
            assert isinstance(node["end_index"], int), \
                f"{path}: 'end_index' is not int"
            assert node["start_index"] <= node["end_index"], \
                f"{path}: start_index ({node['start_index']}) > end_index ({node['end_index']})"
            for i, child in enumerate(node.get("nodes") or []):
                check_node(child, f"{path}.nodes[{i}]")

        for i, node in enumerate(data["structure"]):
            check_node(node, f"{golden_path.name} structure[{i}]")

    @pytest.mark.parametrize("golden_path", GOLDEN_FILES, ids=lambda p: p.name)
    def test_self_comparison_always_passes(self, golden_path):
        """
        Comparing a golden file against itself must always return passed=True.
        This verifies the comparator's correctness on real data.
        """
        with open(golden_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = compare_structures(data, data)
        assert result.passed is True, (
            f"Self-comparison of {golden_path.name} unexpectedly failed:\n"
            f"{result.summary()}"
        )


# ── 3. Import checks ──────────────────────────────────────────────────────────

class TestImports:
    """Verify the package is importable without a running API key."""

    def test_pageindex_package_importable(self):
        import pageindex  # noqa: F401

    def test_page_index_main_importable(self):
        from pageindex.page_index import page_index_main  # noqa: F401
        assert callable(page_index_main)

    def test_utils_importable(self):
        from pageindex import utils  # noqa: F401
        assert utils is not None

    def test_config_loader_importable(self):
        from pageindex.utils import ConfigLoader
        assert ConfigLoader is not None

    def test_md_to_tree_importable(self):
        from pageindex.page_index_md import md_to_tree  # noqa: F401
        assert callable(md_to_tree)


# ── 4. Config checks ──────────────────────────────────────────────────────────

class TestConfig:
    """Verify ConfigLoader reads config.yaml correctly."""

    def test_loads_default_model(self):
        from pageindex.utils import ConfigLoader
        cfg = ConfigLoader().load()
        assert cfg.model == "gpt-4o-2024-11-20"

    def test_loads_default_toc_check_page_num(self):
        from pageindex.utils import ConfigLoader
        cfg = ConfigLoader().load()
        assert cfg.toc_check_page_num == 20

    def test_loads_default_max_page_num_each_node(self):
        from pageindex.utils import ConfigLoader
        cfg = ConfigLoader().load()
        assert cfg.max_page_num_each_node == 10

    def test_loads_default_max_token_num_each_node(self):
        from pageindex.utils import ConfigLoader
        cfg = ConfigLoader().load()
        assert cfg.max_token_num_each_node == 20000

    def test_loads_default_flags(self):
        from pageindex.utils import ConfigLoader
        cfg = ConfigLoader().load()
        assert cfg.if_add_node_id      == "yes"
        assert cfg.if_add_node_summary == "yes"

    def test_user_override_respected(self):
        from pageindex.utils import ConfigLoader
        cfg = ConfigLoader().load({"model": "gpt-4-turbo"})
        assert cfg.model == "gpt-4-turbo"
        # Other defaults should be preserved
        assert cfg.toc_check_page_num == 20

    def test_multiple_overrides(self):
        from pageindex.utils import ConfigLoader
        cfg = ConfigLoader().load({
            "model":                 "gpt-4-turbo",
            "toc_check_page_num":    10,
            "if_add_node_summary":   "no",
        })
        assert cfg.model               == "gpt-4-turbo"
        assert cfg.toc_check_page_num  == 10
        assert cfg.if_add_node_summary == "no"
        assert cfg.max_page_num_each_node == 10   # default preserved

    def test_unknown_key_raises_value_error(self):
        from pageindex.utils import ConfigLoader
        with pytest.raises(ValueError, match="Unknown config keys"):
            ConfigLoader().load({"definitely_not_a_real_key": "value"})

    def test_none_opt_uses_all_defaults(self):
        from pageindex.utils import ConfigLoader
        cfg_none  = ConfigLoader().load(None)
        cfg_empty = ConfigLoader().load({})
        assert cfg_none.model == cfg_empty.model
        assert cfg_none.toc_check_page_num == cfg_empty.toc_check_page_num
