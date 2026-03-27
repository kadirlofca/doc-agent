-- ============================================================================
-- Migration: Add Document Collections
-- Adds collections table, collection_id/is_global to documents, updates RLS.
-- Run in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ============================================================================

-- 1. Seed admin user (needed as FK owner for global documents)
-- ============================================================================
INSERT INTO public.users (id, email, display_name)
VALUES ('00000000-0000-0000-0000-000000000001', 'admin@pageindex.local', 'System Admin')
ON CONFLICT (id) DO NOTHING;


-- 2. Collections table
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.collections (
    id          TEXT PRIMARY KEY,              -- slug: 'curam_web_client', etc.
    name        TEXT NOT NULL,                 -- display name
    description TEXT,
    icon        TEXT DEFAULT '📁',
    is_global   BOOLEAN DEFAULT FALSE,         -- true = shared across all users
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.collections ENABLE ROW LEVEL SECURITY;

-- Everyone can read collections
CREATE POLICY collections_select ON public.collections
    FOR SELECT USING (true);


-- 3. Add collection columns to documents
-- ============================================================================
ALTER TABLE public.documents
    ADD COLUMN IF NOT EXISTS collection_id TEXT REFERENCES public.collections(id),
    ADD COLUMN IF NOT EXISTS is_global BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_documents_collection ON public.documents(collection_id);
CREATE INDEX IF NOT EXISTS idx_documents_global ON public.documents(is_global) WHERE is_global = TRUE;


-- 4. Update RLS on documents — allow reading global docs
-- ============================================================================
DROP POLICY IF EXISTS docs_select ON public.documents;
CREATE POLICY docs_select ON public.documents
    FOR SELECT USING (is_global = TRUE OR user_id = auth.uid());


-- 5. Seed the three default collections
-- ============================================================================
INSERT INTO public.collections (id, name, description, icon, is_global) VALUES
    ('curam_web_client', 'Curam Web Client', 'Pre-indexed Curam Web Client documentation', '🖥️', TRUE),
    ('curam_web_server', 'Curam Web Server', 'Pre-indexed Curam Web Server documentation', '🗄️', TRUE),
    ('user_uploads',     'My Documents',     'Upload and query your own documents',        '📄', FALSE)
ON CONFLICT (id) DO NOTHING;


-- 6. Backfill existing documents into user_uploads
-- ============================================================================
UPDATE public.documents
SET collection_id = 'user_uploads', is_global = FALSE
WHERE collection_id IS NULL;
