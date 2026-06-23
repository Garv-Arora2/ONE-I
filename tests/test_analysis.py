"""Unit tests for the rule-based analysis engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app import analysis


@dataclass
class FakeOutlet:
    name: str
    reliability: float = 0.8
    known: bool = True
    lean: str = "center"


@dataclass
class FakeArticle:
    headline: str
    description: str
    outlet: FakeOutlet
    url: str = "https://example.com"
    published_at: datetime = datetime(2026, 6, 8)


def _make_cluster():
    return [
        FakeArticle(
            "Israel strikes military sites in Iran",
            "Israel launched a missile strike on military facilities in Iran. "
            "Officials said the strike was a retaliation. They reported 14 people killed and 18 missiles fired.",
            FakeOutlet("Reuters", 0.93),
        ),
        FakeArticle(
            "Israel attack on Iran kills 16",
            "An Israeli attack struck military sites in Iran. "
            "Tehran vowed to respond. Local authorities reported 16 people killed and 24 missiles fired.",
            FakeOutlet("BBC", 0.88),
        ),
        FakeArticle(
            "Massacre in Iran: dozens killed",
            "Israeli missiles struck Iran in what local media called a massacre. "
            "Iran condemned the attack. Reports said up to 61 people were killed.",
            FakeOutlet("Al Jazeera", 0.74),
        ),
        FakeArticle(
            "IDF operation hits Iranian military facilities",
            "The military said its operation struck Iranian military facilities. "
            "It described the strike as a retaliation and self-defense.",
            FakeOutlet("Times of Israel", 0.78),
        ),
    ]


def test_reporting_stance_counts_tones():
    stance = analysis.reporting_stance(_make_cluster())
    assert stance["total"] == 4
    assert sum(stance["counts"].values()) == 4


def test_disputed_facts_detects_casualty_divergence():
    df = analysis.disputed_facts(_make_cluster())
    facts = {d["fact"] for d in df["disputed"]}
    assert "casualties" in facts


def test_loaded_terms_flags_massacre():
    loaded = analysis.loaded_terms_scan(_make_cluster())
    terms = {t["term"] for t in loaded["term_cloud"]}
    assert "massacre" in terms


def test_coverage_confidence_includes_community():
    conf = analysis.coverage_confidence(_make_cluster(), poll_score=0.8)
    assert 0 <= conf["score"] <= 100
    assert any(b["key"] == "Community validation" for b in conf["breakdown"])


def test_crux_points_cluster_with_source_support():
    result = analysis.crux_points(_make_cluster())
    points = result["majority"] + result["split"]
    assert points
    top = result["majority"][0] if result["majority"] else points[0]
    assert top["support_count"] >= 2


def test_outlet_story_scores_returns_ten_scale():
    articles = _make_cluster()
    crux = analysis.crux_points(articles)
    scores = analysis.outlet_story_scores(articles, crux=crux)
    assert len(scores) == 4
    assert all(0 <= s["score"] <= 10 for s in scores)
    assert "points_missed" in scores[0]
    assert scores[0]["breakdown"]


def test_disputed_facts_has_report_lines():
    df = analysis.disputed_facts(_make_cluster())
    if df["disputed"]:
        row = df["disputed"][0]["rows"][0]
        assert "line" in row
        assert "reported" in row["line"].lower()


def test_narrative_split_groups_outlets():
    articles = _make_cluster()
    narrative = analysis.narrative_split(articles)
    assert narrative["has_split"]
    assert len(narrative["narratives"]) >= 2
    ids = {n["id"] for n in narrative["narratives"]}
    assert "security" in ids or "humanitarian" in ids


def test_bias_spread_counts_leans():
    articles = _make_cluster()
    articles[0].outlet.lean = "center"
    articles[1].outlet.lean = "center"
    articles[2].outlet.lean = "lean-left"
    articles[3].outlet.lean = "lean-right"
    bias = analysis.bias_spread(articles)
    assert bias["total"] == 4
    assert len(bias["segments"]) == 5
    assert bias["diversity"] > 0


def test_consensus_points_alias():
    assert analysis.consensus_points(_make_cluster()) == analysis.crux_points(_make_cluster())


def test_crux_highlight_majority_headline():
    articles = _make_cluster()
    crux = analysis.crux_points(articles)
    landscape = analysis.consensus_landscape(articles, crux=crux)
    highlight = analysis.crux_highlight(landscape, crux=crux)
    assert highlight["has_crux"]
    assert highlight["headline"]
    assert highlight["majority_label"]
    assert highlight["points"]


def test_consensus_landscape_buckets():
    articles = _make_cluster()
    crux = analysis.crux_points(articles)
    disputed = analysis.disputed_facts(articles)
    narrative = analysis.narrative_split(articles)
    landscape = analysis.consensus_landscape(articles, crux=crux, disputed=disputed, narrative=narrative)
    assert landscape["consensus"]
    assert landscape["total_outlets"] == 4
    if disputed["disputed"]:
        assert landscape["unknown"]
