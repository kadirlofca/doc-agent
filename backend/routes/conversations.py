"""
conversations.py — Conversation CRUD endpoints.
"""
import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    title: str = "New conversation"
    doc_ids: list = []


@router.get("")
async def list_conversations(request: Request):
    """List all conversations for the current user."""
    sb = request.app.state.supabase
    if not sb:
        return []
    user_id = request.state.user_id

    try:
        result = (
            sb.table("conversations")
            .select("id, title, doc_ids, message_count, created_at, last_message_at")
            .eq("user_id", user_id)
            .order("last_message_at", desc=True)
            .limit(20)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.exception("Failed to load conversations for user %s", user_id[:8])
        raise HTTPException(status_code=500, detail="Failed to load conversations")


@router.post("")
async def create_conversation(body: CreateConversationRequest, request: Request):
    """Create a new conversation."""
    sb = request.app.state.supabase
    user_id = request.state.user_id
    if not sb:
        conv_id = str(uuid4())
        return {"id": conv_id, "title": body.title, "doc_ids": body.doc_ids}

    try:
        conv_id = str(uuid4())
        sb.table("conversations").insert({
            "id": conv_id,
            "user_id": user_id,
            "title": body.title,
            "doc_ids": body.doc_ids,
        }).execute()
        return {"id": conv_id, "title": body.title, "doc_ids": body.doc_ids}
    except Exception as e:
        logger.exception("Failed to create conversation for user %s", user_id[:8])
        raise HTTPException(status_code=500, detail="Failed to create conversation")


@router.get("/{conv_id}/messages")
async def get_conversation_messages(conv_id: str, request: Request):
    """Get all messages for a conversation owned by the current user."""
    sb = request.app.state.supabase
    if not sb:
        return []

    user_id = request.state.user_id

    try:
        # Verify conversation belongs to this user
        owner_check = (
            sb.table("conversations")
            .select("id")
            .eq("id", conv_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not owner_check.data:
            raise HTTPException(status_code=404, detail="Conversation not found")

        result = (
            sb.table("messages")
            .select("id, role, content, sources, model_used, latency_ms, created_at")
            .eq("conversation_id", conv_id)
            .order("created_at", desc=False)
            .limit(50)
            .execute()
        )
        return result.data
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to load messages for conversation %s", conv_id[:8])
        raise HTTPException(status_code=500, detail="Failed to load messages")


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, request: Request):
    """Delete a conversation and its messages (owner only)."""
    sb = request.app.state.supabase
    if not sb:
        return {"status": "deleted"}

    user_id = request.state.user_id

    try:
        # Only delete if owned by current user
        sb.table("conversations").delete().eq("id", conv_id).eq("user_id", user_id).execute()
        return {"status": "deleted"}
    except Exception as e:
        logger.exception("Failed to delete conversation %s", conv_id[:8])
        raise HTTPException(status_code=500, detail="Failed to delete conversation")
