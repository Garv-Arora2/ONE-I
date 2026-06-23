"""Optional: refresh seed_stories.json from the GNews API.

Usage:  python scripts/refresh_news.py
Requires the GNEWS_API_KEY environment variable. If it is missing the script
exits cleanly without touching the bundled data, so the offline demo is never
broken.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.constants import TOPIC_QUERIES  # noqa: E402

OUTPUT = ROOT / "app" / "data" / "seed_stories.json"
GNEWS_URL = "https://gnews.io/api/v4/search"


def fetch_topic(client: httpx.Client, query: str, max_results: int = 10) -> list[dict]:
    params = {"q": query, "lang": "en", "max": max_results, "apikey": settings.gnews_api_key}
    resp = client.get(GNEWS_URL, params=params, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    articles = []
    for item in payload.get("articles", []):
        source = (item.get("source") or {}).get("name") or "Unknown Source"
        articles.append({
            "outlet": source,
            "url": item.get("url", ""),
            "headline": item.get("title", ""),
            "description": item.get("description", "") or "",
            "published_at": item.get("publishedAt", ""),
            "image_url": item.get("image"),
        })
    return articles


def main() -> int:
    if not settings.gnews_api_key:
        print("GNEWS_API_KEY not set. Skipping refresh; bundled data left unchanged.")
        return 0

    stories = []
    with httpx.Client() as client:
        for slug, title, query in TOPIC_QUERIES:
            try:
                articles = fetch_topic(client, query)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! failed to fetch '{query}': {exc}")
                continue
            if not articles:
                continue
            stories.append({
                "slug": slug,
                "title": title,
                "topic_query": query,
                "summary": f"Latest coverage on: {title}.",
                "image_url": articles[0].get("image_url"),
                "articles": articles,
            })
            print(f"  + {slug}: {len(articles)} articles")

    if not stories:
        print("No stories fetched; leaving existing data untouched.")
        return 0

    OUTPUT.write_text(
        json.dumps({"_note": "Refreshed from GNews.", "stories": stories}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(stories)} stories to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
