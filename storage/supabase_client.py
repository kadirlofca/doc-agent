"""
supabase_client.py — Supabase integration for PageIndex.

Handles all database operations, file storage, and auth verification.
Uses the Supabase Python SDK (supabase-py).

Environment variables required:
    SUPABASE_URL        — Project URL (https://xxxxx.supabase.co)
    SUPABASE_ANON_KEY   — Public anon key (for client-side auth)
    SUPABASE_SERVICE_KEY — Service role key (for server-side operations)
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from supabase import create_client, Client

logger = logging.getLogger(__name__)


def get_client() -> Client:
    """Create and return a Supabase client using environment variables."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_ANON_KEY) "
            "must be set in environment variables."
        )
    return create_client(url, key)


# ── Document Operations ──────────────────────────────────────────────────────

def create_document(
    client: Client,
    user_id: str,
    name: str,
    file_size_bytes: int,
) -> Dict[str, Any]:
    """Create a document record with status='uploaded'. Returns the row."""
    doc_id = str(uuid4())
    row = {
        "id": doc_id,
        "user_id": user_id,
        "name": name,
        "file_size_bytes": file_size_bytes,
        "status": "uploaded",
    }
    result = client.table("documents").insert(row).execute()
    logger.info("Created document %s for user %s", doc_id[:8], user_id[:8])
    return result.data[0]


def update_document_indexing(
    client: Client,
    doc_id: str,
    page_count: int,
    total_tokens: int,
    provider_used: str,
    model_used: str,
) -> None:
    """Mark document as 'indexing' with page/token counts."""
    client.table("documents").update({
        "status": "indexing",
        "page_count": page_count,
        "total_tokens": total_tokens,
        "provider_used": provider_used,
        "model_used": model_used,
    }).eq("id", doc_id).execute()


