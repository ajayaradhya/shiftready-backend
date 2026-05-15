# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ShiftReady** is a full-stack application that automates residential relocation inventory management using Google Gemini AI.

- **Backend** (`shiftready-backend/`): FastAPI service orchestrating the pipeline: live capture / video intake → AI vision extraction → refinement → user review → AI pricing → marketplace publication. Deployed on Cloud Run (Sydney region), Firestore as DB, Firebase Auth.
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

- **`firestore.py`** — Firestore facade. Delegates to repo layer (`app/repos/`): `sale_repo`, `bundle_repo`, `item_repo`, `marketplace_repo`, `user_repo`. Hierarchical structure: `saleEvents/{id}/bundles/{id}/items/{id}`. Async throughout; sub-collection deletes require manual cleanup (no cascading).
- **`gemini.py`** — `GeminiProcessor` facade wrapping `ExtractionService` (in `app/ai/extraction.py`) and `PricingService` (in `app/ai/pricing.py`). Public methods: `process_walkthrough`, `process_frames`, `identify_single_frame`, `refine_captured_items`, `estimate_listing_prices`. Uses Pydantic schemas + `response_mime_type="application/json"` for deterministic structured output.
- **`pipelines.py`** — Background async tasks with exponential retry and FAILED status fallback:
  - `run_extraction_pipeline` — video → Gemini → bundles/items → `READY_FOR_REVIEW`
  - `run_frames_extraction_pipeline` — batch JPEG frames → Gemini → bundles/items
  - `run_capture_refinement_pipeline` — Phase 2 live capture: accepts pre-analyzed `CapturedItemInput` list, runs one text-only Gemini refinement call (dedup + room grouping), writes bundles/items to Firestore, then hands off to pricing. No re-extraction — items already analyzed per-frame during capture.
  - `run_pricing_pipeline` — full summary → Gemini pricing → updates `predicted_listing_price` + `actual_listing_price` → `READY_FOR_REVIEW`
  - `run_append_extraction_pipeline` — appends new bundles from a second video without clearing existing data
- **`auth.py`** — Firebase ID token validation. Tokens prefixed with `dev_` bypass verification when `K_SERVICE` env var is absent (local dev only).
- **`notifier.py`** — WebSocket `ConnectionManager` for real-time status updates during processing.

Global service singletons are initialized in `services/__init__.py`.

### AI Layer (`app/ai/`)

- **`extraction.py`** — `ExtractionService`:
  - `process_walkthrough(gcs_uri)` — full video extraction
  - `process_frames(gcs_uris)` — batch JPEG frames → room bundles
  - `identify_single_frame(gcs_uri)` — lightweight per-frame identify (name/brand/price only); used during live capture at confirm time
  - `refine_captured_items(items)` — text-only Gemini call; groups pre-analyzed items into room bundles using index-based assignment, deduplicates; returns `[{bundle_name, item_indices[]}]`
- **`pricing.py`** — `PricingService.estimate_listing_prices()` — urgency discount based on days until move-out
- **`schemas.py`** — AI output schemas: `SingleFrameResult`, `PricingList`, `PricingResult`, `RefinementGrouping`, `RefinementResult`
- **`schema_utils.py`** — `get_clean_schema()`: converts Pydantic → Gemini-compatible JSON schema (inlines `$ref`, strips null branches, removes backend-managed fields like `actual_*` prices)
- **`client.py`** — Gemini client factory, `MODEL_ID`, `SYSTEM_INSTRUCTION`

### Sale Lifecycle (State Machine)

```
PENDING_UPLOAD → PROCESSING → READY_FOR_REVIEW → PRICING_IN_PROGRESS → LIVE → ARCHIVED
```

Terminal states: `PARTIALLY_SOLD`, `EXPIRED`, `FAILED`, `ARCHIVED`. Status transitions are logged to a `statusHistory` array on the sale document using `firestore.ArrayUnion`.

### Live Capture Flow (Phase 2)

```
[Camera] → MediaPipe (on-device, WASM) → user confirms item
    → POST /sales/{id}/capture/frame
    → Gemini single-frame identify → name/brand/price/gcs_uri returned immediately
    → user reviews all items in ItemReviewScreen
    → POST /sales/{id}/capture/finalize-v2  (sends pre-analyzed items)
    → run_capture_refinement_pipeline:
        1. Status → PROCESSING
        2. Gemini refinement call (text-only): dedup + room grouping by item index
        3. Write bundles/items to Firestore (frame GCS URI as cover image per item)
        4. Status → READY_FOR_REVIEW + WS notify
        5. Status → PRICING_IN_PROGRESS
        6. run_pricing_pipeline → Status → READY_FOR_REVIEW (final)
```

