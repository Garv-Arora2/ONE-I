"""View-model assembly: turn DB rows + analysis into template-ready dicts."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import analysis
from .models import Article, Comment, Outlet, Story, Vote

POLL_QUESTIONS = [
    {
        "key": "completeness",
        "prompt": "Did this coverage feel complete?",
        "hint": "Were major angles and updates included?",
        "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}],
    },
    {
        "key": "trust",
        "prompt": "How trustworthy was the overall coverage?",
        "hint": "Your gut check on source quality",
        "options": [{"value": str(i), "label": str(i)} for i in range(1, 6)],
    },
    {
        "key": "informed",
        "prompt": "How informed do you feel after reading this?",
        "hint": "Did you learn what you needed?",
        "options": [{"value": str(i), "label": str(i)} for i in range(1, 6)],
    },
    {
        "key": "framing_fair",
        "prompt": "Was the framing across outlets fair?",
        "hint": "Balance of positive vs negative language",
        "options": [{"value": str(i), "label": str(i)} for i in range(1, 6)],
    },
    {
        "key": "facts_clear",
        "prompt": "Were the core facts clear?",
        "hint": "Could you tell what actually happened?",
        "options": [{"value": str(i), "label": str(i)} for i in range(1, 6)],
    },
    {
        "key": "missing_angles",
        "prompt": "Did coverage miss important angles?",
        "hint": "No = good (few gaps)",
        "options": [{"value": "yes", "label": "Yes, gaps"}, {"value": "no", "label": "No, solid"}],
    },
    {
        "key": "would_recommend",
        "prompt": "Would you recommend this coverage to someone?",
        "hint": "Share-worthiness",
        "options": [{"value": str(i), "label": str(i)} for i in range(1, 6)],
    },
    {
        "key": "numbers_confidence",
        "prompt": "How confident are you in the reported numbers?",
        "hint": "Casualties, counts, poll margins, etc.",
        "options": [{"value": str(i), "label": str(i)} for i in range(1, 6)],
    },
]


def _vote_tally(session: Session, story_id: int) -> dict[str, dict[str, int]]:
    rows = session.execute(
        select(Vote.question_key, Vote.choice, func.count())
        .where(Vote.story_id == story_id)
        .group_by(Vote.question_key, Vote.choice)
    ).all()
    tally: dict[str, dict[str, int]] = {}
    for key, choice, count in rows:
        tally.setdefault(key, {})[choice] = count
    return tally


def get_story(session: Session, slug: str) -> Story | None:
    return session.scalar(
        select(Story)
        .where(Story.slug == slug)
        .options(selectinload(Story.articles).selectinload(Article.outlet))
    )


def poll_results(session: Session, story: Story, selected: dict[str, str] | None = None) -> dict:
    tally = _vote_tally(session, story.id)
    community = analysis.poll_community_score(tally)
    results = []
    for q in POLL_QUESTIONS:
        counts = tally.get(q["key"], {})
        total = sum(counts.values())
        opts = [
            {
                "value": o["value"],
                "label": o["label"],
                "count": counts.get(o["value"], 0),
                "pct": round(counts.get(o["value"], 0) / total * 100) if total else 0,
                "selected": selected and selected.get(q["key"]) == o["value"],
            }
            for o in q["options"]
        ]
        results.append({
            "key": q["key"],
            "prompt": q["prompt"],
            "hint": q.get("hint", ""),
            "poll_style": "yesno" if len(q["options"]) == 2 and q["options"][0]["value"] in ("yes", "no") else "scale",
            "options": opts,
            "total": total,
        })
    return {"results": results, "community": community}


def _build_card(story: Story, session: Session) -> dict:
    articles = story.articles
    disputed = analysis.disputed_facts(articles)
    loaded = analysis.loaded_terms_scan(articles)
    crux = analysis.crux_points(articles)
    narrative = analysis.narrative_split(articles, loaded)
    landscape = analysis.consensus_landscape(articles, crux=crux, disputed=disputed, narrative=narrative)
    tally = _vote_tally(session, story.id)
    poll = analysis.poll_community_score(tally)
    conf = analysis.coverage_confidence(
        articles, disputed=disputed, loaded=loaded, crux=crux, poll_score=poll["score"]
    )
    return {
        "slug": story.slug,
        "title": story.title,
        "summary": story.summary,
        "image_url": story.image_url,
        "sources": len(articles),
        "disputed": disputed["count"],
        "crux_count": len(crux["majority"]),
        "confidence": conf,
        "stance": analysis.reporting_stance(articles, loaded),
        "bias": analysis.bias_spread(articles),
        "outlets": sorted({a.outlet.name for a in articles if a.outlet})[:8],
        "unresolved": len(landscape.get("contested", [])) + len(landscape.get("unknown", [])),
        "consensus_score": conf["score"],
        "updated_at": story.last_updated,
    }


def _what_happened(crux_highlight: dict, landscape: dict) -> list[dict]:
    bullets: list[dict] = []
    for p in crux_highlight.get("points", []):
        bullets.append({"text": p["claim"], "status": "agreed"})
    elif_headline = crux_highlight.get("headline")
    if not bullets and crux_highlight.get("has_crux") and elif_headline:
        bullets.append({"text": elif_headline.rstrip("."), "status": "agreed"})
    for item in landscape.get("contested", [])[:3]:
        bullets.append({"text": item["claim"], "status": "disputed"})
    for item in landscape.get("unknown", [])[:2]:
        bullets.append({"text": item["claim"], "status": "unknown"})
    return bullets[:7]


def home_view(session: Session) -> dict:
    stories = list(session.scalars(
        select(Story).options(selectinload(Story.articles).selectinload(Article.outlet))
    ))
    cards = [_build_card(story, session) for story in stories]
    cards.sort(key=lambda c: c["confidence"]["score"], reverse=True)
    hero = cards[0] if cards else None
    feed = cards[1:] if len(cards) > 1 else []
    return {"cards": cards, "hero": hero, "feed": feed, "story_count": len(stories)}


def story_view(session: Session, story: Story) -> dict:
    articles = sorted(story.articles, key=lambda a: a.published_at)

    disputed = analysis.disputed_facts(articles)
    loaded = analysis.loaded_terms_scan(articles)
    crux = analysis.crux_points(articles)
    narrative = analysis.narrative_split(articles, loaded)
    landscape = analysis.consensus_landscape(articles, crux=crux, disputed=disputed, narrative=narrative)
    crux_highlight = analysis.crux_highlight(landscape, crux=crux)
    tally = _vote_tally(session, story.id)
    poll = analysis.poll_community_score(tally)
    confidence = analysis.coverage_confidence(
        articles, disputed=disputed, loaded=loaded, crux=crux, poll_score=poll["score"]
    )
    stance = analysis.reporting_stance(articles, loaded)
    bias = analysis.bias_spread(articles)
    missing = analysis.missing_coverage(articles)
    outlet_scores = analysis.outlet_story_scores(
        articles, crux=crux, loaded=loaded, disputed=disputed, poll_score=poll["score"]
    )

    comments = list(session.scalars(select(Comment).where(Comment.story_id == story.id)))
    reactions = analysis.public_reaction_top_statements(comments)

    timeline: dict[str, list[dict]] = {}
    score_by_outlet = {s["outlet"]: s for s in outlet_scores}
    for art in articles:
        name = art.outlet.name if art.outlet else "Unknown"
        day = art.published_at.strftime("%Y-%m-%d")
        timeline.setdefault(day, []).append({
            "outlet": name,
            "tone": score_by_outlet.get(name, {}).get("tone", "majority"),
            "headline": art.headline,
            "url": art.url,
        })
    timeline_days = [
        {"day": day, "entries": items} for day, items in sorted(timeline.items())
    ]

    outlets = sorted({a.outlet.name for a in articles if a.outlet})
    what_happened = _what_happened(crux_highlight, landscape)
    word_count = len(story.summary.split()) + sum(len(a.headline.split()) for a in articles)
    reading_mins = max(2, min(8, word_count // 180))

    return {
        "story": story,
        "confidence": confidence,
        "stance": stance,
        "bias": bias,
        "crux": crux,
        "landscape": landscape,
        "crux_highlight": crux_highlight,
        "narrative": narrative,
        "disputed": disputed,
        "loaded": loaded,
        "missing": missing,
        "timeline": timeline_days,
        "outlet_scores": outlet_scores,
        "reactions": reactions,
        "polls": poll_results(session, story)["results"],
        "poll_community": poll,
        "source_count": len(articles),
        "outlets": outlets[:10],
        "what_happened": what_happened,
        "reading_mins": reading_mins,
        "articles": [
            {
                "outlet": a.outlet.name if a.outlet else "Unknown",
                "lean": a.outlet.lean if a.outlet else "center",
                "headline": a.headline,
                "url": a.url,
                "published_at": a.published_at,
            }
            for a in articles
        ],
    }


def outlet_view(session: Session, name: str) -> dict | None:
    outlet = session.scalar(select(Outlet).where(Outlet.name.ilike(name)))
    if outlet is None:
        return None
    card = analysis.outlet_report_card(session, outlet)
    covered = list(session.scalars(
        select(Story).where(Story.id.in_(card["covered_story_ids"]))
    )) if card["covered_story_ids"] else []
    card["covered_stories"] = [{"slug": s.slug, "title": s.title} for s in covered]
    return card
