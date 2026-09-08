"""AC2 -- confidence labels, source tiers, the High gate, and the Reddit rule.

One fixture input per label and per tier, per ARCHITECTURE.md section 3.
"""
from __future__ import annotations

import pytest

from gunpla_official_news import verification as V


# ---------------------------------------------------------------------------
# The two vocabularies
# ---------------------------------------------------------------------------


def test_source_tiers_are_exactly_the_documented_five_in_order():
    assert V.SOURCE_TIERS == (
        "official",
        "primary_retail",
        "credible_community_official",
        "competitor_uncited",
        "community",
    )


def test_confidence_labels_are_exactly_the_documented_four_in_order():
    assert V.CONFIDENCE_LABELS == ("High", "Medium", "Low", "RUMOR")


def test_confidence_rank_orders_labels_strongest_first():
    ranks = [V.CONFIDENCE_RANK[label] for label in V.CONFIDENCE_LABELS]
    assert ranks == sorted(ranks, reverse=True)


# ---------------------------------------------------------------------------
# Tier classification -- one fixture URL per tier
# ---------------------------------------------------------------------------

TIER_FIXTURES = [
    # (url, cites_official, expected tier)
    ("https://en.gundam-official.com/news/1001", False, "official"),
    ("https://global.bandai-hobby.net/en-us/site/gbase_worldtour/", False, "official"),
    ("https://www.hlj.com/1-100-mg-freedom-bans64213", False, "primary_retail"),
    ("https://www.reddit.com/r/Gunpla/comments/def456/", True, "credible_community_official"),
    ("https://gundamkitscollection.com/2026/09/mg-sazabi.html", False, "competitor_uncited"),
    ("https://www.reddit.com/r/Gunpla/comments/abc123/", False, "community"),
    ("https://www.youtube.com/watch?v=xyz", False, "community"),
]


@pytest.mark.parametrize("url,cites,expected", TIER_FIXTURES)
def test_classify_source_tier(url, cites, expected):
    assert V.classify_source_tier(url, cites_official=cites) == expected


def test_every_tier_is_reachable_from_a_fixture():
    produced = {
        V.classify_source_tier(u, cites_official=c) for u, c, _ in TIER_FIXTURES
    }
    assert produced == set(V.SOURCE_TIERS)


def test_competitor_with_an_official_link_is_promoted_not_trusted_outright():
    url = "https://gundamkitscollection.com/2026/09/mg-sazabi.html"
    assert V.classify_source_tier(url, cites_official=True) == "credible_community_official"


def test_unknown_host_defaults_to_community_never_official():
    assert V.classify_source_tier("https://totally-made-up.example/x") == "community"
    assert V.classify_source_tier("") == "community"
    assert V.classify_source_tier("not a url") == "community"


def test_is_official_url_still_uses_the_config_allowlist():
    assert V.is_official_url("https://www.gundam.info/news/1") is True
    assert V.is_official_url("https://reddit.com/r/Gunpla") is False
    assert V.is_official_url("") is False


# ---------------------------------------------------------------------------
# Mandatory checks before High
# ---------------------------------------------------------------------------


def test_unanswered_checklist_fails_closed():
    assert V.mandatory_checks_before_high(V.MandatoryChecks()) is False


def test_gate_requires_having_opened_the_page():
    checks = V.MandatoryChecks(opened_source_page=False, competitor_corroborated=True)
    assert V.mandatory_checks_before_high(checks) is False


def test_gate_requires_corroboration_when_the_only_source_is_a_competitor():
    opened_only = V.MandatoryChecks(opened_source_page=True)
    assert V.mandatory_checks_before_high(opened_only, only_source_is_competitor=False) is True
    assert V.mandatory_checks_before_high(opened_only, only_source_is_competitor=True) is False

    corroborated = V.MandatoryChecks(opened_source_page=True, competitor_corroborated=True)
    assert V.mandatory_checks_before_high(corroborated, only_source_is_competitor=True) is True


def test_failing_the_gate_downgrades_an_official_source():
    assert (
        V.assess_confidence("official", checks=V.MandatoryChecks(opened_source_page=True))
        == "High"
    )
    # Same tier, page never opened -> must NOT be High.
    assert V.assess_confidence("official", checks=V.MandatoryChecks()) == "Medium"


# ---------------------------------------------------------------------------
# Confidence labels -- one fixture per label
# ---------------------------------------------------------------------------

OPENED = V.MandatoryChecks(opened_source_page=True)

