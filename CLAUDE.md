# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ShiftReady** is a full-stack application that automates residential relocation inventory management using Google Gemini AI.

- **Backend** (`shiftready-backend/`): FastAPI service orchestrating the pipeline: video intake → AI vision extraction → user review → AI pricing → marketplace publication. Deployed on Cloud Run (Sydney region), Firestore as DB, Firebase Auth.
- **Frontend** (`../shiftready-ui/`): Next.js 16 / React 19 SPA, sibling directory to this repo. Launched with `--add-dir ../shiftready-ui` so both repos are editable in the same session.

Always launch Claude from the backend directory with:
```
claude --add-dir ../shiftready-ui
```

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server
uvicorn app.main:app --reload --port 8080

# Lint
ruff check . --exclude scripts

# Run all tests with coverage
pytest --cov=app --cov-report=term-missing

# Run a single test file
pytest tests/test_sales.py -v

# Run a single test
pytest tests/test_sales.py::test_function_name -v
```

API docs available at `http://localhost:8080/docs` when running locally.

## Architecture

### Core Services (`app/services/`)

All business logic lives here. Routers are thin orchestrators — they call services and return responses.

- **`firestore.py`** — All Firestore CRUD. Hierarchical structure: `saleEvents/{id}/bundles/{id}/items/{id}`. Async throughout; note that sub-collection deletes require manual cleanup (no cascading).
- **`gemini.py`** — Gemini AI vision extraction and pricing. Uses Pydantic schemas + `response_mime_type="application/json"` for deterministic structured output.
- **`pipelines.py`** — Background async tasks for extraction and pricing, with exponential retry logic and FAILED status fallback.
- **`auth.py`** — Firebase ID token validation. Tokens prefixed with `dev_` bypass verification when `K_SERVICE` env var is absent (local dev only).
- **`notifier.py`** — WebSocket `ConnectionManager` for real-time status updates during processing.

Global service singletons are initialized in `services/__init__.py`.

### Sale Lifecycle (State Machine)

```
PENDING_UPLOAD → PROCESSING → READY_FOR_REVIEW → PRICING_IN_PROGRESS → LIVE → ARCHIVED
```

Terminal states: `PARTIALLY_SOLD`, `EXPIRED`, `FAILED`, `ARCHIVED`. Status transitions are logged to a `statusHistory` array on the sale document using `firestore.ArrayUnion`.

### Firestore Schema

```
saleEvents/{eventId}
  ├── metadata (status, sellerId, videoUrl, timestamps)
  ├── bundles/{bundleId}
  │   └── items/{itemId}
  │       ├── predicted_*/actual_* price fields
  │       └── pricing_reasoning
users/{userId}
```

### Authentication

- All protected endpoints require Firebase ID token as `Authorization: Bearer <token>`
- WebSocket auth via query param `?token=<token>`
- `validate_sale_owner` enforces resource-level ownership checks
- Marketplace endpoints allow anonymous browsing; seller details masked from non-owners

### GCS Signed URLs

Never expose raw GCS paths to the frontend. Always generate signed URLs via `app/utils/gcs.py` — PUT URLs expire in 15 min, GET URLs in 1 hour.

## Key Conventions

- **Async-first**: All I/O (Firestore, GCS, Gemini) must be `await`ed. Never use synchronous `requests` in request handlers.
- **Python 3.13+**: Use modern type hints (`dict[str, Any]`, not `Dict[str, Any]`).
- **Routers must have `response_model`**: No bare untyped responses.
- **AI output must be validated** against Pydantic schemas before persisting to Firestore.
- **Log AI metadata** (tokens, finish_reason) on every Gemini call.

## Environment Variables

Required (see `.env.example`):

```
GCP_PROJECT_ID
GCP_SERVICE_ACCOUNT
GCP_UPLOAD_BUCKET
GCP_REGION
GOOGLE_APPLICATION_CREDENTIALS=./shiftready-backend-service-account.json
```

`K_SERVICE` is injected by Cloud Run; its absence enables local dev auth bypass.

## CI/CD

