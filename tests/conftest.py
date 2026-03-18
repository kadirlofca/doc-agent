"""
Pytest configuration and shared fixtures for all phases.

sys.path is configured here so every test file can use:
    from compare import ...             (tests/compare.py)
    from pageindex import ...           (project root)
"""
import os
import sys
from pathlib import Path

# ── sys.path setup (must happen before any project imports) ──────────────────
_ROOT = Path(__file__).parent.parent          # .../doc-agent/
_TESTS = Path(__file__).parent                # .../doc-agent/tests/

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

# Load .env so CHATGPT_API_KEY is available before any module-level os.getenv()
from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

import pytest

# ── Directory constants ───────────────────────────────────────────────────────
PDFS_DIR   = _TESTS / "pdfs"
GOLDEN_DIR = _TESTS / "results"


# ── Marker registration ───────────────────────────────────────────────────────
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (requires live LLM API calls — "
        "deselect with: pytest -m 'not slow')",
    )
    config.addinivalue_line(
        "markers",
        "requires_api: marks tests that need a valid CHATGPT_API_KEY env var",
    )


# ── Path fixtures ─────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def pdfs_dir():
    return PDFS_DIR


@pytest.fixture(scope="session")
def golden_dir():
    return GOLDEN_DIR


# ── Test PDF fixtures: three tiers ────────────────────────────────────────────
@pytest.fixture(scope="session")
def fast_pdf():
    """~100 KB, ~10 pages — primary regression fixture, runs in ~30 s."""
    return PDFS_DIR / "q1-fy25-earnings.pdf"


@pytest.fixture(scope="session")
def fast_golden():
    return GOLDEN_DIR / "q1-fy25-earnings_structure.json"


@pytest.fixture(scope="session")
def medium_pdf():
    """~1.4 MB — secondary regression fixture, runs in ~2 min."""
    return PDFS_DIR / "2023-annual-report-truncated.pdf"


@pytest.fixture(scope="session")
def medium_golden():
    return GOLDEN_DIR / "2023-annual-report-truncated_structure.json"


@pytest.fixture(scope="session")
def large_pdf():
    """18 MB, PRML textbook — manual / CI nightly only."""
    return PDFS_DIR / "PRML.pdf"


@pytest.fixture(scope="session")
def large_golden():
    return GOLDEN_DIR / "PRML_structure.json"


# ── API key fixture (skips test if key is absent) ────────────────────────────
@pytest.fixture(scope="session")
def openai_api_key():
    """
    Returns the OpenAI API key from the environment.
    Skips the requesting test with a clear message if it is not set.
    """
    key = os.getenv("CHATGPT_API_KEY")
    if not key:
        pytest.skip(
            "CHATGPT_API_KEY not set — skipping live API test. "
            "Add it to .env or export it before running with -m slow."
        )
    return key
