"""Data ingestion: seed from bundled JSON, optional live refresh from GNews/Reddit.

The bundled JSON files are the source of truth. The app seeds the database from
them on startup so it always runs fully offline. Live refresh scripts rewrite the
JSON files; they never write to the database directly.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Article, Comment, Outlet, Story

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
OUTLET_BIAS_FILE = DATA_DIR / "outlet_bias.json"
SEED_STORIES_FILE = DATA_DIR / "seed_stories.json"
SEED_REACTIONS_FILE = DATA_DIR / "seed_reactions.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        logger.warning("Data file missing: %s", path)
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow()


def _load_outlets(session: Session) -> dict:
    """Upsert outlets from outlet_bias.json. Returns the fallback config dict."""
    data = _load_json(OUTLET_BIAS_FILE)
    fallback = data.get("fallback", {
        "name": "Unknown Source", "domain": "", "lean": "center",
        "lean_score": 0, "reliability": 0.5, "known": False,
    })
    for entry in data.get("outlets", []):
        existing = session.scalar(select(Outlet).where(Outlet.name == entry["name"]))
        if existing is None:
            session.add(Outlet(
                name=entry["name"],
                domain=entry.get("domain", ""),
                lean=entry.get("lean", "center"),
                lean_score=entry.get("lean_score", 0),
                reliability=entry.get("reliability", 0.5),
                known=entry.get("known", True),
            ))
        else:
            existing.domain = entry.get("domain", existing.domain)
            existing.lean = entry.get("lean", existing.lean)
            existing.lean_score = entry.get("lean_score", existing.lean_score)
            existing.reliability = entry.get("reliability", existing.reliability)
            existing.known = entry.get("known", existing.known)
    session.flush()
    return fallback


def _resolve_outlet(session: Session, name: str, fallback: dict) -> Outlet:
    """Find an outlet by name (case-insensitive), else create an unrated one."""
    name = (name or "").strip() or fallback["name"]
    outlet = session.scalar(select(Outlet).where(Outlet.name.ilike(name)))
    if outlet is not None:
        return outlet
    outlet = Outlet(
        name=name,
        domain="",
        lean=fallback.get("lean", "center"),
        lean_score=fallback.get("lean_score", 0),
        reliability=fallback.get("reliability", 0.5),
        known=False,
    )
    session.add(outlet)
    session.flush()
    return outlet


def _seed_stories(session: Session, fallback: dict) -> None:
    data = _load_json(SEED_STORIES_FILE)
    for entry in data.get("stories", []):
        story = session.scalar(select(Story).where(Story.slug == entry["slug"]))
        if story is None:
            story = Story(slug=entry["slug"])
            session.add(story)
        story.title = entry.get("title", entry["slug"])
        story.topic_query = entry.get("topic_query", "")
        story.summary = entry.get("summary", "")
        story.image_url = entry.get("image_url")
        story.last_updated = datetime.utcnow()
        session.flush()

        existing_by_url = {a.url: a for a in story.articles}
        for art in entry.get("articles", []):
            url = art.get("url", "")
            outlet = _resolve_outlet(session, art.get("outlet", ""), fallback)
            if url in existing_by_url:
                row = existing_by_url[url]
                row.headline = art.get("headline", row.headline)
                row.description = art.get("description", row.description)
                row.published_at = _parse_dt(art.get("published_at")) or row.published_at
                row.image_url = art.get("image_url", row.image_url)
                continue
            session.add(Article(
                story_id=story.id,
                outlet_id=outlet.id,
                url=url,
                headline=art.get("headline", ""),
                description=art.get("description", ""),
                published_at=_parse_dt(art.get("published_at")),
                image_url=art.get("image_url"),
            ))
    session.flush()


def _seed_reactions(session: Session) -> None:
    data = _load_json(SEED_REACTIONS_FILE)
    for entry in data.get("reactions", []):
        story = session.scalar(select(Story).where(Story.slug == entry["story_slug"]))
        if story is None:
            continue
        existing = {(c.body, c.score) for c in story.comments}
        for c in entry.get("comments", []):
            key = (c.get("body", ""), c.get("score", 0))
            if key in existing:
                continue
            session.add(Comment(
                story_id=story.id,
                source=c.get("source", "reddit"),
                author=c.get("author", "redditor"),
                body=c.get("body", ""),
                score=c.get("score", 0),
                permalink=c.get("permalink", ""),
                subreddit=c.get("subreddit"),
            ))
    session.flush()


def seed_from_json(session: Session | None = None) -> None:
    """Idempotently load outlets, stories, articles and comments from JSON."""
    own_session = session is None
    session = session or SessionLocal()
    try:
        fallback = _load_outlets(session)
        _seed_stories(session, fallback)
        _seed_reactions(session)
        session.commit()
        logger.info("Seed complete.")
    except Exception:  # pragma: no cover - defensive
        session.rollback()
        logger.exception("Seeding failed")
        raise
    finally:
        if own_session:
            session.close()


def database_is_empty() -> bool:
    session = SessionLocal()
    try:
        return session.scalar(select(Story).limit(1)) is None
    finally:
        session.close()
