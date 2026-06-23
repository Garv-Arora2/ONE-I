"""Optional: refresh seed_reactions.json with top Reddit comments per story.

Usage:  python scripts/refresh_reactions.py
Uses Reddit's public read-only JSON (no auth). On any failure it leaves the
bundled data untouched so the offline demo keeps working.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.constants import TOPIC_QUERIES  # noqa: E402

OUTPUT = ROOT / "app" / "data" / "seed_reactions.json"
SEARCH_URL = "https://www.reddit.com/search.json"


def find_thread(client: httpx.Client, query: str) -> str | None:
    resp = client.get(SEARCH_URL, params={"q": query, "sort": "relevance", "t": "month", "limit": 5})
    resp.raise_for_status()
    children = resp.json().get("data", {}).get("children", [])
    for child in children:
        permalink = child.get("data", {}).get("permalink")
        if permalink:
            return permalink
    return None


def fetch_comments(client: httpx.Client, permalink: str, limit: int = 12) -> list[dict]:
    resp = client.get(f"https://www.reddit.com{permalink}.json", params={"sort": "top", "limit": limit})
    resp.raise_for_status()
    data = resp.json()
    if len(data) < 2:
        return []
    comments = []
    for child in data[1].get("data", {}).get("children", []):
        cd = child.get("data", {})
        body = cd.get("body")
        if not body or cd.get("stickied"):
            continue
        comments.append({
            "source": "reddit",
            "author": "redditor",
            "body": body.strip(),
            "score": int(cd.get("score", 0)),
            "permalink": f"https://www.reddit.com{cd.get('permalink', '')}",
            "subreddit": cd.get("subreddit"),
        })
    comments.sort(key=lambda c: c["score"], reverse=True)
    return comments[:10]


def main() -> int:
    headers = {"User-Agent": settings.reddit_user_agent}
    reactions = []
    with httpx.Client(headers=headers, timeout=20) as client:
        for slug, _title, query in TOPIC_QUERIES:
            try:
                permalink = find_thread(client, query)
                if not permalink:
                    continue
                comments = fetch_comments(client, permalink)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! failed for '{query}': {exc}")
                continue
            if comments:
                reactions.append({"story_slug": slug, "comments": comments})
                print(f"  + {slug}: {len(comments)} comments")
            time.sleep(1)

    if not reactions:
        print("No comments fetched; leaving existing data untouched.")
        return 0

    OUTPUT.write_text(
        json.dumps({"_note": "Refreshed from Reddit.", "reactions": reactions}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote reactions for {len(reactions)} stories to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
