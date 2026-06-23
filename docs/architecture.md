# ONE-I Architecture

## Runtime Components

### FastAPI Web Application

- Entry point: `app/main.py`
- Registers page routes (`app/routes/pages.py`) and API routes (`app/routes/api.py`)
- Initializes database on startup and seeds from bundled JSON if empty
- Serves static assets from `app/static`
- Renders UI via Jinja templates in `app/templates`

### Analysis Layer

- Core analytics logic lives in `app/analysis.py`
- View assembly and route-facing composition lives in `app/services.py`
- Computations include:
  - Coverage confidence scoring
  - Consensus/split extraction (Crux points)
  - Disputed fact detection
  - Framing divergence detection
  - Narrative split and outlet-level scoring

### Data Access Layer

- SQLAlchemy models in `app/models.py`
- Session/engine setup in `app/db.py`
- Default database: SQLite (`clarity.db`)

### Ingestion and Refresh

- JSON-to-database seeding in `app/ingest.py`
- Script-driven refresh in `scripts/refresh_all.py`, `scripts/refresh_news.py`, `scripts/refresh_rss.py`, and `scripts/refresh_reactions.py`
- Optional periodic execution in `app/scheduler.py` via APScheduler

## Request Flow

1. Browser requests a page (`/`, `/story/{slug}`, `/outlet/{name}`).
2. Route handler calls service functions to fetch entities and compute analytics.
3. Templates render server-side HTML.
4. HTMX endpoints (`/api/story/{slug}/vote`, `/api/story/{slug}/source/{point_id}`) return partial HTML fragments for targeted updates.

## Data Boundaries

- Source-of-truth files for offline/demo mode:
  - `app/data/seed_stories.json`
  - `app/data/seed_reactions.json`
  - `app/data/outlet_bias.json`
- Refresh scripts update JSON files first, then trigger reseed.
- Application requests never write directly to external APIs.

## Operational Notes

- Scheduler is disabled by default (`ENABLE_SCHEDULER=false`).
- If refresh scripts fail, errors are logged and web serving continues.
- Health endpoint is available at `/api/health`.
