"""Rule-based analysis engine for ONE-I.

All analysis is deterministic and runs offline. The Crux engine uses
classical NLP (TF-IDF + cosine similarity), not an LLM.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import median

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .constants import (
    CRUX_MAJORITY_RATIO,
    CRUX_SPLIT_MIN,
    EXPECTED_MAJOR_OUTLETS,
    EXTRA_STOPWORDS,
    FACT_KEYWORDS,
    POLL_CONFIDENCE_WEIGHT,
    SIM_THRESHOLD,
    confidence_label,
)

DATA_DIR = Path(__file__).parent / "data"
TONE_POSITIVE = "positive"
TONE_NEGATIVE = "negative"
TONE_MAJORITY = "majority"

LEAN_BUCKETS = ["left", "lean-left", "center", "lean-right", "right"]
LEAN_LABELS = {
    "left": "Left",
    "lean-left": "Lean left",
    "center": "Center",
    "lean-right": "Lean right",
    "right": "Right",
}

_WORD_RE = re.compile(r"[a-z0-9']+")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@lru_cache
def _loaded_terms() -> list[dict]:
    path = DATA_DIR / "loaded_terms.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh).get("terms", [])


def _text(article) -> str:
    return f"{article.headline} {article.description}".strip()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalize_lean(lean: str | None) -> str:
    key = (lean or "center").lower().replace("_", "-")
    return key if key in LEAN_BUCKETS else "center"


def bias_spread(articles) -> dict:
    """Count articles per political lean bucket for the 5-segment bias bar."""
    counts = {b: 0 for b in LEAN_BUCKETS}
    for art in articles:
        if not art.outlet:
            continue
        counts[_normalize_lean(art.outlet.lean)] += 1
    total = sum(counts.values()) or 1
    segments = [
        {
            "bucket": b,
            "label": LEAN_LABELS[b],
            "count": counts[b],
            "pct": round(counts[b] / total * 100),
        }
        for b in LEAN_BUCKETS
    ]
    nonzero = sum(1 for c in counts.values() if c > 0)
    dominant = max(counts, key=counts.get)
    return {
        "counts": counts,
        "segments": segments,
        "total": total,
        "diversity": round(nonzero / 5, 2),
        "dominant_lean": dominant,
        "dominant_label": LEAN_LABELS[dominant],
    }


# ---------------------------------------------------------------------------
# Reporting stance (positive / negative / majority-neutral tone)
# ---------------------------------------------------------------------------
def _outlet_tone(matches: list[dict]) -> str:
    """Classify an outlet's headline tone from loaded-term weights."""
    strong = [m for m in matches if m.get("category") != "hedging"]
    if not strong:
        return TONE_MAJORITY
    net = sum(m["weight"] for m in strong)
    if net > 0.12:
        return TONE_POSITIVE
    if net < -0.12:
        return TONE_NEGATIVE
    return TONE_MAJORITY


def reporting_stance(articles, loaded: dict | None = None) -> dict:
    """How outlets frame the story: positive, negative, or aligned with the majority tone."""
    if loaded is None:
        loaded = loaded_terms_scan(articles)
    counts = {TONE_POSITIVE: 0, TONE_NEGATIVE: 0, TONE_MAJORITY: 0}
    for row in loaded["per_article"]:
        tone = _outlet_tone(row["matches"])
        counts[tone] += 1
    total = sum(counts.values()) or 1
    labels = {
        TONE_POSITIVE: "Positive framing",
        TONE_NEGATIVE: "Negative framing",
        TONE_MAJORITY: "Majority take",
    }
    colors = {
        TONE_POSITIVE: "emerald",
        TONE_NEGATIVE: "rose",
        TONE_MAJORITY: "slate",
    }
    segments = [
        {
            "tone": tone,
            "label": labels[tone],
            "count": counts[tone],
            "pct": round(counts[tone] / total * 100),
            "color": colors[tone],
        }
        for tone in (TONE_POSITIVE, TONE_MAJORITY, TONE_NEGATIVE)
    ]
    dominant = max(counts, key=counts.get)
    return {
        "counts": counts,
        "segments": segments,
        "total": total,
        "dominant": dominant,
        "dominant_label": labels[dominant],
    }


# ---------------------------------------------------------------------------
# 8.3 Loaded-term scan + framing divergence
# ---------------------------------------------------------------------------
def loaded_terms_scan(articles) -> dict:
    terms = _loaded_terms()
    per_article = []
    per_term = defaultdict(lambda: {"outlets": set(), "count": 0, "meta": None})
    total_magnitude = 0.0

    for art in articles:
        text = _text(art).lower()
        padded = f" {text} "
        tokens = set(_WORD_RE.findall(text))
        matches = []
        for term in terms:
            t = term["term"].lower()
            hit = (t in tokens) if " " not in t else (f" {t} " in padded)
            if hit:
                matches.append(term)
                total_magnitude += abs(term["weight"])
                outlet_name = art.outlet.name if art.outlet else "Unknown"
                per_term[t]["outlets"].add(outlet_name)
                per_term[t]["count"] += 1
                per_term[t]["meta"] = term
        matches.sort(key=lambda m: abs(m["weight"]), reverse=True)
        per_article.append({
            "outlet": art.outlet.name if art.outlet else "Unknown",
            "tone": _outlet_tone(matches),
            "matches": matches,
            "magnitude": round(sum(abs(m["weight"]) for m in matches), 2),
        })

    n = len(articles) or 1
    avg_magnitude = total_magnitude / n

    # Framing divergence: each outlet's single most charged term (exclude hedging)
    framing = []
    for row in per_article:
        strong = [m for m in row["matches"] if m["category"] != "hedging"]
        if strong:
            top = strong[0]
            framing.append({
                "outlet": row["outlet"],
                "tone": row["tone"],
                "tone_label": row["tone"].replace("_", " ").title(),
                "term": top["term"],
                "neutral": top["neutral"],
                "weight": top["weight"],
                "direction": "positive" if top["weight"] > 0 else "negative",
            })
    framing.sort(key=lambda f: abs(f["weight"]), reverse=True)

    term_cloud = sorted(
        (
            {
                "term": t,
                "count": info["count"],
                "outlets": len(info["outlets"]),
                "weight": info["meta"]["weight"],
                "neutral": info["meta"]["neutral"],
                "category": info["meta"]["category"],
                "direction": "positive" if info["meta"]["weight"] > 0 else "negative",
            }
            for t, info in per_term.items()
        ),
        key=lambda x: (x["outlets"], x["count"]),
        reverse=True,
    )

    return {
        "per_article": per_article,
        "framing": framing,
        "term_cloud": term_cloud,
        "avg_magnitude": round(avg_magnitude, 3),
        "language_penalty": _clamp(avg_magnitude),
    }


