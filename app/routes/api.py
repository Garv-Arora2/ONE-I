"""JSON + HTMX partial routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from .. import services
from ..db import get_session
from ..models import Vote
from ..templating import templates

router = APIRouter()

VALID_QUESTIONS = {q["key"] for q in services.POLL_QUESTIONS}


@router.get("/api/health")
def health():
    return JSONResponse({"status": "ok"})


@router.post("/api/story/{slug}/vote", response_class=HTMLResponse)
def vote(
    slug: str,
    request: Request,
    question_key: str = Form(...),
    choice: str = Form(...),
    session: Session = Depends(get_session),
):
    story = services.get_story(session, slug)
    if story is None:
        return HTMLResponse("Story not found", status_code=404)
    if question_key in VALID_QUESTIONS and choice:
        session.add(Vote(story_id=story.id, question_key=question_key, choice=choice))
        session.commit()
    data = services.story_view(session, story)
    target = next((r for r in data["polls"] if r["key"] == question_key), None)
    if target is None:
        return HTMLResponse("", status_code=404)
    for opt in target["options"]:
        opt["selected"] = opt["value"] == choice
    return templates.TemplateResponse(
        request,
        "partials/vote_refresh.html",
        {
            "result": target,
            "selected": choice,
            "confidence": data["confidence"],
        },
    )


@router.get("/api/story/{slug}/source/{point_id}", response_class=HTMLResponse)
def source_explorer(
    slug: str, point_id: int, request: Request, session: Session = Depends(get_session)
):
    story = services.get_story(session, slug)
    if story is None:
        return HTMLResponse("Story not found", status_code=404)
    data = services.story_view(session, story)
    pool = data["crux"]["majority"] + data["crux"]["split"]
    point = next((p for p in pool if p["id"] == point_id), None)
    if point is None:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(
        request, "partials/source_explorer.html", {"point": point}
    )
