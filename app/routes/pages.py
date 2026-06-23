"""HTML page routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .. import services
from ..db import get_session
from ..templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)):
    data = services.home_view(session)
    return templates.TemplateResponse(request, "home.html", {"title": "Home", **data})


@router.get("/story/{slug}", response_class=HTMLResponse)
def story(slug: str, request: Request, session: Session = Depends(get_session)):
    story = services.get_story(session, slug)
    if story is None:
        return templates.TemplateResponse(
            request, "not_found.html", {"title": "Not found", "what": "story"}, status_code=404
        )
    data = services.story_view(session, story)
    return templates.TemplateResponse(request, "story.html", {"title": story.title, **data})


@router.get("/outlet/{name}", response_class=HTMLResponse)
def outlet(name: str, request: Request, session: Session = Depends(get_session)):
    data = services.outlet_view(session, name)
    if data is None:
        return templates.TemplateResponse(
            request, "not_found.html", {"title": "Not found", "what": "outlet"}, status_code=404
        )
    return templates.TemplateResponse(request, "outlet.html", {"title": data["name"], "card": data})


@router.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {"title": "Methodology"})