# ---------------------------------------------------------------------------
# Narrative Split — how outlets frame the same story
# ---------------------------------------------------------------------------
_NARRATIVE_DOMAINS: dict[str, list[dict]] = {
    "conflict": [
        {
            "id": "security",
            "label": "Security Narrative",
            "color": "blue",
            "strong_signals": [
                "self-defense", "defensive operation", "defensive", "justified",
                "idf operation", "retaliation for", "only targets", "military sites only",
            ],
            "signals": [
                "retaliation", "retaliatory", "operation", "military facilities",
                "military sites", "military targets", "military infrastructure", "provocation",
            ],
            "claims": [
                ("defensive|self-defense", "Action was defensive"),
                ("retaliation|retaliatory|response to|provocation", "Threat was imminent"),
                ("justified|operation|military sites|military facilities|military targets", "Response was justified"),
            ],
        },
        {
            "id": "humanitarian",
            "label": "Humanitarian Narrative",
            "color": "rose",
            "strong_signals": [
                "massacre", "brutal", "unprovoked", "regional war", "civilians",
                "including civilians", "condemned the attack",
            ],
            "signals": [
                "civilian", "escalation", "condemn", "wounded", "fears of",
                "devastating", "atrocity", "kills 16", "kills 61", "dozens killed",
            ],
            "claims": [
                ("civilian|massacre|killed including|wounded", "Civilian impact emphasized"),
                ("escalation|regional war|wider regional|fears of", "Escalation risk highlighted"),
                ("condemn|international|criticism|controversial", "International criticism discussed"),
            ],
        },
    ],
    "election": [
        {
            "id": "momentum",
            "label": "Momentum Narrative",
            "color": "blue",
            "signals": ["surge", "gain", "gaining", "landmark", "lead", "momentum", "shift"],
            "claims": [
                ("surge|lead|momentum|shift", "One party has momentum"),
                ("landmark|breakthrough", "Race framed as a turning point"),
                ("gain|gaining ground", "Recent polling shows movement"),
            ],
        },
        {
            "id": "skeptical",
            "label": "Skeptical Narrative",
            "color": "amber",
            "signals": [
                "margin of error", "toss-up", "disputed", "slammed", "overstating",
                "within the margin", "competitive", "cautioned",
            ],
            "claims": [
                ("margin of error|toss-up|within the margin", "Lead treated as statistically uncertain"),
                ("disputed|slammed|overstating", "Rival framing criticized as misleading"),
                ("cautioned|competitive|narrowing", "Race described as too close to call"),
            ],
        },
    ],
    "regulation": [
        {
            "id": "protection",
            "label": "Protection Narrative",
            "color": "emerald",
            "signals": ["landmark", "hailed", "breakthrough", "protect", "rights", "transparency", "benchmark"],
            "claims": [
                ("landmark|breakthrough|benchmark", "Rules framed as historic progress"),
                ("protect|rights|transparency", "Consumer and digital rights emphasized"),
                ("hailed|welcomed|overdue", "Regulation praised as necessary"),
            ],
        },
        {
            "id": "burden",
            "label": "Burden Narrative",
            "color": "amber",
            "signals": ["burden", "burdensome", "compliance", "cost", "costly", "crackdown", "controversial", "warned"],
            "claims": [
                ("burden|burdensome|compliance cost", "Compliance burden highlighted"),
                ("crackdown|controversial", "Rules framed as stifling innovation"),
                ("warned|industry", "Industry pushback emphasized"),
            ],
        },
    ],
    "climate": [
        {
            "id": "breakthrough",
            "label": "Breakthrough Narrative",
            "color": "emerald",
            "signals": ["breakthrough", "landmark", "sealed", "progress", "compromise", "hailed"],
            "claims": [
                ("breakthrough|landmark|sealed", "Deal framed as a breakthrough"),
                ("progress|compromise", "Negotiations described as productive"),
                ("committed|agreement reached", "Concrete commitments emphasized"),
            ],
        },
        {
            "id": "insufficient",
            "label": "Insufficient Narrative",
            "color": "rose",
            "signals": ["inadequate", "falls short", "not enough", "disappointment", "critics", "short of"],
            "claims": [
                ("inadequate|falls short|not enough", "Deal deemed insufficient"),
                ("vulnerable nations|finance", "Finance for vulnerable nations criticized"),
                ("scientists|campaigners|critics", "Scientific ambition questioned"),
            ],
        },
    ],
    "economic": [
        {
            "id": "policy",
            "label": "Policy Narrative",
            "color": "slate",
            "signals": ["held", "unchanged", "inflation", "rates", "policymakers", "data dependent"],
            "claims": [
                ("held|unchanged|steady", "Rate decision reported as expected"),
                ("inflation|cooling|easing", "Inflation trend emphasized"),
                ("patience|data dependent|cuts", "Future path left open"),
            ],
        },
    ],
}


