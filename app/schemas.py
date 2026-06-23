"""Lightweight view-model schemas (optional typing helpers)."""
from __future__ import annotations

from pydantic import BaseModel


class StoryCard(BaseModel):
    slug: str
    title: str
    summary: str
    sources: int
    disputed: int
    confidence_score: int


class ConfidenceBreakdown(BaseModel):
    key: str
    value: float
    weight: int
    note: str
