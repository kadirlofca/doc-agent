#!/usr/bin/env python3
"""
admin_upload.py — Bulk-index PDFs into global Supabase collections.

Usage:
  python scripts/admin_upload.py \
    --collection curam_web_client \
    --pdf ./docs/guide.pdf \
    --provider gemini \
    --model gemini-2.0-flash-lite \
    --api-key $GEMINI_API_KEY

Environment:
  SUPABASE_URL         — Supabase project URL
  SUPABASE_SERVICE_KEY — Service role key (bypasses RLS)
"""
import argparse
import asyncio
import logging
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from storage.supabase_client import get_client
from pageindex.page_index import page_index_main
from pageindex.llm.factory import build_provider
from pageindex.utils import get_page_tokens

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("admin_upload")

ADMIN_USER_ID = "00000000-0000-0000-0000-000000000001"

# Provider defaults (same as backend PROVIDERS config)
PROVIDER_DEFAULTS = {
    "gemini": {
        "factory": "gemini",
        "chunk_budget": 16000,
        "concurrency": 4,
        "inter_call_delay": 0.3,
    },
    "groq": {
        "factory": "openai_compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "chunk_budget": 6000,
        "concurrency": 1,
        "inter_call_delay": 3.0,
    },
    "openai": {
        "factory": "openai",
        "chunk_budget": 20000,
        "concurrency": 8,
        "inter_call_delay": 0.1,
    },
    "anthropic": {
        "factory": "anthropic",
        "chunk_budget": 20000,
        "concurrency": 2,
        "inter_call_delay": 2.0,
    },
}


def create_provider(provider_key: str, model: str, api_key: str):
    """Create an LLM provider using the factory."""
    defaults = PROVIDER_DEFAULTS.get(provider_key)
    if not defaults:
        raise ValueError(f"Unknown provider: {provider_key}. Available: {list(PROVIDER_DEFAULTS)}")

    llm_config = SimpleNamespace(
        provider=defaults["factory"],
        model=model,
        api_key=api_key,
    )
    if "base_url" in defaults:
        llm_config.base_url = defaults["base_url"]

    cache_config = SimpleNamespace(enabled=False)
    retry_config = SimpleNamespace(
        max_attempts=3,
        base_delay_seconds=1.0,
        max_delay_seconds=30.0,
        backoff_factor=2.0,
    )
    pipeline_config = SimpleNamespace(
        concurrency=defaults["concurrency"],
        inter_call_delay=defaults["inter_call_delay"],
    )

    return build_provider(llm_config, cache_config, retry_config, pipeline_config)


def index_pdf(pdf_path: str, provider_obj, provider_defaults: dict) -> tuple:
    """Index a PDF and return (tree_json, pages_json, duration_ms)."""
    pdf_bytes = Path(pdf_path).read_bytes()

    logger.info("Extracting pages from %s...", pdf_path)
    page_list = get_page_tokens(BytesIO(pdf_bytes))
    if not page_list:
        raise RuntimeError(f"No pages found in {pdf_path}")

    total_tokens = sum(p[1] for p in page_list)
    logger.info("Found %d pages, %d tokens", len(page_list), total_tokens)

    opt = SimpleNamespace(
        provider=provider_obj,
        toc_check_page_num=20,
        max_page_num_each_node=10,
        max_token_num_each_node=provider_defaults["chunk_budget"],
        if_add_node_id="yes",
        if_add_node_text="no",
        if_add_node_summary="no",
        if_add_doc_description="no",
        pipeline=SimpleNamespace(
            timeout_seconds=3600,
            concurrency=provider_defaults["concurrency"],
            chunk_token_budget=provider_defaults["chunk_budget"],
            inter_call_delay=provider_defaults.get("inter_call_delay", 0.5),
        ),
    )

    start = time.time()
    logger.info("Indexing %s (this may take several minutes)...", pdf_path)
    tree_json = page_index_main(BytesIO(pdf_bytes), opt=opt)
    duration_ms = int((time.time() - start) * 1000)

    pages_json = [[p[0], p[1]] for p in page_list]
    logger.info("Indexing complete in %.1fs", duration_ms / 1000)

    return tree_json, pages_json, duration_ms, len(page_list), total_tokens


def upload_to_supabase(
    collection_id: str,
    pdf_name: str,
    tree_json,
    pages_json,
    duration_ms: int,
    page_count: int,
    total_tokens: int,
    provider_key: str,
    model: str,
) -> str:
    """Create a global document record in Supabase. Returns doc_id."""
    client = get_client()
    doc_id = str(uuid4())

    client.table("documents").insert({
        "id": doc_id,
        "user_id": ADMIN_USER_ID,
        "name": pdf_name,
        "file_size_bytes": 0,
        "page_count": page_count,
        "total_tokens": total_tokens,
        "status": "indexed",
        "provider_used": provider_key,
        "model_used": model,
        "tree_json": tree_json,
        "pages_json": pages_json,
        "indexing_duration_ms": duration_ms,
        "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collection_id": collection_id,
        "is_global": True,
    }).execute()

    logger.info("Saved document %s (%s) to collection '%s'", doc_id[:8], pdf_name, collection_id)
    return doc_id


def main():
    parser = argparse.ArgumentParser(description="Upload and index PDFs into global collections")
    parser.add_argument("--collection", required=True, help="Collection ID (e.g., curam_web_client)")
    parser.add_argument("--pdf", required=True, nargs="+", help="PDF file path(s)")
    parser.add_argument("--provider", default="gemini", help="LLM provider (default: gemini)")
    parser.add_argument("--model", default="gemini-2.0-flash-lite", help="Model name")
    parser.add_argument("--api-key", default=None, help="API key (or set env var)")
    args = parser.parse_args()

    # Resolve API key
    api_key = args.api_key
    if not api_key:
        env_map = {
            "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "openai": ["OPENAI_API_KEY"],
            "anthropic": ["ANTHROPIC_API_KEY"],
            "groq": ["GROQ_API_KEY"],
        }
        for env_var in env_map.get(args.provider, []):
            api_key = os.environ.get(env_var)
            if api_key:
                break

    if not api_key:
        logger.error("No API key provided. Use --api-key or set the appropriate env var.")
        sys.exit(1)

    # Verify Supabase connection
    try:
        client = get_client()
        logger.info("Supabase connected")
    except Exception as e:
        logger.error("Supabase connection failed: %s", e)
        sys.exit(1)

    # Create provider
    provider_obj = create_provider(args.provider, args.model, api_key)
    defaults = PROVIDER_DEFAULTS[args.provider]
    logger.info("Using %s / %s", args.provider, args.model)

    # Process each PDF
    for pdf_path in args.pdf:
        if not Path(pdf_path).exists():
            logger.error("File not found: %s", pdf_path)
            continue

        pdf_name = Path(pdf_path).name

        try:
            tree_json, pages_json, duration_ms, page_count, total_tokens = index_pdf(
                pdf_path, provider_obj, defaults
            )

            doc_id = upload_to_supabase(
                collection_id=args.collection,
                pdf_name=pdf_name,
                tree_json=tree_json,
                pages_json=pages_json,
                duration_ms=duration_ms,
                page_count=page_count,
                total_tokens=total_tokens,
                provider_key=args.provider,
                model=args.model,
            )

            logger.info("SUCCESS: %s → doc_id=%s (collection=%s)", pdf_name, doc_id, args.collection)

        except Exception as e:
            logger.error("FAILED: %s → %s", pdf_name, e)
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