def _story_domain(articles) -> str:
    blob = " ".join(_text(a).lower() for a in articles)
    if any(k in blob for k in ("strike", "missile", "military", "attack", "war", "idf")):
        return "conflict"
    if any(k in blob for k in ("poll", "election", "midterm", "vote", "ballot")):
        return "election"
    if any(k in blob for k in ("ai act", "regulation", "compliance", "enforcement")):
        return "regulation"
    if any(k in blob for k in ("climate", "emissions", "summit", "cop")):
        return "climate"
    if any(k in blob for k in ("federal reserve", "fed ", "interest rate", "inflation")):
        return "economic"
    return "conflict"


def _text_hits(text: str, pattern: str) -> bool:
    parts = pattern.split("|")
    return any(p in text for p in parts)


def _narrative_score(text: str, signals: list[str], strong: list[str] | None = None) -> float:
    score = 0.0
    for sig in strong or []:
        if sig in text:
            score += 3.0
    for sig in signals:
        if sig in text:
            score += 1.0 if " " not in sig else 1.5
    return score


def _is_wire_reporting(text: str) -> bool:
    """Wire-style factual copy without strong narrative framing."""
    charged = (
        "massacre", "brutal", "unprovoked", "self-defense", "defensive operation",
        "justified", "regional war", "idf operation", "condemned the attack",
    )
    if any(c in text for c in charged):
        return False
    if ("operation" in text or "retaliation" in text) and (
        "response to" in text or "retaliation" in text or "military targets" in text
    ):
        if "casualty figures" not in text and not (
            "officials said" in text and "people killed" in text
        ):
            return False
    if "casualty figures" in text or "casualties reported" in text:
        return True
    if "officials said" in text and "people killed" in text and "massacre" not in text:
        return True
    wire_markers = ("officials said", "authorities said", "reported", "according to")
    return any(m in text for m in wire_markers)


def _classify_outlet_narrative(text: str, profiles: list[dict]) -> str | None:
    """Assign outlet to the narrative camp with the strongest distinct signal."""
    if any(x in text for x in ("massacre", "brutal", "unprovoked massacre", "regional war", "including civilians")):
        return "humanitarian"
    if ("attack on iran kills" in text or "regional war" in text) and "self-defense" not in text:
        return "humanitarian"
    if _is_wire_reporting(text):
        return None
    if any(x in text for x in (
        "self-defense", "defensive operation", "justified retaliation", "idf operation",
        "operation was a response", "hits iran military", "military sites in retaliation",
    )):
        return "security"
    scores = []
    for p in profiles:
        strong = p.get("strong_signals", [])
        s = _narrative_score(text, p["signals"], strong)
        scores.append((p["id"], s))
    scores.sort(key=lambda x: x[1], reverse=True)
    best_id, best = scores[0]
    second = scores[1][1] if len(scores) > 1 else 0.0
    if best < 2.5:
        return None
    if second >= best - 1.0:
        return None
    return best_id


