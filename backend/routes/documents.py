"""
documents.py — Document upload, listing, loading, deletion, and indexing progress SSE.
"""
import asyncio
import json
import time
from typing import List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from sse_starlette.sse import EventSourceResponse

from backend.services.indexing import (
    run_indexing, get_progress, get_job_queue, get_all_active_jobs,
)
from backend.routes.providers import PROVIDERS, friendly_error

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
async def list_documents(request: Request):
    """List all documents for the current user."""
    sb = request.app.state.supabase
    if not sb:
        return []
    try:
        result = (
            sb.table("documents")
            .select("id, name, page_count, total_tokens, status, provider_used, "
                    "model_used, indexing_duration_ms, created_at, indexed_at, error_message")
            .order("created_at", desc=True)
            .execute()
        )
        return result.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load documents: {e}")


@router.get("/indexing-progress/{doc_id}")
async def indexing_progress(doc_id: str):
    """SSE endpoint streaming indexing progress for a specific document."""
    async def event_stream():
        q = get_job_queue(doc_id)
        if not q:
            yield {"event": "error", "data": json.dumps({"error": "No active indexing job for this document"})}
            return

        log_lines = []
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield {"event": "heartbeat", "data": "ping"}
                continue

            kind = msg[0]
            if kind == "log":
                log_lines.append(msg[1])
                pct, label = get_progress(log_lines)
                yield {
                    "event": "progress",
                    "data": json.dumps({
                        "percentage": pct,
                        "step": label,
                        "log": msg[1],
                    }),
                }
            elif kind == "done":
                yield {
                    "event": "done",
                    "data": json.dumps({"status": "indexed"}),
                }
                return
            elif kind == "error":
                yield {
                    "event": "error",
                    "data": json.dumps({"error": msg[1]}),
                }
                return

    return EventSourceResponse(event_stream())


@router.get("/{doc_id}")
async def get_document(doc_id: str, request: Request):
    """Load tree_json and pages_json for a document."""
    sb = request.app.state.supabase
    if not sb:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Check in-memory cache first
    sessions = request.app.state.sessions
    user_id = request.state.user_id
    user_session = sessions.get(user_id, {})
    loaded_docs = user_session.get("loaded_docs", {})

    if doc_id in loaded_docs:
        return loaded_docs[doc_id]

    try:
        result = (
            sb.table("documents")
            .select("name, tree_json, pages_json")
            .eq("id", doc_id)
            .eq("status", "indexed")
            .single()
            .execute()
        )
        if result.data and result.data.get("tree_json"):
            doc_data = {
                "tree": result.data["tree_json"],
                "pages": result.data["pages_json"],
                "name": result.data["name"],
            }
            # Cache in session
            sessions.setdefault(user_id, {})
            sessions[user_id].setdefault("loaded_docs", {})[doc_id] = doc_data
            return doc_data
        raise HTTPException(status_code=404, detail="Document not found or not indexed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load document: {e}")


@router.post("/upload")
async def upload_documents(
    request: Request,
    files: List[UploadFile] = File(...),
):
    """Upload one or more PDFs, create Supabase records, start background indexing."""
    sb = request.app.state.supabase
    user_id = request.state.user_id
    sessions = request.app.state.sessions
    user_session = sessions.get(user_id, {})

    provider_obj = user_session.get("provider_obj")
    if not provider_obj:
        raise HTTPException(status_code=400, detail="No provider configured. Connect a provider first.")

    provider_key = user_session.get("provider_key", "gemini")
    provider_cfg = PROVIDERS.get(provider_key, PROVIDERS["gemini"])

    doc_ids = []
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"Only PDF files are accepted: {file.filename}")

        pdf_bytes = await file.read()
        doc_id = str(uuid4())

        # Create Supabase record
        if sb:
            try:
                sb.table("documents").insert({
                    "id": doc_id,
                    "user_id": user_id,
                    "name": file.filename,
                    "file_size_bytes": len(pdf_bytes),
                    "status": "uploaded",
                    "provider_used": provider_key,
                    "model_used": user_session.get("provider_model", ""),
                }).execute()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to create document record: {e}")

        # Start background indexing
        asyncio.create_task(
            run_indexing(pdf_bytes, provider_obj, provider_cfg, doc_id, sb)
        )
        doc_ids.append({"doc_id": doc_id, "name": file.filename})

    return {"documents": doc_ids}


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, request: Request):
    """Delete a document from Supabase."""
    sb = request.app.state.supabase
    if not sb:
        raise HTTPException(status_code=500, detail="Database not configured")

    try:
        sb.table("documents").delete().eq("id", doc_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}")

    # Remove from session cache
    sessions = request.app.state.sessions
    user_id = request.state.user_id
    user_session = sessions.get(user_id, {})
    user_session.get("loaded_docs", {}).pop(doc_id, None)

    return {"status": "deleted"}
