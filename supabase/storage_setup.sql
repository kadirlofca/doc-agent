-- ============================================================================
-- Supabase Storage — Bucket & Policies
-- Run this AFTER schema.sql in SQL Editor
-- ============================================================================

-- Create bucket for PDF files
INSERT INTO storage.buckets (id, name, public)
VALUES ('pdfs', 'pdfs', false)
ON CONFLICT (id) DO NOTHING;

-- Users can upload PDFs to their own folder: pdfs/{user_id}/filename.pdf
CREATE POLICY "Users upload own PDFs"
ON storage.objects FOR INSERT
WITH CHECK (
    bucket_id = 'pdfs'
    AND auth.uid()::text = (storage.foldername(name))[1]
);

-- Users can read their own PDFs
CREATE POLICY "Users read own PDFs"
ON storage.objects FOR SELECT
USING (
    bucket_id = 'pdfs'
    AND auth.uid()::text = (storage.foldername(name))[1]
);

-- Users can delete their own PDFs
CREATE POLICY "Users delete own PDFs"
ON storage.objects FOR DELETE
USING (
    bucket_id = 'pdfs'
    AND auth.uid()::text = (storage.foldername(name))[1]
);
