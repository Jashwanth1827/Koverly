# Koverly

**Understand, manage, and use every insurance policy your family owns.**

Koverly is an Insurance Operating System for individuals and families. It helps you discover
what insurance you actually have, organize every policy in one place, understand complicated
documents, track renewals and premiums, manage family members, track claims, and reach the right
information in an emergency.

> Koverly is an organizational and informational tool. It is not an insurer, lawyer, doctor, or
> financial adviser, and it never guarantees a claim outcome.

---

## What it does

| Module | Purpose |
| --- | --- |
| Dashboard | Family protection overview: active policies, annual premium, life/health cover, renewals, actions, recent claims. |
| Family | One family group with members (self, spouse, parents, children, siblings) and roles (owner, admin, member, viewer). |
| Policies | Life, health, motor, home, travel, personal accident, and other policies with extensible metadata. |
| Documents | Private policy document vault (PDF, scan, photo, Word, text) with upload, view, download, delete, and processing status. |
| Automatic understanding | Upload any insurance document — Koverly detects the format, reads it (OCR for scans/photos), classifies what it is, infers the insurance category/type, and shows what it found. No manual type selection. |
| OCR | Self-hosted Tesseract reads scanned policy copies — PDFs without a text layer and JPG/PNG/WEBP images — so their fields are extractable too. |
| AI extraction | Structured field extraction with confidence, source page, source text, and an evidence state (`explicitly_found` / `inferred` / `uncertain` / `not_found`). Fields you review are the only ones applied. |
| Multi-policy documents | One upload can hold several policies; Koverly splits it into separate candidates, each with its own classification and page range. |
| Ask InsuraOS | Grounded Q&A over your own policies, family, claims, and documents, with source references. |
| Insurance Intelligence | Expiring policies, missing information, and *potential* overlaps — never stated as advice. |
| Claims | Claim records with statuses, a timeline, and claim documents. |
| Emergency mode | Fast, readable summary of relevant cover, TPA, helpline, and claim steps, plus a scoped temporary share link. |
| Calendar | Renewals, premiums, claims, and document dates aggregated from real data. |
| Search | Authorized global search across policies, members, claims, and documents. |
| Audit log | Actor, action, resource, timestamp for sensitive operations. No raw document contents. |

## Product principles

- **No fake functionality.** Every value in the UI comes from the database. Integrations that are
  not configured report their real state (for example, `AI provider: null`).
- **AI never invents.** If a field is absent from a document, it is reported as *not found in
  uploaded document* — never guessed.
- **AI is reviewed.** Extracted fields are *proposed* until you confirm, edit, or reject them.
- **Tenant isolation.** A user can never access another user's policies, claims, documents, or
  vector chunks.

---

## Architecture

```
frontend/  Next-generation SPA — React + TypeScript + Vite + Tailwind
backend/   FastAPI — Python 3.13, SQLAlchemy async, Pydantic v2
```

### Backend layout

```
app/
  api/v1/        Versioned routers (auth, families, policies, documents, claims,
                 insights, reminders, emergency, search, dashboard, config)
  core/          config, security, errors, logging, rate limiting
  db/            async engine/session
  models/        SQLAlchemy models (user, family, policy, document, claim, ...)
  schemas/       Pydantic request/response models
  services/      business logic (policy, document, extraction, retrieval,
                 assistant, intelligence, claims, reminders, audit)
  ai/            provider abstraction: base, factory, null_provider, openai_provider
  integrations/  storage (local/S3) and notifications (noop/webhook)
```

### Key design choices

- **AI provider abstraction** — `AIProvider` with `extract_candidates` (one or more policies per
  document), `classify_insurance`, `extract_policy`, `answer_policy_question`,
  `summarize_document`, and `analyze_coverage`. `null` is a deterministic local provider that
  performs no external calls and fabricates nothing. `openai` targets any OpenAI-compatible
  endpoint. Swapping providers is configuration, not code.
- **Multi-format document processors** — `app/utils/text_extract.py` dispatches by detected
  content type: PDF (pypdf + OCR fallback), images (Pillow + Tesseract), DOCX (python-docx or a
  ZIP/XML fallback), legacy DOC (printable-run recovery), RTF, and plain text. Adding a format is
  a new branch in one place, never a change to the pipeline.
- **Universal, non-fixed schema** — universal fields (insurer, policy number, premium, dates, ...)
  plus dynamic, category-specific extras (health: waiting period, TPA; motor: IDV, registration;
  life: maturity, nominee; travel; property). Nothing is mandatory and absent fields stay absent.
- **Taxonomy is secondary** — the user never selects a category or type. `app/ai/taxonomy.py`
  maps inferred categories onto the persisted policy types so dashboards, emergency mode, and
  coverage maps keep working.
- **Private storage with signed URLs** — documents are never served publicly; access goes through
  short-lived signed URLs.
- **Retrieval with tenant isolation** — document chunks are always filtered by `user_id`/`family_id`
  before they reach the model.
- **Prompt-injection defense** — uploaded documents are treated as untrusted text and are clearly
  separated from system instructions and the user question.
