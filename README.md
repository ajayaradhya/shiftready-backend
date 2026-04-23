# ShiftReady Backend | The Relocation Monolith

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-v0.100+-009688.svg)](https://fastapi.tiangolo.com/)
[![AI-Native](https://img.shields.io/badge/AI--Native-Gemini%203.1%20Flash%20Lite-7B1FA2.svg)](https://deepmind.google/technologies/gemini/)
[![Architecture](https://img.shields.io/badge/Architecture-Intelligent%20Monolith-orange.svg)](#architecture)

ShiftReady is an AI-enabled relocation and inventory management monolith designed to streamline residential transitions. It orchestrates a multi-stage pipeline from computer vision-based inventory extraction to market-aware pricing enabling users to bundle and sell household assets before their move-out deadline.

---

## Key Features

- **Temporal Vision Extraction**: Processes residential walkthrough videos using Gemini 3.1 Flash Lite with clock-time anchoring to identify assets and room bundles.
- **Urgency-Aware Pricing Engine**: Real-time Sydney market analysis (Waterloo/Zetland/Alexandria) that adjusts listing prices based on move-out deadlines.
- **State Machine Architecture**: A robust transition engine (Firestore-backed) managing sale lifecycles from `PENDING_UPLOAD` to `LIVE` and `ARCHIVED`.
- **Zero-Blink Polling**: Optimized polling endpoints for seamless UI transitions during intensive AI workloads.
- **Marketplace Sync**: Automated bundle-total recalculations and inventory synchronization across the cloud ledger.

---

## Tech Stack

- **Framework**: FastAPI (Asynchronous Python 3.11+)
- **Intelligence**: Gemini 3.1 Flash Lite (via Google GenAI Vertex AI SDK)
- **Database**: Google Cloud Firestore (NoSQL Hierarchical Storage)
- **Storage**: Google Cloud Storage (GCS)
- **Deployment**: Google Cloud Run (Containerized Monolith)

---

## Architecture: The Intelligent Monolith

The project follows a modular monolith pattern, isolating business logic (Services) from the interface (Routers) to ensure maintainability.

```mermaid
%%{init: {
  'theme': 'base',
  'themeVariables': {
    'primaryColor': '#BBDEFB',
    'primaryTextColor': '#0D47A1',
    'primaryBorderColor': '#1976D2',
    'lineColor': '#1976D2',
    'secondaryColor': '#E1BEE7',
    'tertiaryColor': '#FFE082',
    'noteBorderColor': '#FFA000',
    'noteBkgColor': '#FFF8E1'
  }
}%%}

graph TD
    %% --- EXTERNAL ACTORS & SERVICES ---
    subgraph External["2026 ShiftReady Ecosystem"]
        direction TB
        FE[("React Frontend<br/>(relocation-ui)")]
        GCS[("Google Cloud Storage (GCS)<br/>(Walkthrough Videos)")]
        Firestore[("Google Cloud Firestore<br/>(Hierarchical DB)")]
        Vertex[("Google Vertex AI<br/>(Gemini 3.1 Flash Lite)")]
    end

    %% --- THE MONOLITH ---
    subgraph Monolith["[The Monolith] ShiftReady Backend (FastAPI on Cloud Run)"]
        direction TB
        Main["app/main.py<br/>(CORS, Middleware, Init)"]

        %% Interface Layer
        subgraph Interface["1. The Interface (Routers)"]
            SR[("app/routers/sales.py<br/>(Endpoints & Orchestration)")]
        end

        %% Data Models & Contracts
        subgraph Models["2. The Contracts (Pydantic Models)"]
            direction LR
            Schemas[("app/models/schemas.py<br/>(API Requests/Responses)")]
            InvModels[("app/models/inventory.py<br/>(RoomBundle, ItemPrediction)")]
        end

        %% State Machine & Logic
        subgraph StateMachine["3. The Transition Engine"]
            StatusEnums[("SaleStatus Enum<br/>PENDING -> LIVE -> ARCHIVED")]
        end

        %% Business Logic Layer (Services)
        subgraph Services["4. Business Logic (Singletons)"]
            direction TB
            FS_Svc[("app/services/firestore.py<br/>(FirestoreService)")]
            Gem_Svc[("app/services/gemini.py<br/>(GeminiProcessor)")]
            GCS_Util[("app/utils/gcs.py<br/>(GCSUtils)")]
        end
    end

    %% --- FLOWS & INTERACTIONS ---

    %% Client Interactions
    FE == "1. POST /init" ==> Main
    Main --> SR
    FE == "2. PUT (Signed URL)" ==> GCS
    FE == "3. POST /{id}/process (Start Stage 1 AI)" ==> SR
    FE == "4. GET /{id}/status (Polling)" ==> SR
    FE == "5. POST /{id}/estimate (Start Stage 2 AI)" ==> SR

    %% Routers to Models (Serialization)
    SR -. "Uses" .-> Schemas
    SR -. "Uses" .-> InvModels

    %% Background Pipeline 1: AI Extraction
    SR == "Triggers<br/>Background Task" ==> E_Pipe("run_extraction_pipeline")
    E_Pipe == "A. Get videoUrl" ==> FS_Svc
    E_Pipe == "B. Analyze Video" ==> Gem_Svc
    E_Pipe == "C. Save RoomBundles & Items" ==> FS_Svc
    E_Pipe == "D. Transition Status<br/>(READY_FOR_REVIEW)" ==> StateMachine

    %% Background Pipeline 2: AI Pricing
    SR == "Triggers<br/>Background Task" ==> P_Pipe("run_pricing_pipeline")
    P_Pipe == "A. Get Full Summary" ==> FS_Svc
    P_Pipe == "B. Analyze Market (Sydney)" ==> Gem_Svc
    P_Pipe == "C. Save Predicted Prices & Reasoning" ==> FS_Svc
    P_Pipe == "D. Transition Status<br/>(READY_FOR_REVIEW)" ==> StateMachine

    %% Services to External GCP
    FS_Svc <== "Read/Write Inventory Hierarchy" ==> Firestore
    GCS_Util -. "Generate Signed URLs" .-> GCS
    Gem_Svc <== "Multimodal generation" ==> Vertex

    %% Pricing Grounding
    Gem_Svc <== "Grounds prices<br/>(google_search)" ==> GoogleSearch("Google Search Engine")

    %% --- STYLING ---
    %% Modifying node colors for clear visualization
    %% Interface Layer (Light Blue)
    style Main fill:#E3F2FD,stroke:#1976D2,stroke-width:2px;
    style SR fill:#E3F2FD,stroke:#1976D2,stroke-width:1px;
    
    %% Models Layer (Green)
    style Schemas fill:#E8F5E9,stroke:#2E7D32,stroke-width:1px;
    style InvModels fill:#E8F5E9,stroke:#2E7D32,stroke-width:1px;

    %% Services Layer (Purple)
    style FS_Svc fill:#F3E5F5,stroke:#7B1FA2,stroke-width:1px;
    style Gem_Svc fill:#F3E5F5,stroke:#7B1FA2,stroke-width:1px;
    style GCS_Util fill:#F3E5F5,stroke:#7B1FA2,stroke-width:1px;

    %% State Machine (Orange)
    style StateMachine fill:#FFF3E0,stroke:#EF6C00,stroke-width:1px;
    style StatusEnums fill:#FFF3E0,stroke:#EF6C00,stroke-width:1px;

    %% Pipelines (Dashed Border)
    style E_Pipe fill:#ECEFF1,stroke:#546E7A,stroke-width:1px,stroke-dasharray: 5 5;
    style P_Pipe fill:#ECEFF1,stroke:#546E7A,stroke-width:1px,stroke-dasharray: 5 5;

    %% External (Yellow)
    style External fill:#FFFDE7,stroke:#FBC02D,stroke-width:1px;
    style GCS fill:#FFFDE7,stroke:#FBC02D,stroke-width:1px;
    style Firestore fill:#FFFDE7,stroke:#FBC02D,stroke-width:1px;
    style Vertex fill:#FFFDE7,stroke:#FBC02D,stroke-width:1px;
```

## File Structure

```text
app/
├── models/         # Pydantic Schemas & Data Models
├── routers/        # FastAPI Route Handlers (Sales, Inventory, etc.)
├── services/       # Core Logic (Firestore, Gemini, GCS Utils)
├── utils/          # Shared Helpers (GCS Signers, Formatting)
└── main.py         # Entry point & Global Middleware
```

## 🔧 Local Setup

### 1. Prerequisites

- Python 3.11+
- Google Cloud CLI (`gcloud`) configured
- Firestore instance enabled in Native Mode

---

### 2. Clone & Environment

```bash
git clone <your-repo-url>
cd project-backend

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Environment Variables (.env)

Create a .env file in the root directory:

```env
GCP_PROJECT_ID=your-project-id
GCP_UPLOAD_BUCKET=your-gcs-bucket-name
GOOGLE_APPLICATION_CREDENTIALS=path/to/your/service-account.json
PORT=8000
```

### 4. Running the Project
Development Mode
```bash
uvicorn app.main:app --reload --port 8000
```

API Documentation

```text
Swagger UI: http://localhost:8000/docs

ReDoc: http://localhost:8000/redoc
```

## Sale Lifecycle (State Machine)

| Status                | Description                                               |
| --------------------- | --------------------------------------------------------- |
| `PENDING_UPLOAD`      | Sale initialized; waiting for GCS video upload.           |
| `PROCESSING`          | Gemini Vision is extracting items and bundles from video. |
| `READY_FOR_REVIEW`    | Inventory prepared for user verification.                 |
| `PRICING_IN_PROGRESS` | Gemini is analyzing market trends for valuation.          |
| `LIVE`                | Sale is public on the marketplace.                        |
| `ARCHIVED`            | Move complete; record frozen for history.                 |

## Testing the Pipelines

### Initialise a Sale

```curl
curl -X POST "http://localhost:8000/api/v1/sales/init" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user", "filename": "walkthrough.mp4"}'
```
### Trigger Pricing Analysis

```bash
curl -X POST "http://localhost:8000/api/v1/sales/{event_id}/estimate"
```

### License
Internal Proprietary - ShiftReady 2026
