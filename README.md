# doc-agent

A production web application built on top of [PageIndex](https://github.com/VectifyAI/PageIndex)
(by [Vectify AI](https://vectify.ai)) — a vectorless, reasoning-based RAG
framework. Forked from [kadirlofca/doc-agent](https://github.com/kadirlofca/doc-agent).

The `pageindex/` directory contains the upstream library, used as-is. All
changes are in `backend/`, `frontend/`, `cloudbuild.yaml`, and `Dockerfile`.

> For background on how PageIndex works — tree-index construction, LLM
> tree-search retrieval, and the FinanceBench results — see the
> [upstream repo](https://github.com/VectifyAI/PageIndex) and the
> [PageIndex blog post](https://pageindex.ai/blog/pageindex-intro).

---

## What I changed and why

### 1. Lexical pre-filter before LLM tree-search

**File:** `backend/services/shingling.py`, `backend/services/rag.py`

**The problem.** PageIndex's tree-search step sends the entire document tree
to an LLM and asks it to pick the relevant nodes. For large documents this
means sending hundreds of node summaries in a single prompt — expensive and
slow, and larger prompts give the LLM more surface area to get confused.

**What I added.** Before the LLM sees any candidates, a lightweight lexical
pre-filter narrows the field:

1. Flatten the PageIndex tree into individual candidate nodes
2. Compute word-level k-shingles (hashed n-grams) for each node's title +
   page-text preview
3. Rank all nodes by Jaccard similarity against the query's shingle set
4. Pass only the top-15 scoring candidates (score > 0.01) to the LLM tree-search
5. If no candidate scores above the threshold, fall back to the full tree
   (preserves original behaviour)

This is the same two-stage pattern as ANN-then-rerank in vector pipelines —
cheap filter, expensive reranker — applied to a vectorless system. The lexical
step costs negligible compute; the savings come from the LLM step seeing a
smaller, more focused context.

**Near-duplicate suppression.** Within the shortlist, a greedy pass removes
candidates whose content is ≥ 85% Jaccard-similar to an already-kept
candidate. Financial documents repeat boilerplate across sections; without
this, the LLM shortlist can fill up with near-identical entries.

---

### 2. Containment score instead of Jaccard for grounding

**File:** `backend/services/shingling.py` → `ground_answer()`

**The problem.** After the LLM generates an answer, I wanted a fast,
lightweight signal for whether the answer is actually grounded in the
retrieved context (i.e. not hallucinated). My first implementation used
Jaccard similarity between the answer's shingles and the context's shingles.

Jaccard is `|A ∩ B| / |A ∪ B|`. When the context is a long document passage
and the answer is a short sentence, the union is dominated by the context's
shingle set. Even a perfectly grounded answer gets a deflated score because
the denominator grows with context size, not answer relevance.

**The fix.** Switch to containment: `|A ∩ B| / |A|`. Normalise by the answer
size only. This measures "what fraction of what the model said appears in the
retrieved context" — which is exactly the grounding question — without being
penalised by how wide the context window is. Asymmetric query-vs-document
matching calls for an asymmetric metric.

The grounding score is logged per-query alongside retrieval telemetry and
returned in the API response, so it's available for monitoring without adding
latency to the user-facing path.

---

### 3. Multi-document RAG with async indexing

**File:** `backend/services/rag.py` → `run_rag_multi()`,
`backend/services/indexing.py`

**The problem.** PageIndex is designed for single-document retrieval. Users
want to upload a set of related PDFs (e.g. several quarterly filings) and ask
questions across all of them.

**What I added.**

- An async indexing queue processes uploads sequentially without blocking the
  UI. Documents show a pending/indexing/ready status; users can start chatting
  as soon as the first document is ready.
- `run_rag_multi()` fans out the tree-search step across all selected documents
  in parallel using `asyncio.gather`, then merges context before generation.
- When at least one document returns a positive lexical signal, documents with
  zero lexical score are dropped from the merged context. This prevents an
  unrelated document from polluting the answer prompt when the query is clearly
  scoped to a subset.

---

### 4. Provider-agnostic LLM abstraction

**File:** `backend/routes/providers.py`, `pageindex/llm/factory.py`

PageIndex defaults to OpenAI. I extended the LLM factory to support six
providers from the same interface:

| Provider   | Free tier | Notes |
|------------|-----------|-------|
| Google Gemini | Yes | Default recommendation; generous free quota |
| Groq       | Yes | Fast inference on open models |
| OpenRouter | Yes | Free-tier open models via unified API |
| Mistral AI | Yes | |
| OpenAI     | No  | gpt-4o, gpt-4.1 |
| Anthropic  | No  | claude-sonnet-4-6, claude-opus-4-6 |

Provider, model, and API key are configurable at runtime from the UI — no
redeploy needed to switch reasoners. This makes it straightforward to test
whether a cheaper or faster model degrades retrieval quality on a given
document set.

---

### 5. Full-stack rewrite: Next.js + FastAPI

The upstream fork was a Streamlit prototype — fine for experimentation, not
suitable for a multi-user deployment. I rewrote the application layer:

- **FastAPI backend** (`backend/`) — REST API for document management, RAG
  chat, provider configuration, and conversation history. Swagger UI available
  in dev mode (`/docs`).
- **Next.js 14 frontend** (`frontend/`) — TypeScript, App Router. Document
  collections are shown as cards on the landing page; chat lives inside a
  collection so the context (which documents are selected) is always clear.
- **Supabase** — Postgres for metadata + conversation history, Supabase
  Storage for PDF blobs, Supabase Auth for identity + session management.

---

### 6. Auth: Google OAuth + server-side proxy + hardened JWT

**Files:** `backend/auth.py`, `frontend/src/app/api/proxy/`

**Google OAuth with role-based access.** Login is via Google OAuth through
Supabase Auth. On first login the backend checks the user's email against
`ADMIN_EMAILS`; admins get write access (upload, delete), regular users get
read/chat only.

**Server-side auth proxy.** The initial implementation used Next.js URL
rewrites to forward API requests to FastAPI. This caused 401s on Cloud Run
because the auth cookie was not being forwarded correctly across the rewrite.
The fix: a server-side route handler in Next.js reads the Supabase session
cookie, attaches the JWT as a `Bearer` token in an `Authorization` header, and
proxies the request to FastAPI. The FastAPI backend only ever sees
already-authenticated requests.

**JWT verification via Supabase API.** The first iteration used PyJWT with the
Supabase JWT secret stored locally. This works but ties verification to a
secret that rotates if you cycle Supabase keys. Switched to verifying tokens
by calling the Supabase `/auth/v1/user` endpoint — Supabase handles the
verification, the backend just checks the returned user object. Removes local
key management and is more robust to token edge cases (expiry, format changes).

**Hardened responses.** Error responses from the backend do not include stack
traces or internal details. Cookies set with `HttpOnly`, `Secure`, and
`SameSite=Lax`. All mutation endpoints check role before proceeding.

---

### 7. Docker + GCP Cloud Run + Cloud Build CI/CD

**Files:** `Dockerfile`, `cloudbuild.yaml`, `start.sh`

**Multi-stage Docker build.**
- Stage 1: Node 20 builds the Next.js bundle
- Stage 2: Python 3.11-slim installs backend dependencies
- Stage 3: Runtime image copies both, serves them from a single container via
  `start.sh` (Next.js on 3000, FastAPI on 8000, nginx or process manager
  forwards :8080)

A single container simplifies Cloud Run deployment — one service URL, one
billing unit, no service mesh needed between frontend and backend.

**Cloud Build CI/CD.** `cloudbuild.yaml` triggers on push to `main`:
1. Build image tagged with `$COMMIT_SHA` and `latest`
2. Push both tags to Container Registry
3. Deploy `$COMMIT_SHA` tag to Cloud Run (`us-central1`)

Using the commit SHA tag means every deployment is pinned and rollback is a
single `gcloud run deploy --image=...` command.

**Retry logic for cold-start.** Cloud Run scales to zero. On the first request
after a cold start, the FastAPI container can take a few seconds to be ready
while the Next.js server is already accepting connections. Added retry logic in
the Next.js proxy route so the first request retries instead of immediately
returning a 502.

---

## Planned next steps

- Formal benchmarking of the lexical pre-filter on
  [FinanceBench](https://arxiv.org/abs/2311.11944) — the same benchmark used
  by the upstream PageIndex paper — to measure whether the shortlisting step
  changes retrieval accuracy versus the unfiltered baseline
- MinHash / LSH to approximate Jaccard at scale (relevant if document trees
  become very large)
- Streaming responses so the UI can show partial answers as they generate

---

## Setup

### Prerequisites

- Python 3.11+, Node.js 20+
- [Supabase](https://supabase.com) project (free tier is sufficient)
- At least one LLM API key (Gemini and Groq have free tiers)

### Environment variables

```bash
# .env in repo root

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...        # service-role key — keep secret

# Admin access (comma-separated emails)
ADMIN_EMAILS=you@example.com

# LLM keys — add whichever providers you want
GEMINI_API_KEY=AIza...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Production only
ENV=production
FRONTEND_URL=https://your-cloud-run-url
```

### Local development (without Docker)

```bash
# Python deps
pip install -r requirements.txt
pip install -r backend/requirements.txt

# Frontend deps
cd frontend && npm install && cd ..

# Start backend (terminal 1)
uvicorn backend.main:app --reload --port 8000

# Start frontend (terminal 2)
cd frontend && npm run dev
```

Open `http://localhost:3000`. Google OAuth must be configured in your Supabase
project under Authentication → Providers → Google.

### Docker

```bash
docker build \
  --build-arg NEXT_PUBLIC_SUPABASE_URL=$SUPABASE_URL \
  --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY \
  -t doc-agent .

docker run -p 8080:8080 --env-file .env doc-agent
```

### Deploy to GCP Cloud Run

1. Enable Cloud Run, Cloud Build, and Container Registry APIs in your GCP project
2. Add secrets to Secret Manager: `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
   `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`
3. Update `ADMIN_EMAILS` and the Supabase public keys in `cloudbuild.yaml`
4. Connect the repo to Cloud Build — push to `main` deploys automatically

### Tests

```bash
pytest tests/
```

---

## Credit

The retrieval framework (`pageindex/`) is [PageIndex](https://github.com/VectifyAI/PageIndex)
by [Vectify AI](https://vectify.ai), used under its original license.
This repo does not modify or redistribute PageIndex — it imports it as a
local library. All application code, retrieval extensions, and infrastructure
are independent of the upstream project.
