# ONE-I Data Pipeline

## 1) Collection

Data enters the system from two paths:

- **Bundled offline dataset** in `app/data/*.json`
- **Optional live refresh scripts**:
  - `scripts/refresh_news.py` (GNews; requires `GNEWS_API_KEY`)
  - `scripts/refresh_rss.py` (RSS feeds)
  - `scripts/refresh_reactions.py` (reaction/comment refresh)
  - `scripts/refresh_all.py` (orchestrates merge + reseed)

The refresh process writes updated records back into `app/data/seed_stories.json` and `app/data/seed_reactions.json`.

## 2) Normalization

`app/ingest.py` loads JSON and upserts normalized relational entities:

- `Outlet`
- `Story`
- `Article`
- `Comment`

Important normalization details:

- Outlet metadata is sourced from `outlet_bias.json` with fallback values for unknown sources.
- Articles are deduplicated per story by URL.
- Datetime values are normalized via ISO parsing with fallback to current UTC time.

## 3) Analysis

`app/analysis.py` computes story-level and outlet-level metrics used by pages and API partials.

Main stages:

- Sentence extraction from headlines/descriptions
- TF-IDF vectorization and cosine similarity clustering
- Consensus/split classification based on outlet support ratio
- Numeric mismatch detection for disputed facts
- Loaded-term scan for framing divergence
- Coverage confidence scoring and confidence breakdown

## 4) Storage

Default storage is a local SQLite file (`clarity.db`).

- Engine and session setup: `app/db.py`
- Table creation on startup: `init_db()`
- Idempotent reseed: `seed_from_json()`

## 5) Retrieval

Data retrieval is split between:

- **Page routes** in `app/routes/pages.py` for full-page renders
- **API/HTMX routes** in `app/routes/api.py` for incremental updates

Service composition in `app/services.py` acts as the contract between persistence/analysis and templates.

## Scheduling and Background Execution

`app/scheduler.py` can run `refresh_all.py` on an interval via APScheduler when enabled.

- Controlled by:
  - `ENABLE_SCHEDULER`
  - `INGEST_INTERVAL_HOURS`
- Failures are logged and do not terminate the web server process.