Key constraint: per-frame extraction already done client-side. `finalize-v2` does NOT re-extract. One refinement Gemini call total at finalize.

### Firestore Schema

```
saleEvents/{eventId}
  ├── metadata (status, sellerId, videoUrl, captureMode, timestamps)
  ├── bundles/{bundleId}
  │   └── items/{itemId}
  │       ├── predicted_*/actual_* price fields
  │       ├── pricing_reasoning
  │       └── images[{id, gcs_path, source, is_cover, uploaded_at}]
users/{userId}
```

`captureMode: "live" | "frames" | "batch"` set on sale at pipeline completion.
Item image `source` values: `"frame_extract"` (from live/frames capture), `"user_upload"` (manual upload in inventory cockpit).

### Authentication

- All protected endpoints require Firebase ID token as `Authorization: Bearer <token>`
- WebSocket auth via query param `?token=<token>`
- `validate_sale_owner` enforces resource-level ownership checks
- Marketplace endpoints allow anonymous browsing; seller details masked from non-owners

### GCS Signed URLs

Never expose raw GCS paths to the frontend. Always generate signed URLs via `app/utils/gcs.py` — PUT URLs expire in 15 min, GET URLs in 1 hour.
- Capture frames: `captures/{eventId}/{frameId}.jpg`
- Item user-uploads: `sales/{eventId}/items/{itemId}/{imageId}.jpg`
- Videos: `{userId}/{filename}`

## Key Conventions

- **Async-first**: All I/O (Firestore, GCS, Gemini) must be `await`ed. Never use synchronous `requests` in request handlers.
- **Python 3.13+**: Use modern type hints (`dict[str, Any]`, not `Dict[str, Any]`).
- **Routers must have `response_model`**: No bare untyped responses.
- **AI output must be validated** against Pydantic schemas before persisting to Firestore.
- **Log AI metadata** (tokens, finish_reason) on every Gemini call.
- **Repos layer**: all direct Firestore document access goes through `app/repos/`. The `firestore.py` service composes repos — don't bypass it in routers.

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

`cloudbuild.yaml` runs on push to `master`: lint → Docker build → push to Artifact Registry → Firestore index deploy → deploy backend to Cloud Run (`australia-southeast1`) → build + deploy frame-extractor Cloud Run Job (`jobs/frame_extractor/`).

## Additional Docs

- `GEMINI.md` — Gemini/Vertex AI setup, prompt engineering, schema strategies
- `FRONTEND_AUTH_INTEGRATION.md` — Firebase Client SDK setup and WebSocket auth patterns

---

## Frontend (shiftready-ui)

Next.js 16.2.4 · React 19 · TypeScript · TanStack Query v5 · Tailwind v4 · lucide-react · clsx · tailwind-merge · Firebase 12 · MediaPipe tasks-vision · Radix UI · react-hook-form + zod · sonner

### Directory Structure

