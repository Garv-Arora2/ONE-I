"""Shared Jinja2 environment with custom filters and globals."""
from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from .config import settings

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def confidence_color(score: int) -> str:
    if score >= 60:
        return "text-consensus"
    if score >= 40:
        return "text-dispute"
    return "text-conflict"


def confidence_ring(score: int) -> str:
    if score >= 60:
        return "#1E9E62"
    if score >= 40:
        return "#F4A621"
    return "#D64545"


def fmt_date(value) -> str:
    try:
        return value.strftime("%b %d, %Y")
    except Exception:  # noqa: BLE001
        return ""


def fmt_num(value) -> str:
    try:
        return f"{int(value):,}"
    except Exception:  # noqa: BLE001
        return str(value)


templates.env.filters["fmt_date"] = fmt_date
templates.env.filters["fmt_num"] = fmt_num
templates.env.globals.update(
    app_name=settings.app_name,
    tagline=settings.tagline,
    confidence_color=confidence_color,
    confidence_ring=confidence_ring,
    lean_seg={
        "left": "bg-blue-600",
        "lean-left": "bg-sky-400",
        "center": "bg-slate-400",
        "lean-right": "bg-orange-400",
        "right": "bg-red-600",
    },
)
