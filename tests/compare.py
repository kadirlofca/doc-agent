"""
compare.py — Golden-file structural comparator for PageIndex outputs.

Rules:
  - Titles are fuzzy-matched via SequenceMatcher (default threshold 0.85).
  - Page ranges are checked with ±tolerance pages (default ±1).
  - Ignored fields: node_id, summary, prefix_summary, doc_description, text.
  - A node-count difference of exactly 1 is a WARNING (not a failure).
  - A node-count difference of 2+ is a MISMATCH (hard failure).
"""
import json
import difflib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class CompareResult:
    passed: bool
    mismatches: List[str] = field(default_factory=list)
    warnings: List[str]   = field(default_factory=list)

    def summary(self) -> str:
        status = "✓ PASSED" if self.passed else "✗ FAILED"
        lines = [status]
        if self.mismatches:
            lines.append(f"  {len(self.mismatches)} mismatch(es):")
            for m in self.mismatches:
                lines.append(f"    FAIL  {m}")
        if self.warnings:
            lines.append(f"  {len(self.warnings)} warning(s):")
            for w in self.warnings:
                lines.append(f"    WARN  {w}")
        return "\n".join(lines)

    def __bool__(self) -> bool:
        return self.passed


# ── Primitive comparisons ─────────────────────────────────────────────────────

def titles_match(t1: str, t2: str, threshold: float = 0.85) -> bool:
    """
    Return True if two section titles are considered equivalent.
    Uses SequenceMatcher ratio; exact match always passes regardless of threshold.
    """
    if not t1 and not t2:
        return True
    if not t1 or not t2:
        return False
    a = t1.strip().lower()
    b = t2.strip().lower()
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def page_range_matches(
    actual: Dict[str, Any],
    golden: Dict[str, Any],
    tolerance: int = 1,
) -> bool:
    """
    Return True if start_index and end_index both differ by at most `tolerance`.
    Silently passes when either node is missing the keys (incomparable).
    """
    s_a = actual.get("start_index")
    e_a = actual.get("end_index")
    s_g = golden.get("start_index")
    e_g = golden.get("end_index")
    if any(v is None for v in (s_a, e_a, s_g, e_g)):
        return True
    return abs(s_a - s_g) <= tolerance and abs(e_a - e_g) <= tolerance


# ── Recursive node-list comparison ───────────────────────────────────────────

def _compare_node_lists(
    actual: List[Dict],
    golden: List[Dict],
    path: str,
    title_threshold: float,
    page_tolerance: int,
) -> Tuple[List[str], List[str]]:
    """
    Recursively compare two lists of tree nodes.
    Returns (mismatches, warnings).
    """
    mismatches: List[str] = []
    warnings:   List[str] = []

    # ── Node count check ──────────────────────────────────────────────────
    if len(actual) != len(golden):
        diff = abs(len(actual) - len(golden))
        msg = (
            f"{path}: node count {len(actual)} (actual) "
            f"vs {len(golden)} (golden)"
        )
        if diff <= 1:
            warnings.append(msg)
        else:
            mismatches.append(msg)

    # ── Per-node checks (zip stops at the shorter list) ───────────────────
    for i, (a_node, g_node) in enumerate(zip(actual, golden)):
        node_path = "{path}[{i}]({title})".format(
            path=path, i=i, title=g_node.get("title", "?")
        )

        # Title
        a_title = a_node.get("title", "")
        g_title = g_node.get("title", "")
        if not titles_match(a_title, g_title, title_threshold):
            mismatches.append(
                f"{node_path}: title mismatch — "
                f"got {a_title!r}, expected {g_title!r}"
            )

        # Page range
        if not page_range_matches(a_node, g_node, page_tolerance):
            mismatches.append(
                f"{node_path}: page range "
                f"[{a_node.get('start_index')}-{a_node.get('end_index')}] (actual) "
                f"vs [{g_node.get('start_index')}-{g_node.get('end_index')}] (golden)"
            )

        # Recurse into children
        a_children = a_node.get("nodes") or []
        g_children = g_node.get("nodes") or []
        if a_children or g_children:
            child_m, child_w = _compare_node_lists(
                a_children, g_children,
                f"{node_path}.nodes",
                title_threshold, page_tolerance,
            )
            mismatches.extend(child_m)
            warnings.extend(child_w)

    return mismatches, warnings


# ── Public API ────────────────────────────────────────────────────────────────

def compare_structures(
    actual: Dict[str, Any],
    golden: Dict[str, Any],
    title_threshold: float = 0.85,
    page_tolerance: int = 1,
) -> CompareResult:
    """
    Compare two PageIndex output dicts.

    Ignored fields: node_id, summary, prefix_summary, doc_description, text.
    Title comparison: fuzzy (SequenceMatcher ratio >= title_threshold).
    Page range comparison: absolute difference <= page_tolerance.
    """
    mismatches: List[str] = []
    warnings:   List[str] = []

    # doc_name — warn only (cosmetic difference)
    a_name = actual.get("doc_name", "")
    g_name = golden.get("doc_name", "")
    if a_name != g_name:
        warnings.append(f"doc_name: {a_name!r} (actual) vs {g_name!r} (golden)")

    # Structure list
    a_structure = actual.get("structure", [])
    g_structure = golden.get("structure", [])

    # Normalise: sometimes a single root dict is returned instead of a list
    if isinstance(a_structure, dict):
        a_structure = [a_structure]
    if isinstance(g_structure, dict):
        g_structure = [g_structure]

    node_m, node_w = _compare_node_lists(
        a_structure, g_structure,
        path="structure",
        title_threshold=title_threshold,
        page_tolerance=page_tolerance,
    )
    mismatches.extend(node_m)
    warnings.extend(node_w)

    return CompareResult(
        passed=len(mismatches) == 0,
        mismatches=mismatches,
        warnings=warnings,
    )


def compare_files(
    actual_path: str,
    golden_path: str,
    title_threshold: float = 0.85,
    page_tolerance: int = 1,
) -> CompareResult:
    """Load two JSON files from disk and compare their structures."""
    with open(actual_path, "r", encoding="utf-8") as f:
        actual = json.load(f)
    with open(golden_path, "r", encoding="utf-8") as f:
        golden = json.load(f)
    return compare_structures(actual, golden, title_threshold, page_tolerance)
