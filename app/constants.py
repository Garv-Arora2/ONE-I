"""Shared constants for ingestion and analysis."""
from __future__ import annotations

# High-reach outlets we expect to cover a major story. Used by the
# Missing Coverage detector.
EXPECTED_MAJOR_OUTLETS: list[str] = [
    "Reuters",
    "Associated Press",
    "BBC",
    "CNN",
    "The New York Times",
    "The Washington Post",
    "Al Jazeera",
    "Fox News",
    "Bloomberg",
    "The Guardian",
]

# Predefined topic queries -> deterministic story clusters.
# (slug, title, query)
TOPIC_QUERIES: list[tuple[str, str, str]] = [
    ("israel-iran-strike-2026", "Israel-Iran Strike Exchange", "Israel Iran strike"),
    ("us-election-poll-shift-2026", "US Midterm Polls Tighten", "US midterm election polls"),
    ("fed-holds-rates-2026", "Federal Reserve Holds Interest Rates", "Federal Reserve interest rate decision"),
    ("eu-ai-act-enforcement-2026", "EU Begins Enforcing AI Act", "EU AI Act enforcement"),
    ("cop-climate-summit-2026", "Global Climate Summit Reaches Deal", "climate summit agreement"),
    ("oil-prices-surge-2026", "Oil Prices Surge on Supply Fears", "oil prices supply"),
    ("supreme-court-ruling-2026", "Supreme Court Issues Major Ruling", "supreme court ruling decision"),
    ("global-migration-2026", "Migration Policy Sparks Debate", "migration border policy"),
    ("health-outbreak-2026", "Health Agencies Track New Outbreak", "disease outbreak health agency"),
    ("ai-policy-summit-2026", "Nations Meet on AI Safety", "AI safety summit regulation"),
]

# Context keywords used to label extracted numbers in disputed-fact detection.
# Deliberately excludes generic words like "people" and noisy units like
# "percent"/"dollars" that mix unrelated quantities and create false disputes.
FACT_KEYWORDS: list[str] = [
    "killed",
    "dead",
    "deaths",
    "casualties",
    "wounded",
    "injured",
    "missiles",
    "rockets",
    "drones",
    "soldiers",
    "troops",
    "point",
    "points",
]

# Crux engine thresholds (TF-IDF sentence clustering).
SIM_THRESHOLD: float = 0.24
CRUX_MAJORITY_RATIO: float = 0.60
CRUX_SPLIT_MIN: float = 0.20

# Coverage confidence: community poll weight (small but visible impact).
POLL_CONFIDENCE_WEIGHT: float = 0.10

# Extra stopwords for outlet phrase extraction (on top of sklearn english list).
EXTRA_STOPWORDS: set[str] = {
    "said",
    "say",
    "says",
    "according",
    "reported",
    "report",
    "news",
    "told",
    "added",
    "new",
}

# Confidence label thresholds.
CONFIDENCE_LABELS = [
    (80, "High"),
    (60, "Moderate"),
    (40, "Mixed"),
    (0, "Low"),
]


def confidence_label(score: int) -> str:
    for threshold, label in CONFIDENCE_LABELS:
        if score >= threshold:
            return label
    return "Low"
