"""Fetch from GNews + RSS, merge, refresh reactions, reseed database.

Usage:  python scripts/refresh_all.py

GNews is optional (GNEWS_API_KEY). RSS always runs (no key).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.constants import TOPIC_QUERIES  # noqa: E402
from app.ingest import seed_from_json  # noqa: E402

OUTPUT = ROOT / "app" / "data" / "seed_stories.json"


def _merge_articles(*groups: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for art in group:
            url = art.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(art)
    return merged[:14]


def _fetch_gnews() -> dict[str, list[dict]]:
    if not settings.gnews_api_key:
        print("GNEWS_API_KEY not set — skipping GNews (RSS still runs).")
        return {}
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "refresh_news", ROOT / "scripts" / "refresh_news.py"
    )
    refresh_news = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(refresh_news)

    import httpx

    out: dict[str, list[dict]] = {}
    with httpx.Client() as client:
        for slug, _title, query in TOPIC_QUERIES:
            try:
                arts = refresh_news.fetch_topic(client, query)
                if arts:
                    out[slug] = arts
                    print(f"  + GNews {slug}: {len(arts)} articles")
            except Exception as exc:  # noqa: BLE001
                print(f"  ! GNews failed '{query}': {exc}")
    return out


def main() -> int:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "refresh_rss", ROOT / "scripts" / "refresh_rss.py"
    )
    refresh_rss = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(refresh_rss)

    print("Fetching RSS...")
    rss = refresh_rss.fetch_rss_by_topic()
    print("Fetching GNews...")
    gnews = _fetch_gnews()

    stories = []
    for slug, title, query in TOPIC_QUERIES:
        articles = _merge_articles(gnews.get(slug, []), rss.get(slug, []))
        if not articles:
            continue
        stories.append({
            "slug": slug,
            "title": title,
            "topic_query": query,
            "summary": f"Live coverage cluster: {title}.",
            "image_url": articles[0].get("image_url"),
            "articles": articles,
        })
        print(f"  = {slug}: {len(articles)} merged articles")

    if not stories:
        print("No articles fetched; leaving existing seed_stories.json unchanged.")
        return 0

    # Keep bundled stories that had no live matches this run.
    if OUTPUT.exists():
        try:
            prior = json.loads(OUTPUT.read_text(encoding="utf-8"))
            live_slugs = {s["slug"] for s in stories}
            for entry in prior.get("stories", []):
                if entry["slug"] not in live_slugs:
                    stories.append(entry)
                    print(f"  ~ kept bundled story: {entry['slug']}")
        except json.JSONDecodeError:
            pass

    stories.sort(key=lambda s: s["slug"])
    OUTPUT.write_text(
        json.dumps({
            "_note": "Refreshed from GNews + RSS via scripts/refresh_all.py",
            "stories": stories,
        }, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(stories)} stories to {OUTPUT}")

    print("Refreshing Reddit reactions...")
    import subprocess
    subprocess.run([sys.executable, str(ROOT / "scripts" / "refresh_reactions.py")], check=False)

    print("Reseeding database...")
    seed_from_json()
    print("Done. Restart uvicorn if it is already running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
