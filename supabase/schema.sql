-- ============================================================================
-- PageIndex — Supabase Database Schema
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ============================================================================

-- 1. USERS TABLE
-- Extends Supabase Auth (auth.users) with app-specific preferences
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.users (
    id              UUID PRIMARY KEY,
    email           TEXT,
    display_name    TEXT,
    default_provider TEXT DEFAULT 'gemini',
    default_model   TEXT DEFAULT 'gemini-2.0-flash-lite',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-create user profile when they sign up via Supabase Auth
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.users (id, email, display_name)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.email)
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger: fires on every new auth.users insert
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- 2. DOCUMENTS TABLE
-- Stores metadata + indexed tree JSON for each uploaded PDF
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,                      -- original filename
    file_size_bytes BIGINT,                             -- PDF size
    page_count      INT,                                -- number of pages
    total_tokens    INT,                                -- total tokens across all pages
    status          TEXT DEFAULT 'uploaded'              -- uploaded | indexing | indexed | failed
                    CHECK (status IN ('uploaded', 'indexing', 'indexed', 'failed')),
    error_message   TEXT,                               -- error details if status='failed'
    provider_used   TEXT,                               -- which LLM provider indexed this
    model_used      TEXT,                               -- which model
    tree_json       JSONB,                              -- full indexed tree (1-5MB)
    pages_json      JSONB,                              -- page_list: [[text, tokens], ...]
    pdf_storage_path TEXT,                              -- path in Supabase Storage bucket
    indexing_duration_ms INT,                           -- how long indexing took
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    indexed_at      TIMESTAMPTZ
);

-- Index for fast user document lookups
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON public.documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON public.documents(status);


-- 3. CONVERSATIONS TABLE
-- Each conversation can reference multiple documents
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title           TEXT DEFAULT 'New conversation',
    doc_ids         UUID[] DEFAULT '{}',                -- array of document IDs linked
    message_count   INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_message_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON public.conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_last_msg ON public.conversations(last_message_at DESC);


-- 4. MESSAGES TABLE
-- Chat messages with source attribution
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.messages (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id   UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    role              TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content           TEXT NOT NULL,
    sources           JSONB DEFAULT '[]',               -- [{"doc_id": "...", "node_id": "1.2", "title": "..."}]
    token_count       INT,                              -- tokens in this message
    model_used        TEXT,                              -- which model generated this (for assistant msgs)
    latency_ms        INT,                              -- response generation time
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON public.messages(conversation_id, created_at);


-- 5. PROMPT CACHE TABLE
-- Shared LLM response cache (deduplicates across users)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.prompt_cache (
    hash            TEXT PRIMARY KEY,                    -- SHA-256 of (model + messages + temp)
    model           TEXT NOT NULL,
    response        JSONB NOT NULL,                      -- {content, finish_reason, input_tokens, output_tokens}
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,                -- created_at + TTL
    hit_count       INT DEFAULT 0                        -- track how often this cache entry is used
);

-- Auto-delete expired cache entries (run via pg_cron or app-level cleanup)
CREATE INDEX IF NOT EXISTS idx_prompt_cache_expires ON public.prompt_cache(expires_at);


-- 6. API KEYS TABLE (encrypted user-provided keys)
-- Users store their own API keys, encrypted at rest by Supabase
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.user_api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,                       -- anthropic, gemini, groq, etc.
    encrypted_key   TEXT NOT NULL,                       -- we encrypt before storing
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, provider)                            -- one key per provider per user
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user ON public.user_api_keys(user_id);


-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- Users can ONLY access their own data
-- ============================================================================

-- Enable RLS on all tables
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_api_keys ENABLE ROW LEVEL SECURITY;
-- prompt_cache is shared (no RLS needed — all users benefit from cache)

-- USERS: can only read/update their own profile
CREATE POLICY users_select ON public.users FOR SELECT USING (auth.uid() = id);
CREATE POLICY users_update ON public.users FOR UPDATE USING (auth.uid() = id);

-- DOCUMENTS: users see only their own documents
CREATE POLICY docs_select ON public.documents FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY docs_insert ON public.documents FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY docs_update ON public.documents FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY docs_delete ON public.documents FOR DELETE USING (auth.uid() = user_id);

-- CONVERSATIONS: users see only their own conversations
CREATE POLICY convos_select ON public.conversations FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY convos_insert ON public.conversations FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY convos_update ON public.conversations FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY convos_delete ON public.conversations FOR DELETE USING (auth.uid() = user_id);

-- MESSAGES: users see messages in their own conversations only
CREATE POLICY msgs_select ON public.messages FOR SELECT
    USING (conversation_id IN (SELECT id FROM public.conversations WHERE user_id = auth.uid()));
CREATE POLICY msgs_insert ON public.messages FOR INSERT
    WITH CHECK (conversation_id IN (SELECT id FROM public.conversations WHERE user_id = auth.uid()));

-- API KEYS: users see only their own keys
CREATE POLICY keys_select ON public.user_api_keys FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY keys_insert ON public.user_api_keys FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY keys_update ON public.user_api_keys FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY keys_delete ON public.user_api_keys FOR DELETE USING (auth.uid() = user_id);

-- PROMPT CACHE: everyone can read/write (shared cache benefits all users)
ALTER TABLE public.prompt_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY cache_select ON public.prompt_cache FOR SELECT USING (true);
CREATE POLICY cache_insert ON public.prompt_cache FOR INSERT WITH CHECK (true);
CREATE POLICY cache_update ON public.prompt_cache FOR UPDATE USING (true);


-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Auto-increment message_count on conversations
CREATE OR REPLACE FUNCTION public.increment_message_count()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE public.conversations
    SET message_count = message_count + 1,
        last_message_at = NOW()
    WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER messages_count_increment
    AFTER INSERT ON public.messages
    FOR EACH ROW EXECUTE FUNCTION public.increment_message_count();

-- Cleanup expired cache entries (call periodically)
CREATE OR REPLACE FUNCTION public.cleanup_expired_cache()
RETURNS INT AS $$
DECLARE
    deleted_count INT;
BEGIN
    DELETE FROM public.prompt_cache WHERE expires_at < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
