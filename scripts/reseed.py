"""Reload bundled JSON into the database (updates headlines/descriptions in place).

Usage:  python scripts/reseed.py

Use this after editing seed_stories.json — no API keys required.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import init_db  # noqa: E402
from app.ingest import seed_from_json  # noqa: E402


def main() -> int:
    init_db()
    seed_from_json()
    print("Reseed complete. Restart the server if it is already running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
