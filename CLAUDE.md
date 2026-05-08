# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ShiftReady Backend** is a FastAPI service that automates residential relocation inventory management using Google Gemini AI. It orchestrates a multi-stage pipeline: video intake → AI vision extraction → user review → AI pricing → marketplace publication.

Deployed on Cloud Run (Sydney region), with Firestore as the database and Firebase for authentication.

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