def _extract_narrative_claims(texts: list[str], claim_rules: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern, label in claim_rules:
        if label in seen:
            continue
        if any(_text_hits(t, pattern) for t in texts):
            found.append(label)
            seen.add(label)
    return found[:4]


def narrative_split(articles, loaded: dict | None = None) -> dict:
    """Group outlets into competing narrative frames with shared claims."""
    domain = _story_domain(articles)
    profiles = _NARRATIVE_DOMAINS.get(domain, _NARRATIVE_DOMAINS["conflict"])
    total = len(articles) or 1

    assignments: dict[str, list[dict]] = {p["id"]: [] for p in profiles}
    unassigned: list[str] = []

    for art in articles:
        text = _text(art).lower()
        name = art.outlet.name if art.outlet else "Unknown"
        camp = _classify_outlet_narrative(text, profiles)
        if camp:
            assignments[camp].append({"outlet": name, "text": text})
        else:
            unassigned.append(name)

    narratives = []
    for profile in profiles:
        members = assignments[profile["id"]]
        if not members:
            continue
        texts = [m["text"] for m in members]
        claims = _extract_narrative_claims(texts, profile["claims"])
        if not claims and members:
            claims = [f"Framing aligned with {profile['label'].lower()}"]
        narratives.append({
            "id": profile["id"],
            "label": profile["label"],
            "color": profile["color"],
            "outlet_count": len(members),
            "claims": claims,
            "sources": sorted(m["outlet"] for m in members),
        })

    narratives.sort(key=lambda n: n["outlet_count"], reverse=True)

    if unassigned:
        narratives.append({
            "id": "neutral",
            "label": "Neutral / Wire Reporting",
            "color": "slate",
            "outlet_count": len(unassigned),
            "claims": ["Facts reported with minimal loaded language"],
            "sources": sorted(unassigned),
        })

    return {
        "domain": domain,
        "total_outlets": total,
        "narratives": narratives,
        "has_split": len(narratives) >= 2,
    }


# ---------------------------------------------------------------------------
# Consensus vs Contested vs Unknown
# ---------------------------------------------------------------------------
def _simplify_claim(text: str) -> str:
    lower = text.lower()
    rules = [
        (("military facilit", "military site", "military target", "military infrastructure"), "Military sites were struck"),
        (("strike", "attack", "missile"), "Attack occurred"),
        (("officials said", "officials reported", "confirmed", "government", "authorities said"), "Government confirmed operation"),
        (("poll", "margin", "survey"), "Poll showed movement in the race"),
        (("held rates", "held interest", "unchanged", "on hold"), "Rates held steady"),
        (("ai act", "rules took effect", "enforcing", "enforcement"), "AI Act enforcement began"),
        (("deal", "agreement", "reached a deal"), "Agreement was reached"),
        (("emissions", "finance package", "climate summit"), "Summit produced a formal deal"),
    ]
    for keys, label in rules:
        if any(k in lower for k in keys):
            return label
    return _truncate_claim(text, 52)


def _outlets_with_keywords(articles, keywords: list[str]) -> set[str]:
    hits: set[str] = set()
    for art in articles:
        text = _text(art).lower()
        if any(k in text for k in keywords):
            hits.add(art.outlet.name if art.outlet else "Unknown")
    return hits


def consensus_landscape(
    articles,
    crux: dict | None = None,
    disputed: dict | None = None,
    narrative: dict | None = None,
) -> dict:
    """Ground News-style consensus / contested / unknown breakdown."""
    if crux is None:
        crux = crux_points(articles)
    if disputed is None:
        disputed = disputed_facts(articles)
    if narrative is None:
        narrative = narrative_split(articles)

    total = crux["total_outlets"] or len(articles) or 1
    seen_consensus: set[str] = set()
    consensus: list[dict] = []
    _MILITARY_CLAIMS = {"Military sites were struck", "Military facilities were targeted"}

    for p in crux["majority"]:
        if p["ratio"] >= 0.55:
            claim = _simplify_claim(p["claim"])
            if claim in seen_consensus:
                continue
            if claim in _MILITARY_CLAIMS and _MILITARY_CLAIMS & seen_consensus:
                continue
            seen_consensus.add(claim)
            consensus.append({
                "claim": claim,
                "support_count": p["support_count"],
                "total": total,
                "support_label": f"{p['support_count']}/{total} outlets",
                "point_id": p["id"],
            })

    # Facility count heuristic for conflict stories
    if narrative.get("domain") == "conflict":
        facility_hits = _outlets_with_keywords(
            articles, ["military facilit", "military site", "military target", "military infrastructure"]
        )
        if len(facility_hits) >= total * 0.5:
            claim = "Military facilities were targeted"
            if claim not in seen_consensus and not (_MILITARY_CLAIMS & seen_consensus):
                seen_consensus.add(claim)
                consensus.append({
                    "claim": claim,
                    "support_count": len(facility_hits),
                    "total": total,
                    "support_label": f"{len(facility_hits)}/{total} outlets",
                    "point_id": None,
                })
        attack_hits = _outlets_with_keywords(articles, ["strike", "attack", "missile"])
        if len(attack_hits) >= total * 0.7:
            claim = "Attack occurred"
            if claim not in seen_consensus:
                seen_consensus.add(claim)
                consensus.append({
                    "claim": claim,
                    "support_count": len(attack_hits),
                    "total": total,
                    "support_label": f"{len(attack_hits)}/{total} outlets",
                    "point_id": None,
                })
        confirm_hits = _outlets_with_keywords(
            articles, ["officials said", "authorities said", "government", "military said", "confirmed"]
        )
        if len(confirm_hits) >= total * 0.4:
            claim = "Government confirmed operation"
            if claim not in seen_consensus:
                seen_consensus.add(claim)
                consensus.append({
                    "claim": claim,
                    "support_count": len(confirm_hits),
                    "total": total,
                    "support_label": f"{len(confirm_hits)}/{total} outlets",
                    "point_id": None,
                })

    contested: list[dict] = []
    seen_contested: set[str] = set()

    domain = narrative.get("domain", "conflict")
    if domain == "conflict" and len(narrative.get("narratives", [])) >= 2:
        by_id = {n["id"]: n for n in narrative["narratives"]}
        sec = by_id.get("security", {})
        hum = by_id.get("humanitarian", {})
        sec_n = sec.get("outlet_count", 0)
        hum_n = hum.get("outlet_count", 0)
        if sec_n and hum_n:
            for claim in (
                "Whether operation was defensive",
                "Scale of civilian impact",
            ):
                if claim not in seen_contested:
                    seen_contested.add(claim)
                    contested.append({
                        "claim": claim,
                        "for_count": sec_n,
                        "against_count": hum_n,
                        "split_label": f"{sec_n} vs {hum_n}",
                    })
        law_hits = _outlets_with_keywords(articles, ["international", "law", "condemn", "unprovoked", "legality"])
        other = total - len(law_hits)
        if law_hits and other and abs(len(law_hits) - other) <= max(2, total // 3):
            claim = "Legality under international law"
            if claim not in seen_contested:
                seen_contested.add(claim)
                contested.append({
                    "claim": claim,
                    "for_count": len(law_hits),
                    "against_count": other,
                    "split_label": f"{len(law_hits)} vs {other}",
                })

    elif domain == "election" and len(narrative.get("narratives", [])) >= 2:
        by_id = {n["id"]: n for n in narrative["narratives"]}
        mom = by_id.get("momentum", {}).get("outlet_count", 0)
        ske = by_id.get("skeptical", {}).get("outlet_count", 0)
        if mom and ske:
            contested.append({
                "claim": "Whether one party has clear momentum",
                "for_count": mom,
                "against_count": ske,
                "split_label": f"{mom} vs {ske}",
            })

    elif domain == "regulation" and len(narrative.get("narratives", [])) >= 2:
        by_id = {n["id"]: n for n in narrative["narratives"]}
        prot = by_id.get("protection", {}).get("outlet_count", 0)
        burd = by_id.get("burden", {}).get("outlet_count", 0)
        if prot and burd:
            contested.append({
                "claim": "Whether rules protect citizens or burden industry",
                "for_count": prot,
                "against_count": burd,
                "split_label": f"{prot} vs {burd}",
            })

    elif domain == "climate" and len(narrative.get("narratives", [])) >= 2:
        by_id = {n["id"]: n for n in narrative["narratives"]}
        brk = by_id.get("breakthrough", {}).get("outlet_count", 0)
        ins = by_id.get("insufficient", {}).get("outlet_count", 0)
        if brk and ins:
            contested.append({
                "claim": "Whether the deal is adequate",
                "for_count": brk,
                "against_count": ins,
                "split_label": f"{brk} vs {ins}",
            })

    for p in crux.get("split", []):
        claim = _simplify_claim(p["claim"])
        if claim in seen_consensus or claim in seen_contested:
            continue
        against = total - p["support_count"]
        if against > 0 and p["support_count"] <= total // 2:
            seen_contested.add(claim)
            contested.append({
                "claim": claim,
                "for_count": p["support_count"],
                "against_count": against,
                "split_label": f"{p['support_count']} vs {against}",
                "point_id": p["id"],
            })

    unknown: list[dict] = []
    _UNKNOWN_LABELS = {
        "casualties": "Actual casualty count",
        "wounded": "Actual wounded count",
        "projectiles": "Actual projectile count",
        "poll margin (points)": "Actual poll margin",
    }
    for fact in disputed.get("disputed", []):
        label = _UNKNOWN_LABELS.get(fact["fact"], f"Actual {fact['fact']}")
        unknown.append({"claim": label, "reason": "Outlets report conflicting numbers"})

    long_term = _outlets_with_keywords(articles, ["long-term", "long term", "consequences", "years ahead", "lasting"])
    if len(long_term) < total * 0.35:
        unknown.append({"claim": "Long-term consequences", "reason": "Few outlets address downstream impact"})

    casualty_disputed = any(f["fact"] == "casualties" for f in disputed.get("disputed", []))
    if casualty_disputed and not any(u["claim"] == "Actual casualty count" for u in unknown):
        unknown.append({"claim": "Actual casualty count", "reason": "Figures still disputed across sources"})

    return {
        "total_outlets": total,
        "consensus": consensus[:6],
        "contested": contested[:5],
        "unknown": unknown[:5],
    }


def crux_highlight(landscape: dict, crux: dict | None = None) -> dict:
    """Prominent majority-agreement block — the clarity crux of what happened."""
    points = list(landscape.get("consensus", []))
    total = landscape.get("total_outlets", 0)

    if not points and crux:
        for p in crux.get("majority", []):
            points.append({
                "claim": _simplify_claim(p["claim"]),
                "support_count": p["support_count"],
                "total": p["total_outlets"],
                "support_label": f"{p['support_count']}/{p['total_outlets']} outlets",
                "point_id": p["id"],
            })

    if not points:
        return {
            "has_crux": False,
            "headline": "Sources have not converged on a clear majority take yet.",
            "points": [],
            "majority_label": None,
            "total_outlets": total,
        }

    headline = points[0]["claim"]
    if len(points) >= 2:
        headline = f"{points[0]['claim']}. {points[1]['claim']}."

    top = points[0]
    return {
        "has_crux": True,
        "headline": headline,
        "points": points,
        "majority_label": f"Majority agree — {top['support_label']}",
        "total_outlets": total,
    }


# ---------------------------------------------------------------------------
# 8.4 Disputed facts (numbers)
# ---------------------------------------------------------------------------
def _map_keyword(kw: str) -> str:
    if kw in {"dead", "deaths", "killed", "casualties"}:
        return "casualties"
    if kw in {"wounded", "injured"}:
        return "wounded"
    if kw in {"missiles", "rockets", "drones"}:
        return "projectiles"
    if kw in {"point", "points"}:
        return "poll margin (points)"
    if kw in {"soldiers", "troops"}:
        return "troops"
    return kw


def _fact_report_line(outlet: str, fact_type: str, value: float | int) -> str:
    """Human-readable one-liner: 'Reuters reported 14 casualties'."""
    val = int(value) if isinstance(value, float) and value == int(value) else value
    val_s = f"{val:,}" if isinstance(val, int) else str(val)
    labels = {
        "casualties": "casualties",
        "wounded": "people wounded",
        "projectiles": "missiles / projectiles",
        "poll margin (points)": "point poll margin",
        "troops": "troops",
    }
    label = labels.get(fact_type, fact_type)
    return f"{outlet} reported {val_s} {label}"


def _fact_type_for(tokens: list[str], idx: int) -> str | None:
    """Return the fact type from the nearest context keyword to the number."""
    for dist in range(1, 5):
        for j in (idx + dist, idx - dist):
            if 0 <= j < len(tokens) and tokens[j] in FACT_KEYWORDS:
                return _map_keyword(tokens[j])
    return None


def disputed_facts(articles) -> dict:
    by_fact: dict[str, list[dict]] = defaultdict(list)
    for art in articles:
        text = _text(art)
        lowered = text.lower()
        words = _WORD_RE.findall(lowered)
        for match in _NUMBER_RE.finditer(lowered):
            raw = match.group().replace(",", "")
            try:
                value = float(raw)
            except ValueError:
                continue
            before = lowered[: match.start()]
            idx = len(_WORD_RE.findall(before))
            fact = _fact_type_for(words, idx)
            if fact is None:
                continue
            by_fact[fact].append({
                "outlet": art.outlet.name if art.outlet else "Unknown",
                "value": value,
                "headline": art.headline,
            })

    disputed = []
    distinct_fact_types = 0
    for fact, entries in by_fact.items():
        values = [e["value"] for e in entries]
        if len(values) < 2:
            continue
        distinct_fact_types += 1
        lo, hi = min(values), max(values)
        if len(set(values)) > 1 and hi > 1.25 * lo:
            # dedupe outlets, keep highest value per outlet
            best: dict[str, dict] = {}
            for e in entries:
                if e["outlet"] not in best or e["value"] > best[e["outlet"]]["value"]:
                    best[e["outlet"]] = e
            ordered = sorted(best.values(), key=lambda e: e["value"])
            rows = []
            for e in ordered:
                v = int(e["value"]) if e["value"] == int(e["value"]) else e["value"]
                rows.append({
                    **e,
                    "value": v,
                    "line": _fact_report_line(e["outlet"], fact, v),
                })
            disputed.append({
                "fact": fact,
                "min": lo,
                "max": hi,
                "spread_ratio": round(hi / lo, 1) if lo else None,
                "rows": rows,
            })

    dispute_ratio = len(disputed) / max(1, distinct_fact_types)
    return {
        "disputed": disputed,
        "count": len(disputed),
        "dispute_ratio": _clamp(dispute_ratio),
    }


# ---------------------------------------------------------------------------
# 8.5 Missing coverage
# ---------------------------------------------------------------------------
def missing_coverage(articles, all_outlets_by_name: dict | None = None) -> dict:
    present = {art.outlet.name for art in articles if art.outlet}
    missing = []
    for name in EXPECTED_MAJOR_OUTLETS:
        if name not in present:
            missing.append({"outlet": name})
    return {
        "missing": missing,
        "missing_count": len(missing),
        "expected_total": len(EXPECTED_MAJOR_OUTLETS),
        "present_count": len(EXPECTED_MAJOR_OUTLETS) - len(missing),
    }


# ---------------------------------------------------------------------------
# Crux engine (TF-IDF + cosine clustering, no LLM)
# ---------------------------------------------------------------------------
def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if len(_WORD_RE.findall(p)) >= 4]


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def crux_points(articles) -> dict:
    """Extract the Crux — what the majority of independent sources converge on."""
    sentences: list[dict] = []
    for art in articles:
        outlet = art.outlet.name if art.outlet else "Unknown"
        candidates = [art.headline] + _split_sentences(art.description or "")
        for sent in candidates:
            sent = sent.strip()
            if len(_WORD_RE.findall(sent)) >= 4:
                sentences.append({"text": sent, "outlet": outlet, "url": art.url})

    total_outlets = len({art.outlet.name for art in articles if art.outlet}) or 1
    if len(sentences) < 2:
        return {"majority": [], "split": [], "total_outlets": total_outlets}

    corpus = [s["text"].lower() for s in sentences]
    try:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 1), sublinear_tf=False)
        matrix = vec.fit_transform(corpus)
        sim = cosine_similarity(matrix)
    except ValueError:
        return {"majority": [], "split": [], "total_outlets": total_outlets}

    uf = _UnionFind(len(sentences))
    for i in range(len(sentences)):
        for j in range(i + 1, len(sentences)):
            if sim[i, j] >= SIM_THRESHOLD:
                uf.union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(sentences)):
        clusters[uf.find(i)].append(i)

    majority, split = [], []
    cid = 0
    for members in clusters.values():
        outlets = {sentences[m]["outlet"] for m in members}
        ratio = len(outlets) / total_outlets
        if ratio < CRUX_SPLIT_MIN:
            continue
        best_idx = max(members, key=lambda m: sum(sim[m, n] for n in members))
        seen: dict[str, dict] = {}
        for m in members:
            s = sentences[m]
            if s["outlet"] not in seen:
                seen[s["outlet"]] = {
                    "outlet": s["outlet"],
                    "sentence": s["text"],
                    "url": s["url"],
                }
        point = {
            "id": cid,
            "claim": sentences[best_idx]["text"],
            "support_count": len(outlets),
            "total_outlets": total_outlets,
            "ratio": round(ratio, 2),
            "pct": round(ratio * 100),
            "supporting": sorted(seen.values(), key=lambda x: x["outlet"]),
        }
        cid += 1
        if ratio >= CRUX_MAJORITY_RATIO:
            point["status"] = "majority"
            majority.append(point)
        else:
            point["status"] = "split"
            split.append(point)

    majority.sort(key=lambda p: p["support_count"], reverse=True)
    split.sort(key=lambda p: p["support_count"], reverse=True)
    return {
        "majority": majority[:6],
        "split": split[:5],
        "total_outlets": total_outlets,
    }


