"""
main.py — FastAPI application for Doc Agent.

Serves REST endpoints for document management, RAG chat, provider configuration,
and conversation history. Uses Supabase for persistence and anonymous user sessions via cookies.
"""
import logging
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backend.routes import documents, chat, providers, conversations, collections

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(title="Doc Agent API", version="1.0.0")

# CORS — allow the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        os.environ.get("FRONTEND_URL", "http://localhost:3000"),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── App state ────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    # Supabase client (optional)
    sb = None
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if url and key:
        try:
            from supabase import create_client
            sb = create_client(url, key)
            logger.info("Supabase connected: %s", url)
        except Exception as e:
            logger.warning("Supabase connection failed: %s", e)

    app.state.supabase = sb
    # Server-side session store: {user_id: {provider_obj, provider_key, ...}}
    app.state.sessions = {}


# ── Anonymous user middleware ────────────────────────────────────────────────
# Cookie is set by Next.js middleware (same-origin). Backend only reads it.
_known_users: set = set()


@app.middleware("http")
async def user_session_middleware(request: Request, call_next):
    user_id = request.cookies.get("pageindex_user_id")

    if not user_id:
        # Fallback: generate one for direct backend access (e.g. health checks)
        user_id = str(uuid4())

    request.state.user_id = user_id

    # Create user in Supabase on first sight (idempotent)
    if user_id not in _known_users:
        sb = getattr(app.state, "supabase", None)
        if sb:
            try:
                sb.table("users").insert({
                    "id": user_id,
                    "email": f"anon-{user_id[:8]}@pageindex.local",
                    "display_name": f"Anonymous {user_id[:8]}",
                }).execute()
            except Exception:
                pass  # Already exists or DB error — fine either way
        _known_users.add(user_id)

    response: Response = await call_next(request)
    return response


# ── Routes ───────────────────────────────────────────────────────────────────
app.include_router(providers.router)
app.include_router(collections.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(conversations.router)


@app.get("/api/health")
async def health():
    sb = getattr(app.state, "supabase", None)
    return {
        "status": "ok",
        "supabase": "connected" if sb else "not configured",
    }
