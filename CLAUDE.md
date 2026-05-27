# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## Project Overview

**ShiftReady** automates residential relocation inventory management using Google Gemini.

- **Backend** (`shiftready-backend/`, this repo): FastAPI on Cloud Run (`australia-southeast1`). Firestore (Native), GCS, Firebase Auth.
- **Frontend** (`../shiftready-ui/`): Next.js 16 / React 19. Sibling directory; launch with `--add-dir ../shiftready-ui` so both repos are editable together.

Pipeline: live capture / video intake → AI extraction → user review → AI pricing → marketplace publish → buyer messaging → sold rollup.

Always launch Claude from the backend directory:

```
claude --add-dir ../shiftready-ui
```

## Commands

```bash
# Install
pip install -r requirements.txt

# Dev server
uvicorn app.main:app --reload --port 8080

# Lint
ruff check . --exclude scripts

# Tests
pytest --cov=app --cov-report=term-missing
pytest tests/test_sales.py -v
pytest tests/test_sales.py::test_function_name -v
pytest tests/integration/ -v
```

Swagger UI: `http://localhost:8080/docs`.

## Architecture

### Layered Design

```
Routers (app/routers/)      ← thin: validate, call service, return
   ↓
Services (app/services/)    ← business logic; compose repos + AI
   ↓
AI (app/ai/)                ← Gemini calls, Pydantic schemas
   ↓
Repos (app/repos/)          ← only code that touches Firestore directly
   ↓
Firestore / GCS / Gemini
```

**Layering rules — non-negotiable:**

- Routers do not touch Firestore. Always go through a service → repo.
- AI output must be validated against a Pydantic schema before persisting.
- All I/O is `await`ed. Never use synchronous `requests` in handlers.

### Routers (`app/routers/`)

- **`sales.py`** — inventory, capture (frame + finalize-v2), append, status, summary, WebSocket, publish/unpublish, bundle/item/image CRUD.
- **`marketplace.py`** — public anonymous browse; seller PII masked.
- **`messages.py`** — buyer-seller threads, structured offers, accept (→ reserves item).
- **`notifications.py`** — in-app notification feed.
- **`sold.py`** — mark sold at item/bundle/sale granularity; drives `PARTIALLY_SOLD` / `SOLD` rollup.
- **`users.py`** — profile, username, phone.

### Services (`app/services/`)

- **`firestore.py`** — Firestore facade. Composes `app/repos/`: `sale_repo`, `bundle_repo`, `item_repo`, `marketplace_repo`, `user_repo`, `conversation_repo`, `notification_repo`, `transaction_repo`. Sub-collection deletes are NOT cascading — clean manually.
- **`gemini.py`** — `GeminiProcessor` facade wrapping `ExtractionService` + `PricingService`. Public methods:
  - `process_walkthrough` — full video extraction
  - `process_frames` — batch JPEG frames
  - `identify_single_frame` — lightweight per-frame identify (live capture)
  - `refine_captured_items` — text-only dedup + room grouping
  - `estimate_listing_prices` — urgency-weighted pricing
- **`pipelines.py`** — background async tasks; exponential retry; `FAILED` fallback:
  - `run_extraction_pipeline` — video → bundles/items → `READY_FOR_REVIEW`
  - `run_frames_extraction_pipeline` — batch JPEG frames → bundles/items
  - `run_capture_refinement_pipeline` — Phase 2 live: accept `CapturedItemInput[]`, one text-only Gemini refinement, write, kick pricing
  - `run_pricing_pipeline` — summary → Gemini pricing → updates `predicted_listing_price` + `actual_listing_price`
  - `run_append_extraction_pipeline` — append new bundles without clearing
- **`auth.py`** — Firebase ID token validation. `dev_` prefix bypasses verification when `K_SERVICE` is absent (local only).
- **`notifier.py`** — WebSocket `ConnectionManager` for pipeline + message events.
- **`messaging.py`** — conversation + offer logic; structured message types (text, offer, counter, accept).
- **`inventory_lifecycle.py`** — sold-state machine; rolls item/bundle sold flags up to sale `PARTIALLY_SOLD` / `SOLD`.
- **`permissions.py`** — resource-level auth helpers; `validate_sale_owner`.
- **`jobs.py`** — triggers the `frame_extractor` Cloud Run Job.

Global service singletons initialized in `services/__init__.py`.

### AI Layer (`app/ai/`)

- **`extraction.py`** — `ExtractionService` (walkthrough, frames, single-frame identify, refinement).
- **`pricing.py`** — `PricingService.estimate_listing_prices()` with urgency discount based on days-until-move-out.
- **`schemas.py`** — `SingleFrameResult`, `PricingList`, `PricingResult`, `RefinementGrouping`, `RefinementResult`.
- **`schema_utils.py`** — `get_clean_schema()`: Pydantic → Gemini-compatible JSON schema (inlines `$ref`, strips null branches, removes backend-managed fields like `actual_*`).
- **`client.py`** — Gemini client factory, `MODEL_ID`, `SYSTEM_INSTRUCTION`.

Every Gemini call logs `prompt_token_count`, `candidates_token_count`, `finish_reason`.

### Repos (`app/repos/`)

One repo per Firestore collection. **All direct document access goes here.** Don't bypass `firestore.py` in routers.

Repos: `sale_repo`, `bundle_repo`, `item_repo`, `marketplace_repo`, `user_repo`, `conversation_repo`, `notification_repo`, `transaction_repo`.

### Core (`app/core/`)

