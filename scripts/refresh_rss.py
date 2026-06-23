"""Fetch articles from RSS feeds and match them to topic queries.

Usage:  python scripts/refresh_rss.py
No API key required. Returns a dict slug -> list[article dict].
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.constants import TOPIC_QUERIES  # noqa: E402

FEEDS_FILE = ROOT / "app" / "data" / "rss_feeds.json"

OUTLET_ALIASES = {
    "bbc news": "BBC",
    "cnn.com": "CNN",
    "the guardian": "The Guardian",
    "guardian": "The Guardian",
    "al jazeera english": "Al Jazeera",
    "al jazeera – breaking news, world news and video from al jazeera": "Al Jazeera",
    "world news | the guardian": "The Guardian",
    "bloomberg politics": "Bloomberg",
    "ap news": "Associated Press",
    "associated press": "Associated Press",
    "fox news": "Fox News",
    "npr": "NPR",
    "reuters": "Reuters",
    "bloomberg": "Bloomberg",
}


def _normalize_outlet(name: str, fallback: str) -> str:
    key = (name or fallback or "Unknown").strip().lower()
    return OUTLET_ALIASES.get(key, name or fallback or "Unknown")


def _parse_published(entry: dict) -> str:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            return parsedate_to_datetime(raw).isoformat()
        except (TypeError, ValueError):
            pass
    return datetime.utcnow().isoformat()


def _story_text(entry: dict) -> str:
    title = entry.get("title", "") or ""
    summary = entry.get("summary", "") or entry.get("description", "") or ""
    summary = re.sub(r"<[^>]+>", " ", summary)
    return f"{title} {summary}".lower()


def _matches_query(text: str, query: str) -> bool:
    terms = [t for t in re.split(r"\s+", query.lower()) if len(t) > 2]
    if not terms:
        return False
    hits = sum(1 for t in terms if t in text)
    return hits >= min(2, len(terms))


def _fetch_feed(client: httpx.Client, outlet: str, url: str) -> list[dict]:
    try:
        resp = client.get(url, timeout=25, follow_redirects=True)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for entry in parsed.entries[:30]:
        link = entry.get("link") or ""
        if not link:
            continue
        rows.append({
            "outlet": _normalize_outlet(parsed.feed.get("title", ""), outlet),
            "url": link,
            "headline": (entry.get("title") or "").strip(),
            "description": re.sub(r"<[^>]+>", " ", entry.get("summary", "") or "").strip()[:500],
            "published_at": _parse_published(entry),
            "image_url": None,
            "_text": _story_text(entry),
        })
    return rows


def fetch_rss_by_topic(max_per_story: int = 8) -> dict[str, list[dict]]:
    data = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    all_entries: list[dict] = []
    headers = {"User-Agent": "one-i-news-intel/0.1 (RSS refresh)"}
    with httpx.Client(headers=headers) as client:
        for feed in data.get("feeds", []):
            rows = _fetch_feed(client, feed.get("outlet", "Unknown"), feed["url"])
            all_entries.extend(rows)

    by_slug: dict[str, list[dict]] = {slug: [] for slug, _, _ in TOPIC_QUERIES}
    seen_urls: set[str] = set()

    for slug, _title, query in TOPIC_QUERIES:
        matched = [e for e in all_entries if _matches_query(e["_text"], query)]
        matched.sort(key=lambda e: e.get("published_at", ""), reverse=True)
        for row in matched:
            url = row["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            clean = {k: v for k, v in row.items() if k != "_text"}
            by_slug[slug].append(clean)
            if len(by_slug[slug]) >= max_per_story:
                break
    return by_slug


def main() -> int:
    counts = fetch_rss_by_topic()
    total = sum(len(v) for v in counts.values())
    for slug, arts in counts.items():
        if arts:
            print(f"  + RSS {slug}: {len(arts)} articles")
    print(f"RSS fetched {total} articles across topics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