def consensus_points(articles) -> dict:
    """Backward-compatible alias for crux_points."""
    return crux_points(articles)


def _majority_crux_strength(crux: dict) -> float:
    if not crux["majority"]:
        return 0.4
    return sum(p["ratio"] for p in crux["majority"]) / len(crux["majority"])


def _truncate_claim(text: str, max_len: int = 72) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rsplit(" ", 1)[0] + "…"


def _outlet_supports_crux(outlet: str, point: dict) -> bool:
    return any(s["outlet"] == outlet for s in point.get("supporting", []))


def outlet_story_scores(
    articles,
    crux: dict | None = None,
    loaded: dict | None = None,
    disputed: dict | None = None,
    poll_score: float | None = None,
) -> list[dict]:
    """Per-outlet score out of 10 for this story with transparent sub-metrics."""
    if crux is None:
        crux = crux_points(articles)
    if loaded is None:
        loaded = loaded_terms_scan(articles)
    if disputed is None:
        disputed = disputed_facts(articles)

    total = crux["total_outlets"] or 1
    majority_points = crux["majority"]
    all_crux = crux["majority"] + crux["split"]
    poll_norm = poll_score if poll_score is not None else 0.5

    per_outlet_tone: dict[str, str] = {}
    for row in loaded["per_article"]:
        per_outlet_tone[row["outlet"]] = row["tone"]

    # Timeliness: rank by earliest published_at
    sorted_arts = sorted(articles, key=lambda a: a.published_at)
    rank_map = {
        (a.outlet.name if a.outlet else "Unknown"): i
        for i, a in enumerate(sorted_arts)
    }
    n_arts = len(sorted_arts) or 1

    # Disputed-fact divergence per outlet
    diverged: set[str] = set()
    for fact in disputed["disputed"]:
        vals = fact["rows"]
        if len(vals) < 2:
            continue
        med = median([v["value"] for v in vals])
        for v in vals:
            if med and abs(v["value"] - med) / max(med, 1) > 0.15:
                diverged.add(v["outlet"])

    dominant_tone = reporting_stance(articles, loaded)["dominant"]

    scores = []
    for art in articles:
        name = art.outlet.name if art.outlet else "Unknown"

        if majority_points:
            aligned = sum(1 for p in majority_points if _outlet_supports_crux(name, p))
            crux_align = aligned / len(majority_points)
            points_missed = [
                _truncate_claim(p["claim"])
                for p in majority_points
                if not _outlet_supports_crux(name, p)
            ]
            points_score = 1.0 - len(points_missed) / len(majority_points)
        else:
            crux_align = 0.5
            points_missed = []
            points_score = 1.0

        # Divergence from mass reporting
        tone = per_outlet_tone.get(name, TONE_MAJORITY)
        tone_penalty = 0.0 if tone == dominant_tone or tone == TONE_MAJORITY else 0.25
        div_score = 1.0 - (0.5 if name in diverged else 0.0) - tone_penalty

        # Timeliness
        rank = rank_map.get(name, n_arts - 1)
        timeliness = 1.0 - rank / max(n_arts - 1, 1)

        # Top terms this outlet used
        top_terms = [
            m["term"] for m in sorted(
                [m for row in loaded["per_article"] if row["outlet"] == name for m in row["matches"]],
                key=lambda m: abs(m["weight"]),
                reverse=True,
            )[:4]
        ]

        # Public agreement: community poll modulated by crux alignment
        public_agreement = poll_norm * (0.55 + 0.45 * crux_align)

        subs = {
            "crux_alignment": round(crux_align, 2),
            "points_coverage": round(_clamp(points_score), 2),
            "mass_alignment": round(_clamp(div_score), 2),
            "timeliness": round(timeliness, 2),
            "public_agreement": round(public_agreement, 2),
        }
        composite = (
            0.30 * subs["crux_alignment"]
            + 0.20 * subs["points_coverage"]
            + 0.25 * subs["mass_alignment"]
            + 0.15 * subs["timeliness"]
            + 0.10 * subs["public_agreement"]
        )
        score_10 = round(composite * 10, 1)

        scores.append({
            "outlet": name,
            "headline": art.headline,
            "url": art.url,
            "published_at": art.published_at,
            "tone": tone,
            "tone_label": {"positive": "Positive", "negative": "Negative", "majority": "Majority take"}.get(tone, tone),
            "score": score_10,
            "points_missed": points_missed,
            "top_terms": top_terms,
            "late_reporting": rank > n_arts * 0.6,
            "subs": subs,
            "breakdown": [
                {"label": "Crux alignment", "value": subs["crux_alignment"], "note": "supports majority take"},
                {"label": "Crux points covered", "value": subs["points_coverage"], "note": f"{len(points_missed)} points missed"},
                {"label": "Mass reporting alignment", "value": subs["mass_alignment"], "note": "numbers + tone vs majority"},
                {"label": "Timeliness", "value": subs["timeliness"], "note": "early vs late to story"},
                {"label": "Public agreement", "value": subs["public_agreement"], "note": "community poll × alignment"},
            ],
        })

    scores.sort(key=lambda s: s["score"], reverse=True)
    return scores


