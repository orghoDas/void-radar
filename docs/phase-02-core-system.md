# Void Radar Phase 2 Core System

Phase 2 creates the project skeleton, backend API foundation, configuration
pattern, and canonical database schema foundation.

## Structure

```text
void-radar/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── domain/
│   │   └── models/
│   └── tests/
├── apify/
│   ├── yc-company-discovery/
│   └── company-researcher/
├── database/
│   └── migrations/
├── frontend/
│   └── void-radar/
├── workflows/
│   └── n8n/
└── docs/
```

## Backend

The backend starts as a FastAPI service with:

- `/health` endpoint
- environment-based settings
- PostgreSQL connection helper
- shared domain constants for service types, prospect types, evidence kinds, and
  scoring weights

Run locally after installing dependencies:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Database

The first migration defines the canonical persistence contract for:

- companies
- founders
- company founders
- company aliases
- sources
- source records
- research runs
- observations
- signals
- opportunities
- scores
- contacts
- outreach
- feedback

The schema preserves provenance and separates source facts, observations,
inferences, recommendations, signals, opportunities, and scores.

## Configuration

Copy `.env.example` to `.env` locally and fill in real secrets. Keep provider
keys server-side only.

Required before running the backend:

```text
DATABASE_URL
```

Required by later phases:

```text
APIFY_TOKEN
OPENAI_API_KEY
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

## Acceptance Criteria

Phase 2 is complete when:

- The repo has the intended top-level folders.
- The backend can expose a health endpoint once dependencies are installed.
- Database migration `0001_core_schema.sql` captures the core data model.
- External service secrets are represented only as environment variables.
- Apify, frontend, and n8n have clear placeholder boundaries for later phases.