```
src/
├── app/                              # Next.js App Router pages
│   ├── layout.tsx                    # Root layout: Providers + Sidebar + Header
│   ├── page.tsx                      # Home / public browse
│   ├── (auth)/                       # login, register
│   ├── (sellers)/                    # Authenticated seller routes
│   │   ├── create/page.tsx           # Legacy video upload + sale init
│   │   ├── dashboard/page.tsx        # Sales list
│   │   └── seller-central/
│   │       ├── page.tsx              # Seller hub
│   │       ├── capture/page.tsx      # Live capture (primary flow)
│   │       ├── live-stream/page.tsx  # Live stream
│   │       ├── create/page.tsx       # Upload entry
│   │       └── inventory/[eventId]/page.tsx  # Inventory review cockpit
│   └── (public)/
│       └── sale/[eventId]/page.tsx   # Public sale detail
├── components/
│   ├── providers.tsx                 # QueryClientProvider + ReactQueryDevtools
│   ├── ui/
│   │   ├── sidebar.tsx               # Fixed left nav (w-64), collapses on mobile
│   │   └── header.tsx                # Fixed top bar (h-16)
│   └── features/
│       ├── capture/                  # CaptureStage, CaptureBucket, ItemConfirmCard,
│       │                             # CapturePermissionsGate, CaptureControls, CaptureOverlay,
│       │                             # ItemReviewScreen, FinalizeCaptureDialog
│       ├── create/                   # upload-screen, processing-screen (batch+live modes),
│       │                             # video-uploader, how-to, step-header, upload-progress-bar
│       ├── inventory/                # inventory-card, card-pricing-grid, video-panel,
│       │                             # loading-overlay, bundle-section, inventory-actions,
│       │                             # AppendVideoModal
│       ├── seller-central/           # sale-row, bundle-card, item-card-v2, item-photo-strip
│       ├── dashboard/                # sale-card
│       └── marketplace/              # marketplace-item-card, bundle-card
├── hooks/
│   ├── use-auth.ts
│   ├── use-sales.ts
│   ├── use-upload.ts
│   ├── use-append-upload.ts
│   ├── use-websocket.ts
│   └── use-landing.ts
└── lib/
    ├── api.ts                        # Centralized fetch wrapper; all API calls live here
    ├── types.ts                      # InventoryItem, RoomBundle, SaleSummary interfaces
    ├── firebase.ts                   # Firebase client init
    ├── schemas.ts                    # Zod schemas
    ├── constants.ts
    ├── utils.ts                      # cn() = clsx + tailwind-merge
    └── capture/
        ├── mediapipe-loader.ts       # Lazy-load WASM, init ObjectDetector
        └── capture-types.ts          # CapturedItem, PendingDetection, CaptureToast, helpers
```

### Live Capture Flow (Primary)

1. `/seller-central/capture` → `CapturePermissionsGate` (camera required, mic optional)
2. `CaptureStage` — live `getUserMedia` feed + MediaPipe ObjectDetector (WASM, on-device, ~5MB lazy-loaded)
3. Per detection: `ItemConfirmCard` prompt → user confirms → `captureFrame(eventId, file)` → `POST /capture/frame` → Gemini single-frame → `name/brand/price/gcs_uri` stored on `CapturedItem`
4. "Finish" → `ItemReviewScreen` → review/remove items → "Upload & Process"
5. `handleProcess()` → `finalizeCaptureV2(eventId, analyzedItems)` → `POST /capture/finalize-v2`
6. `ProcessingScreen` with `mode="live"` — shows real items with `frameSrc` thumbnails + "Pricing…" status
7. Polls `getStatus()` every 3s → redirects to `/seller-central/inventory/${eventId}`

### ProcessingScreen Modes

- `mode="batch"` (default): animated fake item ticker + animated orb; used for video upload where items aren't known yet
- `mode="live"`: real `capturedItems` shown with `frameSrc` thumbnails, names, brands, pricing status; no fake ticker

### Adding a New Page

1. Create `src/app/<route>/page.tsx` (App Router — no `pages/` directory).
2. Add API calls to `src/lib/api.ts` following the existing pattern.
3. Add TypeScript types to `src/lib/types.ts`.
4. Create a hook in `src/hooks/` using TanStack Query if the page needs data fetching.

### API Client (`src/lib/api.ts`)

- Base URL from `NEXT_PUBLIC_API_URL`; falls back to the Cloud Run URL.
- Module-level `_idToken` set by AuthProvider; auto-injected into all requests.
- Central `apiRequest<T>()` wrapper handles errors (parses FastAPI's `detail` field) and 204 No Content.
- All paths follow: `` `${API_BASE}/sales/${eventId}/...` ``

### TanStack Query Conventions

- `QueryClient` instantiated once in `providers.tsx` with default config.
- Polling conditional — 1500 ms only during `processing` or `pricing_in_progress` states.
- All mutations call `queryClient.invalidateQueries` on success.
- `staleTime: 5 * 60 * 1000` for data that doesn't change during AI processing.

### Design System

- **Dark-only** — `<html className="dark">` hardcoded; no light mode.
- **Tailwind v4** — config in `src/app/globals.css` via `@theme {}`, not `tailwind.config.js`.
- **Layout**: main content has `pl-64` (sidebar) + `pt-16` (header) — don't override on new pages.
- **Key CSS variables**:
  - `bg-surface`, `bg-surface-container-low/high/lowest/highest`
  - `text-on-surface`, `text-on-surface-variant`
  - `text-primary` (#adc6ff electric blue), `text-tertiary` (#4edea3 green for pricing)
  - `border-outline`, `border-outline-variant`
- **Icons**: lucide-react only — do not introduce other icon libraries.
- **Class merging**: `cn()` from `lib/utils.ts` (clsx + tailwind-merge) for conditional classes.

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