# ---------------------------------------------------------------------------
# Community poll score (0..1)
# ---------------------------------------------------------------------------
POLL_QUESTION_META = {
    "completeness": {"type": "yesno", "invert": False},
    "trust": {"type": "scale", "max": 5},
    "informed": {"type": "scale", "max": 5},
    "framing_fair": {"type": "scale", "max": 5},
    "facts_clear": {"type": "scale", "max": 5},
    "missing_angles": {"type": "yesno", "invert": True},
    "would_recommend": {"type": "scale", "max": 5},
    "numbers_confidence": {"type": "scale", "max": 5},
}


def poll_community_score(vote_tally: dict[str, dict[str, int]]) -> dict:
    """Aggregate community poll responses into a 0..1 score."""
    norms: list[float] = []
    for key, meta in POLL_QUESTION_META.items():
        counts = vote_tally.get(key, {})
        total = sum(counts.values())
        if total == 0:
            continue
        if meta["type"] == "yesno":
            yes = counts.get("yes", 0)
            no = counts.get("no", 0)
            val = yes / (yes + no) if (yes + no) else 0.5
            if meta.get("invert"):
                val = 1.0 - val
        else:
            mx = meta["max"]
            weighted = sum(int(k) * v for k, v in counts.items() if k.isdigit())
            val = weighted / (total * mx) if total else 0.5
        norms.append(val)
    score = sum(norms) / len(norms) if norms else 0.5
    return {
        "score": round(score, 2),
        "responses": sum(sum(c.values()) for c in vote_tally.values()),
        "questions_answered": len(norms),
    }