def save_indexed_document(
    client: Client,
    doc_id: str,
    tree_json: Any,
    pages_json: Any,
    duration_ms: int,
) -> None:
    """Save the indexed tree and page list, mark as 'indexed'."""
    client.table("documents").update({
        "status": "indexed",
        "tree_json": tree_json,
        "pages_json": pages_json,
        "indexing_duration_ms": duration_ms,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", doc_id).execute()
    logger.info("Saved indexed tree for document %s (%dms)", doc_id[:8], duration_ms)


def mark_document_failed(client: Client, doc_id: str, error: str) -> None:
    """Mark document as 'failed' with error message."""
    client.table("documents").update({
        "status": "failed",
        "error_message": error[:2000],
    }).eq("id", doc_id).execute()


def get_user_documents(client: Client, user_id: str) -> List[Dict]:
    """Get all documents for a user, ordered by creation date."""
    result = (
        client.table("documents")
        .select("id, name, page_count, total_tokens, status, provider_used, "
                "model_used, indexing_duration_ms, created_at, indexed_at, error_message")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


def get_document_tree(client: Client, doc_id: str) -> Optional[Dict]:
    """Load the indexed tree JSON for a document."""
    result = (
        client.table("documents")
        .select("tree_json, pages_json")
        .eq("id", doc_id)
        .eq("status", "indexed")
        .single()
        .execute()
    )
    return result.data if result.data else None


def delete_document(client: Client, doc_id: str, user_id: str) -> None:
    """Delete a document and its PDF from storage."""
    # Get storage path first
    result = (
        client.table("documents")
        .select("pdf_storage_path")
        .eq("id", doc_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if result.data and result.data.get("pdf_storage_path"):
        try:
            client.storage.from_("pdfs").remove([result.data["pdf_storage_path"]])
        except Exception as e:
            logger.warning("Failed to delete PDF from storage: %s", e)

    client.table("documents").delete().eq("id", doc_id).eq("user_id", user_id).execute()
    logger.info("Deleted document %s", doc_id[:8])


# ── PDF Storage Operations ───────────────────────────────────────────────────

def upload_pdf(client: Client, user_id: str, doc_id: str, pdf_bytes: bytes, filename: str) -> str:
    """Upload PDF to Supabase Storage. Returns the storage path."""
    # Sanitize filename
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-")
    path = f"{user_id}/{doc_id}_{safe_name}"

    client.storage.from_("pdfs").upload(
        path=path,
        file=pdf_bytes,
        file_options={"content-type": "application/pdf"},
    )

    # Update document record with storage path
    client.table("documents").update({
        "pdf_storage_path": path,
    }).eq("id", doc_id).execute()

    logger.info("Uploaded PDF %s (%d bytes)", path, len(pdf_bytes))
    return path


# ── Conversation Operations ──────────────────────────────────────────────────

def create_conversation(
    client: Client,
    user_id: str,
    title: str = "New conversation",
    doc_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new conversation linked to documents."""
    row = {
        "id": str(uuid4()),
        "user_id": user_id,
        "title": title,
        "doc_ids": doc_ids or [],
    }
    result = client.table("conversations").insert(row).execute()
    return result.data[0]


def get_user_conversations(client: Client, user_id: str) -> List[Dict]:
    """Get all conversations for a user, most recent first."""
    result = (
        client.table("conversations")
        .select("id, title, doc_ids, message_count, created_at, last_message_at")
        .eq("user_id", user_id)
        .order("last_message_at", desc=True)
        .execute()
    )
    return result.data


def update_conversation_docs(client: Client, conv_id: str, doc_ids: List[str]) -> None:
    """Update which documents are linked to a conversation."""
    client.table("conversations").update({
        "doc_ids": doc_ids,
    }).eq("id", conv_id).execute()


def delete_conversation(client: Client, conv_id: str, user_id: str) -> None:
    """Delete a conversation and all its messages."""
    client.table("conversations").delete().eq("id", conv_id).eq("user_id", user_id).execute()


# ── Message Operations ───────────────────────────────────────────────────────

def save_message(
    client: Client,
    conversation_id: str,
    role: str,
    content: str,
    sources: Optional[List[Dict]] = None,
    model_used: Optional[str] = None,
    latency_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Save a chat message. Sources format: [{"doc_id": "...", "node_id": "1.2", "title": "..."}]"""
    row = {
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "sources": sources or [],
    }
    if model_used:
        row["model_used"] = model_used
    if latency_ms is not None:
        row["latency_ms"] = latency_ms

    result = client.table("messages").insert(row).execute()
    return result.data[0]


def get_conversation_messages(
    client: Client,
    conversation_id: str,
    limit: int = 50,
) -> List[Dict]:
    """Get messages for a conversation, ordered by time."""
    result = (
        client.table("messages")
        .select("id, role, content, sources, model_used, latency_ms, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data


def get_recent_messages(client: Client, conversation_id: str, limit: int = 10) -> List[Dict]:
    """Get the most recent N messages (for chat context injection)."""
    result = (
        client.table("messages")
        .select("role, content")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    # Reverse so oldest is first (chronological order)
    return list(reversed(result.data))


# ── Prompt Cache Operations ──────────────────────────────────────────────────

def cache_get(client: Client, hash_key: str) -> Optional[Dict]:
    """Get a cached LLM response by SHA-256 hash. Returns None if expired/missing."""
    try:
        result = (
            client.table("prompt_cache")
            .select("response, expires_at")
            .eq("hash", hash_key)
            .single()
            .execute()
        )
        if not result.data:
            return None

        # Check expiry
        expires_at = datetime.fromisoformat(result.data["expires_at"].replace("Z", "+00:00"))
        if expires_at < datetime.now(timezone.utc):
            return None

        # Increment hit count (fire-and-forget)
        client.table("prompt_cache").update({
            "hit_count": result.data.get("hit_count", 0) + 1,
        }).eq("hash", hash_key).execute()

        return result.data["response"]
    except Exception:
        return None


def cache_put(client: Client, hash_key: str, model: str, response: Dict, ttl_seconds: int = 86400) -> None:
    """Store an LLM response in the shared cache."""
    try:
        expires_at = datetime.fromtimestamp(
            time.time() + ttl_seconds, tz=timezone.utc
        ).isoformat()

        client.table("prompt_cache").upsert({
            "hash": hash_key,
            "model": model,
            "response": response,
            "expires_at": expires_at,
            "hit_count": 0,
        }).execute()
    except Exception as e:
        logger.warning("Failed to write prompt cache: %s", e)


# ── User API Key Operations ──────────────────────────────────────────────────
# SECURITY NOTE: API keys are kept in server-side sessions only (in-memory).
# They are NOT persisted to the database. The functions below are intentionally
# removed to prevent plaintext key storage. If persistence is needed in the
# future, add application-level encryption with a server-only master key.
