"""
conversations.py — Conversation CRUD endpoints.
"""
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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
    try:
        result = (
            sb.table("conversations")
            .select("id, title, doc_ids, message_count, created_at, last_message_at")
            .order("last_message_at", desc=True)
            .limit(20)
            .execute()
        )
        return result.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load conversations: {e}")


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
        raise HTTPException(status_code=500, detail=f"Failed to create conversation: {e}")


@router.get("/{conv_id}/messages")
async def get_conversation_messages(conv_id: str, request: Request):
    """Get all messages for a conversation."""
    sb = request.app.state.supabase
    if not sb:
        return []
    try:
        result = (
            sb.table("messages")
            .select("id, role, content, sources, model_used, latency_ms, created_at")
            .eq("conversation_id", conv_id)
            .order("created_at", desc=False)
            .limit(50)
            .execute()
        )
        return result.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load messages: {e}")


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, request: Request):
    """Delete a conversation and its messages."""
    sb = request.app.state.supabase
    if not sb:
        return {"status": "deleted"}
    try:
        sb.table("conversations").delete().eq("id", conv_id).execute()
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {e}")