- `config.py` — `pydantic-settings`
- `deps.py` — FastAPI dependency injectors
- `logging.py` — structured JSON logging
- `middleware.py` — request middleware

## Sale Lifecycle (State Machine)

```
PENDING_UPLOAD → PROCESSING → READY_FOR_REVIEW → PRICING_IN_PROGRESS → LIVE → ARCHIVED
```

Terminal / branch states: `PARTIALLY_SOLD`, `SOLD`, `EXPIRED`, `FAILED`, `ARCHIVED`.

Every transition appends to `statusHistory` (array via `firestore.ArrayUnion`).

## Live Capture Flow (Phase 2)

```
[Camera] → tap-first user confirm
    → POST /sales/{id}/capture/frame
    → Gemini single-frame identify → name/brand/price/gcs_uri returned
    → user reviews all items in ItemReviewScreen
    → POST /sales/{id}/capture/finalize-v2 (sends pre-analyzed items)
    → run_capture_refinement_pipeline:
        1. status → PROCESSING
        2. Gemini refinement (text-only): dedup + grouping by item index
        3. Write bundles/items (frame GCS URI as cover image)
        4. status → READY_FOR_REVIEW (WS notify)
        5. status → PRICING_IN_PROGRESS
        6. run_pricing_pipeline → status → READY_FOR_REVIEW (final)
```

**Key constraint:** per-frame extraction already done client-side. `finalize-v2` does NOT re-extract. One refinement Gemini call at finalize.

## Firestore Schema

```
saleEvents/{eventId}
  ├── metadata (status, sellerId, videoUrl, captureMode, timestamps, statusHistory)
  ├── bundles/{bundleId}
  │   └── items/{itemId}
  │       ├── predicted_*/actual_* price fields
  │       ├── sale_status (AVAILABLE | RESERVED | SOLD)
  │       ├── pricing_reasoning
  │       └── images[{id, gcs_path, source, is_cover, uploaded_at}]
  ├── conversations/{conversationId}    # buyer-seller threads
  │   └── messages/{messageId}          # text · offer · counter · accept
  └── transactions/{transactionId}      # on offer accept

users/{userId}
notifications/{userId}/{notificationId}
```

- `captureMode: "live" | "frames" | "batch"` — set at pipeline completion.
- Item image `source`: `"frame_extract"` (capture) or `"user_upload"` (manual upload in cockpit).

## Authentication

- Protected REST endpoints: `Authorization: Bearer <token>`.
- WebSocket: token in query `?token=<token>`.
- `validate_sale_owner` for sale-level resource access.
- Marketplace endpoints anonymous; seller email/phone masked from non-owners.
- **Local bypass:** `dev_*` tokens skip Firebase verification when `K_SERVICE` is absent. Active only outside Cloud Run.

## GCS Signed URLs

**Never expose raw GCS paths to the frontend.** Use `app/utils/gcs.py`:

- PUT URLs: 15 min
- GET URLs: 1 hour

Path conventions:

- Capture frames: `captures/{eventId}/{frameId}.jpg`
- Item user-uploads: `sales/{eventId}/items/{itemId}/{imageId}.jpg`
- Videos: `{userId}/{filename}`

## Key Conventions

- **Async-first.** All I/O awaited.
- **Python 3.13+.** Modern type hints (`dict[str, Any]`, not `Dict[str, Any]`).
- **Routers must declare `response_model`.** No bare untyped responses.
- **Validate AI output** with a Pydantic schema before Firestore writes.
- **Log AI metadata** on every Gemini call.
- **Single source of Firestore truth.** All document access through `app/repos/`.

## Environment Variables

See `.env.example`:

```
GCP_PROJECT_ID
GCP_SERVICE_ACCOUNT
GCP_UPLOAD_BUCKET
GCP_REGION
GOOGLE_APPLICATION_CREDENTIALS=./shiftready-backend-service-account.json
```

`K_SERVICE` is injected by Cloud Run; its absence enables local dev auth bypass.

## CI/CD

`cloudbuild.yaml` runs on push to `master`:

1. `ruff check .` (excludes `scripts/`)
2. Docker build with layer cache from previous `:latest`
3. Push `:SHORT_SHA` + `:latest` to Artifact Registry
4. Deploy Firestore indexes
5. Deploy backend to Cloud Run (`australia-southeast1`, unauthenticated)
6. Build + deploy `frame_extractor` Cloud Run Job

Machine `E2_HIGHCPU_8`, timeout 1200s.

---

## Frontend Quick Reference

Full details in `../shiftready-ui/CLAUDE.md`.

- Next.js 16 App Router · React 19 · TypeScript · Tailwind v4 (`@theme {}` block) · TanStack Query v5 · Radix · lucide-react · sonner · Firebase 12 · cmdk.
- Layout groups: `(auth)` · `(sellers)` · `(market)` · `(public)`.
- Shell: `components/shell/` — header, icon-rail sidebar, command palette, notifications panel, profile menu, bottom tab bar.
- All API calls live in `src/lib/api.ts`. Single `apiRequest<T>` wrapper.
- Dark-only. `pl-64` + `pt-16` is a layout invariant for authenticated shell pages.
- Live capture: tap-first, no on-device ML. Per-tap → `POST /capture/frame` → Gemini identify. Finalize → `POST /capture/finalize-v2` with pre-analyzed items.

## Additional Docs

- `README.md` — production-facing documentation
- `../shiftready-ui/CLAUDE.md` — frontend AI-pairing guide