LABEL_FIXTURES = [
    # High: official page, opened myself
    ("High", dict(source_tier="official", checks=OPENED)),
    # High: primary retail confirming availability with a date/price
    (
        "High",
        dict(
            source_tier="primary_retail",
            checks=OPENED,
            has_confirmed_date_or_price=True,
            is_first_reveal=False,
        ),
    ),
    # Medium: primary retail, but it is a FIRST REVEAL, not availability
    (
        "Medium",
        dict(
            source_tier="primary_retail",
            checks=OPENED,
            has_confirmed_date_or_price=True,
            is_first_reveal=True,
        ),
    ),
    # Medium: credible community with a direct official link
    ("Medium", dict(source_tier="credible_community_official", checks=OPENED)),
    # Low: competitor with no independent official confirmation
    (
        "Low",
        dict(source_tier="competitor_uncited", checks=OPENED, only_source_is_competitor=True),
    ),
    # RUMOR: a single community post
    ("RUMOR", dict(source_tier="community", checks=OPENED, corroborating_posts=1)),
]


@pytest.mark.parametrize("expected,kwargs", LABEL_FIXTURES)
def test_assess_confidence_labels(expected, kwargs):
    tier = kwargs.pop("source_tier")
    assert V.assess_confidence(tier, **kwargs) == expected


def test_every_label_is_reachable_from_a_fixture():
    assert {label for label, _ in LABEL_FIXTURES} == set(V.CONFIDENCE_LABELS)


def test_community_reaches_medium_only_via_the_three_post_or_citation_rule():
    base = dict(checks=OPENED)
    assert V.assess_confidence("community", corroborating_posts=2, **base) == "RUMOR"
    assert V.assess_confidence("community", corroborating_posts=3, **base) == "Medium"
    assert (
        V.assess_confidence("community", corroborating_posts=0, cites_official=True, **base)
        == "Medium"
    )


def test_community_never_reaches_high():
    for n in (0, 1, 3, 50):
        assert (
            V.assess_confidence(
                "community", checks=OPENED, corroborating_posts=n, cites_official=True
            )
            != "High"
        )


def test_unknown_tier_is_rejected_loudly():
    with pytest.raises(ValueError):
        V.assess_confidence("totally_official_trust_me", checks=OPENED)


# ---------------------------------------------------------------------------
# Reddit consensus rule
# ---------------------------------------------------------------------------


def test_three_corroborating_posts_are_required():
    assert V.REDDIT_MIN_CORROBORATING_POSTS == 3
    two = V.reddit_consensus([{"id": "a"}, {"id": "b"}])
    assert two.corroborated is False
    assert two.corroborating_posts == 2

    three = V.reddit_consensus([{"id": "a"}, {"id": "b"}, {"id": "c"}])
    assert three.corroborated is True
    assert three.corroborating_posts == 3


def test_a_single_post_citing_official_material_is_enough():
    one = V.reddit_consensus([{"id": "a", "cites_official": True}])
    assert one.corroborated is True
    assert one.cites_official is True


def test_off_topic_posts_do_not_count_toward_the_three():
    posts = [{"id": "a"}, {"id": "b"}, {"id": "c", "off_topic": True}]
    assert V.reddit_consensus(posts).corroborated is False


def test_mod_role_alone_does_not_replace_the_three_source_rule():
    posts = [{"id": "a", "author_flair": "mod", "high_credibility": True}]
    result = V.reddit_consensus(posts)
    assert result.corroborated is False


def test_unreachable_reddit_degrades_and_does_not_raise():
    """AC2: Reddit unreachable -> community_consensus 'unavailable', NOT an error."""
    result = V.reddit_consensus(None, reachable=False)  # must not raise
    assert result.available is False
    assert result.unavailable is True
    assert result.community_consensus.startswith("unavailable")
    assert V.is_consensus_unavailable(result.community_consensus)
    assert result.corroborated is False
    assert result.corroborating_posts == 0


def test_unavailable_marker_is_ascii_and_recognised():
    assert V.COMMUNITY_CONSENSUS_UNAVAILABLE.startswith("unavailable")
    V.COMMUNITY_CONSENSUS_UNAVAILABLE.encode("ascii")  # would raise if not ASCII
    assert V.is_consensus_unavailable("Unavailable - Reddit blocked") is True
    assert V.is_consensus_unavailable("corroborated: 3 post(s) agree") is False
    assert V.is_consensus_unavailable("") is False


def test_reachable_but_empty_is_not_the_unavailable_marker():
    result = V.reddit_consensus([], reachable=True)
    assert result.available is True
    assert not V.is_consensus_unavailable(result.community_consensus)
