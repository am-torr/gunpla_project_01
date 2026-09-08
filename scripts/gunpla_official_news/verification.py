"""Source-tier and confidence rules from ARCHITECTURE.md section 3.

Three things live here:

1. ``is_official_url``   -- the pre-existing official-domain allowlist check.
                            Behaviour is UNCHANGED; scrapers call it via
                            ``template.BaseScraper.drop_unofficial``.
2. Two-axis labelling    -- ``classify_source_tier`` (5 tiers) and
                            ``assess_confidence`` (4 labels), including the
                            "mandatory checks before marking High" gate.
3. Reddit consensus      -- the >=3-corroborating-posts-or-official-citation rule,
                            which DEGRADES (never raises) when Reddit is unreachable.

All strings here are ASCII on purpose: this box's console is cp1252 and a stray
em dash in a log line silently mangles output.  The em dashes that ARCHITECTURE.md
uses in *file output* are emitted from ``brief.py`` via explicit \\u escapes instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence
from urllib.parse import urlparse

from .config import OFFICIAL_DOMAINS

# ---------------------------------------------------------------------------
# Pre-existing behaviour (unchanged)
# ---------------------------------------------------------------------------


def is_official_url(url: str) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


# ---------------------------------------------------------------------------
# Axis 1: source tier (ARCHITECTURE.md section 3, "Source tiers")
# ---------------------------------------------------------------------------

TIER_OFFICIAL = "official"
TIER_PRIMARY_RETAIL = "primary_retail"
TIER_CREDIBLE_COMMUNITY_OFFICIAL = "credible_community_official"
TIER_COMPETITOR_UNCITED = "competitor_uncited"
TIER_COMMUNITY = "community"

#: The five tiers, in the documented order.
SOURCE_TIERS: tuple[str, ...] = (
    TIER_OFFICIAL,
    TIER_PRIMARY_RETAIL,
    TIER_CREDIBLE_COMMUNITY_OFFICIAL,
    TIER_COMPETITOR_UNCITED,
    TIER_COMMUNITY,
)

#: Registered-ish hostnames per tier. Matching is suffix-aware (``endswith('.' + d)``)
#: so ``en.gundam-official.com`` matches ``gundam-official.com``.
OFFICIAL_TIER_DOMAINS: tuple[str, ...] = tuple(OFFICIAL_DOMAINS) + (
    "gundam-official.com",
    "global.bandai-hobby.net",
    "bandainamcofilmworks.co.jp",
    "bandainamco-am.co.jp",
)

PRIMARY_RETAIL_DOMAINS: tuple[str, ...] = (
    "hlj.com",
    "gundamplanet.com",
    "toy-people.com",
    "essentialjapan.com",
    "amiami.com",
)

#: "Gundam Kits Collection, Gundam News without official link" -- leads only.
COMPETITOR_DOMAINS: tuple[str, ...] = (
    "gundamkitscollection.com",
    "gunjap.net",
    "gundamnews.tv",
    "ngeekhiong.blogspot.com",
)

#: "Reddit without official link, YouTube, forums" -- rumour unless corroborated.
COMMUNITY_DOMAINS: tuple[str, ...] = (
    "reddit.com",
    "redd.it",
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "gundamforums.com",
    "forums.gunpla.com",
)


def _host(url: str) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _host_in(host: str, domains: Iterable[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def classify_source_tier(url: str, *, cites_official: bool = False) -> str:
    """Return one of :data:`SOURCE_TIERS` for ``url``.

    ``cites_official`` means the post/article carries a direct link to official or
    primary-retail primary material.  Per ARCHITECTURE.md that is exactly what
    promotes a Reddit/community or competitor page to
    ``credible_community_official`` -- "Reddit/GKC with direct official link".

    An unrecognised host is treated as ``community`` (leads only), never as
    official: the allowlist is the thing that grants trust, not the absence of a
    denylist entry.
    """
    host = _host(url)
    if not host:
        return TIER_COMMUNITY
    if _host_in(host, OFFICIAL_TIER_DOMAINS):
        return TIER_OFFICIAL
    if _host_in(host, PRIMARY_RETAIL_DOMAINS):
        return TIER_PRIMARY_RETAIL
    if _host_in(host, COMPETITOR_DOMAINS):
        return TIER_CREDIBLE_COMMUNITY_OFFICIAL if cites_official else TIER_COMPETITOR_UNCITED
    if _host_in(host, COMMUNITY_DOMAINS):
        return TIER_CREDIBLE_COMMUNITY_OFFICIAL if cites_official else TIER_COMMUNITY
    return TIER_CREDIBLE_COMMUNITY_OFFICIAL if cites_official else TIER_COMMUNITY


# ---------------------------------------------------------------------------
# Axis 2: confidence label (ARCHITECTURE.md section 3, "Confidence labels")
# ---------------------------------------------------------------------------

CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"
CONFIDENCE_RUMOR = "RUMOR"

#: The four labels, strongest first.
CONFIDENCE_LABELS: tuple[str, ...] = (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_RUMOR,
)

#: Sort weight for ARCHITECTURE.md section 5 ("sort by confidence desc").
CONFIDENCE_RANK: dict[str, int] = {
    CONFIDENCE_HIGH: 3,
    CONFIDENCE_MEDIUM: 2,
    CONFIDENCE_LOW: 1,
    CONFIDENCE_RUMOR: 0,
}


@dataclass
class MandatoryChecks:
    """ARCHITECTURE.md section 3, "Mandatory checks before marking High".

    * ``opened_source_page``       -- "Did I open the official or primary retail page myself?"
    * ``competitor_corroborated``  -- "If the only source is a competitor, did I find
      the same fact on official/primary retail?"  ``None`` means "not answered".

    Defaults are the *unsafe* answers on purpose: an unanswered checklist must
    fail closed, so nothing reaches ``High`` by omission.
    """

    opened_source_page: bool = False
    competitor_corroborated: Optional[bool] = None

    def passes(self, *, only_source_is_competitor: bool = False) -> bool:
        if not self.opened_source_page:
            return False
        if only_source_is_competitor and self.competitor_corroborated is not True:
            return False
        return True


def mandatory_checks_before_high(
    checks: MandatoryChecks,
    *,
    only_source_is_competitor: bool = False,
) -> bool:
    """Gate function: True only when every mandatory check is satisfied."""
    return checks.passes(only_source_is_competitor=only_source_is_competitor)


def assess_confidence(
    source_tier: str,
    *,
    checks: Optional[MandatoryChecks] = None,
    is_first_reveal: bool = False,
    has_confirmed_date_or_price: bool = False,
    corroborating_posts: int = 0,
    cites_official: bool = False,
    only_source_is_competitor: bool = False,
) -> str:
    """Map a source tier plus evidence onto one of :data:`CONFIDENCE_LABELS`.

    Rules, verbatim from ARCHITECTURE.md section 1 (Level 3) and section 3:

    * ``official`` + live page verified            -> High
    * ``primary_retail`` with confirmed date/price -> High for availability,
                                                      Medium for first reveals
    * ``competitor_uncited`` without official link -> Low  (RUMOR-adjacent; excluded
                                                      from the Verified Brief by
                                                      ``brief.py``, not by this label)
    * single Reddit post                           -> RUMOR unless 3+ sources or an
                                                      official link is cited
    * failing the mandatory checks                 -> downgrade

    ``checks`` defaults to an all-unanswered checklist, i.e. fail closed.
    """
    if source_tier not in SOURCE_TIERS:
        raise ValueError(
            "unknown source_tier %r; expected one of %s" % (source_tier, SOURCE_TIERS)
        )
    checks = checks or MandatoryChecks()
    gate_ok = mandatory_checks_before_high(
        checks, only_source_is_competitor=only_source_is_competitor
    )

    if source_tier == TIER_OFFICIAL:
        # "Official or primary retail confirms it; I checked the page myself"
        return CONFIDENCE_HIGH if gate_ok else CONFIDENCE_MEDIUM

    if source_tier == TIER_PRIMARY_RETAIL:
        if not gate_ok:
            return CONFIDENCE_LOW
        if is_first_reveal:
            # "Primary retail confirms availability but not first reveal"
            return CONFIDENCE_MEDIUM
        return CONFIDENCE_HIGH if has_confirmed_date_or_price else CONFIDENCE_MEDIUM

    if source_tier == TIER_CREDIBLE_COMMUNITY_OFFICIAL:
        # "credible community corroboration" -> Medium, never High on its own.
        return CONFIDENCE_MEDIUM

    if source_tier == TIER_COMPETITOR_UNCITED:
        # "Competitor/community source without independent official confirmation"
        return CONFIDENCE_LOW

    # TIER_COMMUNITY
    if cites_official or corroborating_posts >= REDDIT_MIN_CORROBORATING_POSTS:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_RUMOR


# ---------------------------------------------------------------------------
# Reddit / community consensus (ARCHITECTURE.md section 3)
# ---------------------------------------------------------------------------

#: ">=3 separate posts/comments corroborating same fact"
REDDIT_MIN_CORROBORATING_POSTS = 3

#: Emitted verbatim into ``community_consensus`` when Reddit cannot be reached.
#: ARCHITECTURE.md spells it with an em dash; we keep the file ASCII (cp1252 console)
#: and only require callers to test ``startswith("unavailable")``.
COMMUNITY_CONSENSUS_UNAVAILABLE = "unavailable - Reddit blocked"


def is_consensus_unavailable(value: str) -> bool:
    """True when ``value`` is the degraded 'unavailable' marker."""
    return bool(value) and value.strip().lower().startswith("unavailable")


@dataclass
class ConsensusResult:
    """Outcome of the Reddit corroboration rule."""

    community_consensus: str
    corroborated: bool
    corroborating_posts: int
    cites_official: bool
    available: bool

    @property
    def unavailable(self) -> bool:
        return not self.available


def reddit_consensus(
    posts: Optional[Sequence[dict]] = None,
    *,
    reachable: bool = True,
    summary: str = "",
) -> ConsensusResult:
    """Apply the Reddit corroboration rule.

    ``posts`` is a sequence of dicts; a post counts as corroborating when it is not
    flagged ``off_topic`` and it either cites official material
    (``cites_official=True``) or simply restates the fact.

    DEGRADATION CONTRACT (AC2): when ``reachable`` is False -- Reddit blocked, DNS
    dead, 403 from the environment -- this returns
    ``community_consensus=COMMUNITY_CONSENSUS_UNAVAILABLE`` and continues.  It MUST
    NOT raise: ARCHITECTURE.md says "log as community_consensus: 'unavailable --
    Reddit blocked' and continue without it".  Callers that treat unreachability as
    an error re-introduce the exact failure this rule exists to prevent.
    """
    if not reachable:
        return ConsensusResult(
            community_consensus=COMMUNITY_CONSENSUS_UNAVAILABLE,
            corroborated=False,
            corroborating_posts=0,
            cites_official=False,
            available=False,
        )

    posts = list(posts or [])
    counted = [p for p in posts if not p.get("off_topic")]
    cites_official = any(bool(p.get("cites_official")) for p in counted)
    n = len(counted)

    # "High-credibility Reddit poster/mod role does NOT replace the 3-source rule
    # unless linking primary material" -- so role is deliberately not consulted here.
    corroborated = cites_official or n >= REDDIT_MIN_CORROBORATING_POSTS

    if summary:
        text = summary
    elif corroborated and cites_official:
        text = "corroborated: %d post(s), official source cited" % n
    elif corroborated:
        text = "corroborated: %d post(s) agree" % n
    elif n:
        text = "insufficient: %d post(s), needs %d or an official citation" % (
            n,
            REDDIT_MIN_CORROBORATING_POSTS,
        )
    else:
        text = "no community discussion found"

    return ConsensusResult(
        community_consensus=text,
        corroborated=corroborated,
        corroborating_posts=n,
        cites_official=cites_official,
        available=True,
    )
