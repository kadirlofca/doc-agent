"""
indexing.py — Background PDF indexing with SSE progress streaming.
"""
import asyncio
import logging
import time
from io import BytesIO
from types import SimpleNamespace
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Maps pipeline log keywords to (progress_pct, user_friendly_step_label)
_PROGRESS_STEPS = [
    ("Extracting pages",          5,  "Extracting pages from PDF..."),
    ("Found",                    10,  "Pages extracted"),
    ("Parsing PDF",              12,  "Parsing PDF structure..."),
    ("start find_toc_pages",     15,  "Scanning for table of contents..."),
    ("toc found",                20,  "Table of contents found"),
    ("no toc found",             20,  "No TOC found - generating structure..."),
    ("start detect_page_index",  25,  "Detecting page numbering..."),
    ("index found",              30,  "Page index detected"),
    ("index not found",          30,  "Building page index..."),
    ("meta_processor mode",      35,  "Processing document metadata..."),
    ("start toc_transformer",    40,  "Transforming table of contents..."),
    ("start toc_index_extractor",45,  "Extracting section indices..."),
    ("Processing group",         50,  "Building document tree..."),
    ("TOC generation complete",  60,  "Document tree generated"),
    ("add_page_number_to_toc",   65,  "Mapping pages to sections..."),
    ("start verify_toc",         70,  "Verifying tree accuracy..."),
    ("accuracy",                 75,  "Verification complete"),
    ("start fix_incorrect_toc",  78,  "Fixing incorrect mappings..."),
    ("divided page_list",        80,  "Processing page groups..."),
    ("large node",               85,  "Splitting large sections..."),
    ("Saved to database",        95,  "Saving to database..."),
    ("Indexing complete",       100,  "Indexing complete!"),
]


def get_progress(log_lines: list) -> tuple:
    """Scan log lines and return (progress_pct, step_label)."""
    pct, label = 0, "Starting..."
    for line in log_lines:
        line_lower = line.lower()
        for keyword, step_pct, step_label in _PROGRESS_STEPS:
            if keyword.lower() in line_lower:
                if step_pct > pct:
                    pct = step_pct
                    label = step_label
    return pct, label


class _AsyncQueueHandler(logging.Handler):
    """Logging handler that pushes formatted records into an asyncio.Queue."""
    _SUPPRESSED = frozenset({"httpx", "httpcore", "urllib3", "openai._base_client"})

    def __init__(self, q: asyncio.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            if any(record.name.startswith(p) for p in self._SUPPRESSED):
                return
            self.q.put_nowait(("log", self.format(record)))
        except Exception:
            pass


# In-memory store of active indexing jobs: {doc_id: asyncio.Queue}
_active_jobs: Dict[str, asyncio.Queue] = {}


def get_job_queue(doc_id: str) -> Optional[asyncio.Queue]:
    return _active_jobs.get(doc_id)


def get_all_active_jobs() -> Dict[str, asyncio.Queue]:
    return dict(_active_jobs)


async def run_indexing(
    pdf_bytes: bytes,
    provider_obj: Any,
    provider_cfg: dict,
    doc_id: str,
    sb: Any,
) -> None:
    """Run indexing in a background task. Progress is pushed to an asyncio.Queue."""
    q: asyncio.Queue = asyncio.Queue()
    _active_jobs[doc_id] = q

    handler = _AsyncQueueHandler(q)
    handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))
    root_pi = logging.getLogger("pageindex")
    root_pi.addHandler(handler)
    root_pi.setLevel(logging.INFO)

    start_time = time.time()

    try:
        from pageindex.page_index import tree_parser
        from pageindex.utils import get_page_tokens, write_node_id, get_pdf_name, JsonLogger

        await q.put(("log", "Extracting pages from PDF..."))
        page_list = await asyncio.to_thread(get_page_tokens, BytesIO(pdf_bytes))

        if not page_list:
            await q.put(("error", "No pages found in PDF - is it a scanned/image PDF?"))
            if sb:
                sb.table("documents").update({
                    "status": "failed",
                    "error_message": "No pages found",
                }).eq("id", doc_id).execute()
            return

        total_tokens = sum(p[1] for p in page_list)
        await q.put(("log", f"Found {len(page_list)} pages - {total_tokens:,} tokens total"))
        await q.put(("log", "Building document tree - this can take several minutes..."))

        if sb:
            sb.table("documents").update({
                "status": "indexing",
                "page_count": len(page_list),
                "total_tokens": total_tokens,
            }).eq("id", doc_id).execute()

        opt = SimpleNamespace(
            provider=provider_obj,
            toc_check_page_num=20,
            max_page_num_each_node=10,
            max_token_num_each_node=provider_cfg["chunk_budget"],
            if_add_node_id="yes",
            if_add_node_text="no",
            if_add_node_summary="no",
            if_add_doc_description="no",
            pipeline=SimpleNamespace(
                timeout_seconds=3600,
                concurrency=provider_cfg["concurrency"],
                chunk_token_budget=provider_cfg["chunk_budget"],
                inter_call_delay=provider_cfg.get("inter_call_delay", 0.5),
            ),
        )

        # Call the async tree_parser directly instead of page_index_main
        # (which uses asyncio.run() internally, causing event loop conflicts)
        pi_logger = JsonLogger(BytesIO(pdf_bytes))
        structure = await tree_parser(page_list, opt, doc=BytesIO(pdf_bytes), logger=pi_logger)
        write_node_id(structure)
        result = {
            'doc_name': get_pdf_name(BytesIO(pdf_bytes)),
            'structure': structure,
        }
        duration_ms = int((time.time() - start_time) * 1000)

        if sb:
            try:
                pages_data = [[p[0], p[1]] for p in page_list]
                sb.table("documents").update({
                    "status": "indexed",
                    "tree_json": result,
                    "pages_json": pages_data,
                    "indexing_duration_ms": duration_ms,
                    "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }).eq("id", doc_id).execute()
                await q.put(("log", f"Saved to database ({duration_ms / 1000:.1f}s)"))
            except Exception as e:
                await q.put(("log", f"Database save failed: {e}"))

        await q.put(("log", "Indexing complete!"))
        await q.put(("done", result, page_list))

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        await q.put(("log", f"Error: {exc}"))
        await q.put(("log", tb))
        await q.put(("error", str(exc)))
        if sb:
            try:
                sb.table("documents").update({
                    "status": "failed",
                    "error_message": str(exc)[:2000],
                }).eq("id", doc_id).execute()
            except Exception:
                pass
    finally:
        root_pi.removeHandler(handler)
        _active_jobs.pop(doc_id, None)
