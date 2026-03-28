# PageIndex — Project Overview

PageIndex is a **vectorless, reasoning-based RAG** (Retrieval-Augmented Generation) system
that transforms long PDF documents into hierarchical tree indexes and uses LLM reasoning
for retrieval — instead of traditional vector similarity search.

## What It Does

PageIndex processes PDF documents in two steps:

1. **Indexing** — Builds a hierarchical "table of contents" tree structure from the document.
2. **Retrieval** — Navigates the tree using LLM reasoning to locate the most relevant
   sections, simulating how a human expert would read and search a document.

## Why It Matters

Traditional vector-based RAG splits documents into chunks and retrieves by semantic
similarity. But **similarity ≠ relevance** — especially for long, professional documents
that require domain expertise and multi-step reasoning. PageIndex replaces this with
structured, explainable, reasoning-driven retrieval that provides traceable page and
section references.

## Key Technologies

- **Python** — Core language for the indexing pipeline and retrieval logic.
- **Streamlit** — Interactive web UI for uploading PDFs, building indexes, and chatting.
- **Multi-provider LLM support** — Anthropic, OpenAI, Gemini, Groq, OpenRouter, Mistral, and Ollama.
- **Middleware stack** — Rate limiting, caching (SHA-256 disk cache with TTL), and retry with exponential backoff.
- **Supabase** — Optional cloud storage backend for indexes and documents.

## How It Differs from Vector-Based RAG

| Aspect              | Vector RAG                  | PageIndex                         |
|---------------------|-----------------------------|-----------------------------------|
| Storage             | Vector database             | Hierarchical tree index           |
| Retrieval method    | Embedding similarity search | LLM reasoning over tree structure |
| Document handling   | Chunking                    | Natural section boundaries        |
| Explainability      | Opaque similarity scores    | Traceable reasoning with page refs|

For more details, see the [README](README.md) and [Architecture](ARCHITECTURE.md) docs.