# ---------------------------------------------------------------------------
# Coverage confidence score
# ---------------------------------------------------------------------------
def coverage_confidence(
    articles,
    disputed=None,
    loaded=None,
    crux=None,
    poll_score: float | None = None,
) -> dict:
    n = len(articles)
    if disputed is None:
        disputed = disputed_facts(articles)
    if loaded is None:
        loaded = loaded_terms_scan(articles)
    if crux is None:
        crux = crux_points(articles)

    source_count_score = _clamp(n / 12)
    crux_strength = _majority_crux_strength(crux)
    reliabilities = [art.outlet.reliability for art in articles if art.outlet]
    reliability_score = sum(reliabilities) / len(reliabilities) if reliabilities else 0.5
    agreement_score = _clamp(1.0 - disputed["dispute_ratio"])
    language_penalty = _clamp(loaded["language_penalty"])
    community = poll_score if poll_score is not None else 0.5

    w_poll = POLL_CONFIDENCE_WEIGHT
    w_rest = 1.0 - w_poll
    subs = {
        "source_count": round(source_count_score, 2),
        "crux_strength": round(crux_strength, 2),
        "reliability": round(reliability_score, 2),
        "agreement": round(agreement_score, 2),
        "language": round(1.0 - language_penalty, 2),
        "community": round(community, 2),
    }
    base = (
        0.18 * source_count_score
        + 0.22 * crux_strength
        + 0.22 * reliability_score
        + 0.22 * agreement_score
        + 0.16 * (1.0 - language_penalty)
    )
    score = round(100 * (w_rest * base + w_poll * community))
    breakdown = [
        {"key": "Source count", "value": subs["source_count"], "weight": 18, "note": f"{n} sources"},
        {"key": "Crux strength", "value": subs["crux_strength"], "weight": 22, "note": "majority take clarity"},
        {"key": "Outlet reliability", "value": subs["reliability"], "weight": 22, "note": "editorial track record"},
        {"key": "Fact agreement", "value": subs["agreement"], "weight": 22, "note": f"{disputed['count']} disputed"},
        {"key": "Restrained language", "value": subs["language"], "weight": 16, "note": "loaded-term penalty"},
        {"key": "Community validation", "value": subs["community"], "weight": int(w_poll * 100), "note": "reader polls"},
    ]
    return {
        "score": score,
        "label": confidence_label(score),
        "subs": subs,
        "breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# 8.8 Public reaction: top statements
# ---------------------------------------------------------------------------
def public_reaction_top_statements(comments, limit: int = 12) -> dict:
    seen = set()
    cleaned = []
    for c in comments:
        body = (c.body or "").strip()
        norm = re.sub(r"\s+", " ", body.lower())
        if len(_WORD_RE.findall(body)) < 4 or norm in seen:
            continue
        seen.add(norm)
        cleaned.append(c)
    cleaned.sort(key=lambda c: c.score, reverse=True)
    top = cleaned[:limit]
    reddit_n = sum(1 for c in comments if c.source == "reddit")
    youtube_n = sum(1 for c in comments if c.source == "youtube")
    return {
        "statements": [
            {
                "body": c.body,
                "score": c.score,
                "subreddit": c.subreddit,
                "permalink": c.permalink,
                "source": c.source or "reddit",
                "source_label": "YouTube" if c.source == "youtube" else "Reddit",
            }
            for c in top
        ],
        "total": len(comments),
        "reddit_count": reddit_n,
        "youtube_count": youtube_n,
    }


# ---------------------------------------------------------------------------
# 8.7 Outlet report card
# ---------------------------------------------------------------------------
def _top_phrases(texts: list[str], k: int = 5) -> list[dict]:
    if not texts:
        return []
    stop = list(CountVectorizer(stop_words="english").get_stop_words() | EXTRA_STOPWORDS)
    try:
        vec = CountVectorizer(stop_words=stop, ngram_range=(1, 2), min_df=1)
        matrix = vec.fit_transform([t.lower() for t in texts])
    except ValueError:
        return []
    freqs = np.asarray(matrix.sum(axis=0)).ravel()
    names = vec.get_feature_names_out()
    order = freqs.argsort()[::-1]
    out = []
    for idx in order[: k * 3]:
        phrase = names[idx]
        if len(phrase) < 4:
            continue
        out.append({"phrase": phrase, "count": int(freqs[idx])})
        if len(out) >= k:
            break
    return out


def outlet_report_card(session, outlet) -> dict:
    """Aggregate metrics for one outlet across all cached stories."""
    from sqlalchemy import select

    from .models import Article, Story

    articles = list(session.scalars(
        select(Article).where(Article.outlet_id == outlet.id)
    ))
    total_stories = len(list(session.scalars(select(Story.id))))
    covered_story_ids = {a.story_id for a in articles}
    coverage_breadth = (len(covered_story_ids) / total_stories) if total_stories else 0.0

    texts = [f"{a.headline} {a.description}" for a in articles]
    # emotional language across this outlet's articles
    terms = _loaded_terms()
    mags = []
    for a in articles:
        text = f"{a.headline} {a.description}".lower()
        padded = f" {text} "
        tokens = set(_WORD_RE.findall(text))
        mag = 0.0
        for term in terms:
            t = term["term"].lower()
            hit = (t in tokens) if " " not in t else (f" {t} " in padded)
            if hit:
                mag += abs(term["weight"])
        mags.append(mag)
    emotional = _clamp((sum(mags) / len(mags)) if mags else 0.0)

    # fact agreement: how often this outlet's value equals the cluster median
    agree_hits, agree_total = 0, 0
    for story_id in covered_story_ids:
        story_articles = list(session.scalars(
            select(Article).where(Article.story_id == story_id)
        ))
        df = disputed_facts(story_articles)
        for fact in df["disputed"]:
            med = median([v["value"] for v in fact["rows"]])
            for v in fact["rows"]:
                if v["outlet"] == outlet.name:
                    agree_total += 1
                    if abs(v["value"] - med) < 1e-6:
                        agree_hits += 1
    fact_agreement = (agree_hits / agree_total) if agree_total else None

    return {
        "name": outlet.name,
        "lean": outlet.lean,
        "lean_score": outlet.lean_score,
        "reliability": outlet.reliability,
        "known": outlet.known,
        "articles_count": len(articles),
        "coverage_breadth": round(coverage_breadth, 2),
        "emotional_language": round(emotional, 2),
        "fact_agreement_rate": round(fact_agreement, 2) if fact_agreement is not None else None,
        "top_phrases": _top_phrases(texts),
        "covered_story_ids": covered_story_ids,
    }
