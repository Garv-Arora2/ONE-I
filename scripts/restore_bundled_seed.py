"""Restore offline demo seed_stories.json from bundled rich samples.

Usage: python scripts/restore_bundled_seed.py
Then:  python scripts/reseed.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
DEMO = DATA / "demo_rich"
OUT = DATA / "seed_stories.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    stories = [_load(DEMO / "israel-iran-strike-2026.json")]
    for name in (
        "us-election-poll-shift-2026.json",
        "fed-holds-rates-2026.json",
        "eu-ai-act-enforcement-2026.json",
        "cop-climate-summit-2026.json",
    ):
        path = DEMO / name
        if path.exists():
            stories.append(_load(path))

    payload = {
        "_note": "Bundled offline demo dataset. Restore via scripts/restore_bundled_seed.py",
        "stories": stories,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Restored {len(stories)} stories to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