- **Asynchronous processing** — uploads return immediately; extraction and indexing run in the
  background and update document status.
- **Self-hosted OCR** — pages without a text layer (scans) are rendered with `pdf2image`
  (poppler) and read with Tesseract. OCR is bounded by page count and per-page timeout, and it
  degrades to a clear failure message rather than fabricating text when it is unavailable or
  finds nothing.

---

## Getting started

### Clone

```bash
git clone https://github.com/Jashwanth1827/Koverly.git
cd Koverly
```

### Prerequisites

- Python 3.13 (3.11+ supported) with [uv](https://docs.astral.sh/uv/) or pip
- Node.js 24 (18+ supported)
- Optional: Docker + Docker Compose

### Backend

```bash
cd backend
cp .env.example .env
# Set SECRET_KEY (generate with: python -c "import secrets;print(secrets.token_urlsafe(48))")
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

API docs (development only): <http://localhost:8000/api/docs>

For scanned copies and photos, install the OCR system packages (otherwise those
uploads fail with a clear message rather than fabricating text):

```bash
# Debian/Ubuntu
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng poppler-utils
```

### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev          # http://localhost:5173, proxies /api to the backend
```

### Tests

```bash
cd backend
pytest -q
```

### Docker

```bash
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
docker compose up --build
# Frontend: http://localhost:8080   Backend: http://localhost:8000
```

### Deploy to Render

A Render Blueprint (`render.yaml`) is included. It provisions a Postgres database and a single
web service that builds the combined production image (`deploy/render/Dockerfile`): nginx serves
the SPA and proxies `/api` to FastAPI on the same origin (required because document signed URLs
are relative paths).

**One-click:** Render Dashboard → **New → Blueprint** → select this repository → **Apply**.
Render wires `DATABASE_URL` from the database, generates `SECRET_KEY`, and deploys.

**Or with the Render CLI:**

```bash
render blueprint launch          # create the service + database from render.yaml
```

Build and run the exact production image locally:

```bash
docker build -f deploy/render/Dockerfile -t koverly .
docker run -p 8080:8080 -e SECRET_KEY=dev-secret -e DATABASE_URL="sqlite+aiosqlite:////tmp/k.db" koverly
# http://localhost:8080  (health: /health)
```

Notes:

- The container binds nginx to the platform-provided `$PORT`; the API runs internally on `:8000`.
- `postgres://` / `postgresql://` URLs from Render are rewritten to `postgresql+asyncpg://`.
- `CORS_ORIGINS` defaults to `RENDER_EXTERNAL_URL` when set.
- Local storage (`STORAGE_LOCAL_ROOT`) is used by default. Render's disk is ephemeral on the free
  plan — attach a persistent disk at `/app/storage`, or configure S3, for durable documents.
- Tables are created on startup (`init_models`). For production, migrate to Alembic.

---

## Configuration

All secrets come from environment variables — nothing sensitive is committed. See
`backend/.env.example` and `frontend/.env.example`. Highlights:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | JWT signing key. **Required in production.** |
| `DATABASE_URL` | SQLite by default; PostgreSQL via `postgresql+asyncpg://…` in production. |
| `STORAGE_BACKEND` | `local` or `s3`. |
| `SIGNED_URL_TTL_SECONDS` | Lifetime of document access URLs. |
| `OCR_ENABLED` | `true`/`false` — self-hosted Tesseract OCR for scanned copies. |
| `OCR_LANGUAGES` | Tesseract language codes (default `eng`). |
| `OCR_DPI` / `OCR_MAX_PAGES` / `OCR_PAGE_TIMEOUT_SECONDS` | Rendering quality and OCR bounds. |
| `TESSERACT_CMD` | Optional absolute path to the tesseract binary. |
| `AI_PROVIDER` | `null` (default, offline, no fabrication) or `openai`. |
| `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` | External model credentials and endpoint. |
| `NOTIFICATION_BACKEND` | `noop` or `webhook`. |
| `CORS_ORIGINS` | Allowed browser origins. |
| `RATE_LIMIT_PER_MINUTE` | Per-client request budget. |

---

## Security

- JWT authentication with Argon2 password hashing.
- Role-based authorization per family (owner / admin / member / viewer), enforced on every
  resource access.
- Private document storage with short-lived signed URLs; no public buckets.
- Upload validation on content type and size.
- Structured error responses that never leak stack traces.
- Audit logging for sensitive actions, with no raw document contents recorded.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- Tenant-scoped retrieval so the assistant can never read another user's data.
- Prompt-injection defenses around untrusted document text.

## Known limitations

- Local and test environments create tables via `init_models`; production should use Alembic
  migrations (a migration toolchain is intentionally not added yet to avoid premature dependencies).
- Billing records a plan preference only; no payment processor is connected.
- Email/WhatsApp ingestion and insurer integrations are extension points, not implemented.

## Roadmap (extension points)

Email ingestion, WhatsApp notifications, insurer integrations, employer benefits,
advisor portal, B2B accounts, analytics, and multilingual support.