`cloudbuild.yaml` runs: lint → test → Docker build → push to Artifact Registry → deploy to Cloud Run (`australia-southeast1`). Test coverage report is uploaded as XML.

## Additional Docs

- `GEMINI.md` — Gemini/Vertex AI setup, prompt engineering, schema strategies
- `FRONTEND_AUTH_INTEGRATION.md` — Firebase Client SDK setup and WebSocket auth patterns

---

## Frontend (shiftready-ui)

Next.js 16.2.4 · React 19 · TypeScript · TanStack Query v5 · Tailwind v4 · lucide-react · clsx · tailwind-merge

### Directory Structure

```
src/
├── app/                        # Next.js App Router pages
│   ├── layout.tsx              # Root layout: Providers + Sidebar + Header
│   ├── page.tsx                # Home
│   ├── create/page.tsx         # Video upload + sale init
│   └── inventory/[eventId]/page.tsx  # Inventory review cockpit
├── components/
│   ├── providers.tsx           # QueryClientProvider (+ ReactQueryDevtools)
│   ├── ui/
│   │   ├── sidebar.tsx         # Fixed left nav (w-64)
│   │   └── header.tsx          # Fixed top bar (h-16)
│   └── features/
│       ├── create/             # Video uploader, capture guide
│       └── inventory/          # Inventory cards, pricing grid, delete overlay
├── hooks/
│   └── use-inventory.tsx       # Core hook: status polling + summary fetch + mutations
└── lib/
    ├── api.ts                  # Centralized fetch wrapper; all API calls live here
    └── types.ts                # InventoryItem, RoomBundle, SaleSummary interfaces
```

### Adding a New Page

1. Create `src/app/<route>/page.tsx` (App Router — no `pages/` directory).
2. Add any new API calls to `src/lib/api.ts` following the existing pattern.
3. Add corresponding TypeScript types to `src/lib/types.ts`.
4. If the page needs data fetching, create a hook in `src/hooks/` using TanStack Query.

### API Client (`src/lib/api.ts`)

- Base URL from `NEXT_PUBLIC_API_URL`; falls back to the Cloud Run URL.
- Central `apiRequest<T>()` wrapper handles errors (parses FastAPI's `detail` field) and 204 No Content.
- **No auth headers yet** — the UI currently hits the API without tokens. Backend auth bypass is active in local dev (`K_SERVICE` absent). Full Firebase token integration is documented in `FRONTEND_AUTH_INTEGRATION.md`.
- All functions follow: `` `${API_BASE}/sales/${eventId}/...` ``

### TanStack Query Conventions

- `QueryClient` is instantiated once in `providers.tsx` with default config.
- Polling is conditional — `use-inventory.tsx` polls every 1500 ms only during `processing` or `pricing_in_progress` states.
- All mutations call `queryClient.invalidateQueries` on success to keep UI in sync.
- Use `staleTime: 5 * 60 * 1000` for data that doesn't change during AI processing.

### Design System

- **Dark-only** — `<html className="dark">` is hardcoded; no light mode.
- **Tailwind v4** — config is in `src/app/globals.css` via `@theme {}`, not `tailwind.config.js`.
- **Layout**: main content has `pl-64` (sidebar) + `pt-16` (header) — don't override these on new pages.
- **Key CSS variables** (use via Tailwind utility classes):
  - `bg-surface`, `bg-surface-container-low/high/lowest/highest`
  - `text-on-surface`, `text-on-surface-variant`
  - `text-primary` (#adc6ff electric blue), `text-tertiary` (#4edea3 green for pricing)
  - `border-outline`, `border-outline-variant`
- **Icons**: lucide-react only — do not introduce other icon libraries.
- **Class merging**: use `clsx` + `tailwind-merge` (`cn()` pattern) for conditional classes.

### Frontend Commands

```bash
# Run dev server (from shiftready-ui directory)
npm run dev        # starts on http://localhost:3000

# Lint
npm run lint

# Build
npm run build
```

### Environment Variables (UI)

```
NEXT_PUBLIC_API_URL=http://localhost:8080   # point to local backend during dev
```
