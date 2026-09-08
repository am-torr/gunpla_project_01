"""Canonical schemas.

Two dataclasses live here:

* ``NewsItem``      -- the pre-existing raw-scrape record (UNCHANGED; scrapers and
                       ``dedupe.compute_source_record_hash`` depend on its field set).
* ``WorkingDataRow`` -- the ARCHITECTURE.md Working Data contract (section 1 / section 4).

Working Data column contract
----------------------------
ARCHITECTURE.md section 1 pins the column order verbatim::

    kit_item | series | grade_type | release | msrp | exclusivity | source_tier |
    confidence | source_url | context_hook | image_checked | ImageURL1 | ImageURL2 |
    ImageURL3 | UG's take | community_consensus | engagement_question

DOC-DISCREPANCY (recorded deliberately, do not "fix" silently)
    ARCHITECTURE.md's prose calls this an "18 columns, exact order" table, but the
    enumerated pipe-list it then gives -- and the JSON schema in section 4, which
    mirrors it key-for-key -- both contain 17 names.  The ENUMERATED LIST IS THE
    CONTRACT (it is the thing that says "exact order"); the "18" is an off-by-one in
    the prose header.  ``WORKING_DATA_COLUMNS`` therefore has 17 entries and
    ``test_models_working_data.py`` pins both the list and this discrepancy so a
    future reader cannot mistake it for an omission.  See CONTRACT-NOTES.md.

Two of the columns are not valid Python identifiers, so the dataclass uses safe field
names and the module carries the mapping in three parallel, index-aligned tuples:

    WORKING_DATA_FIELDS[i]  <-> WORKING_DATA_COLUMNS[i]  <-> WORKING_DATA_JSON_KEYS[i]

    ug_take      -> "UG's take"  (markdown header)  -> "UG_take"   (JSON key, section 4)
    image_url_1  -> "ImageURL1"                     -> "ImageURL1"
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields as dataclass_fields
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class NewsItem:
    source_name: str = ""
    source_url: str = ""
    source_type: str = "news_article"  # news_article|product_page|event_page|social_post
    region: str = ""
    language: str = ""

    headline: str = ""
    body_summary: str = ""

    announcement_type: str = "new_kit"  # new_kit|reissue|accessory|event|campaign|price_change

    product_name_official: Optional[str] = None
    line: Optional[str] = None
    grade: Optional[str] = None
    scale: Optional[str] = None
    series: Optional[str] = None
    limited_flag: bool = False
    category: Optional[str] = None

    preorder_open_at: Optional[str] = None
    preorder_close_at: Optional[str] = None
    release_month: Optional[str] = None

    price_local: Optional[float] = None
    currency: Optional[str] = None
    stock_status: Optional[str] = None

    event_name: Optional[str] = None
    event_type: Optional[str] = None
    event_start_at: Optional[str] = None
    event_end_at: Optional[str] = None
    location: Optional[str] = None

    images: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    sources: list = field(default_factory=list)

    canonical_product_id: Optional[str] = None
    scraped_at: str = ""
    source_record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_item(**overrides: Any) -> NewsItem:
    """Factory that stamps scraped_at and applies overrides."""
    item = NewsItem(scraped_at=_now_iso())
    for k, v in overrides.items():
        if hasattr(item, k):
            setattr(item, k, v)
    return item


# ---------------------------------------------------------------------------
# Working Data contract (ARCHITECTURE.md sections 1, 4 and 5)
# ---------------------------------------------------------------------------

#: Markdown table headers, in the exact documented order.
WORKING_DATA_COLUMNS: tuple[str, ...] = (
    "kit_item",
    "series",
    "grade_type",
    "release",
    "msrp",
    "exclusivity",
    "source_tier",
    "confidence",
    "source_url",
    "context_hook",
    "image_checked",
    "ImageURL1",
    "ImageURL2",
    "ImageURL3",
    "UG's take",
    "community_consensus",
    "engagement_question",
)

#: Dataclass attribute names, index-aligned with WORKING_DATA_COLUMNS.
WORKING_DATA_FIELDS: tuple[str, ...] = (
    "kit_item",
    "series",
    "grade_type",
    "release",
    "msrp",
    "exclusivity",
    "source_tier",
    "confidence",
    "source_url",
    "context_hook",
    "image_checked",
    "image_url_1",
    "image_url_2",
    "image_url_3",
    "ug_take",
    "community_consensus",
    "engagement_question",
)

#: JSON keys per ARCHITECTURE.md section 4, index-aligned with the two tuples above.
WORKING_DATA_JSON_KEYS: tuple[str, ...] = (
    "kit_item",
    "series",
    "grade_type",
    "release",
    "msrp",
    "exclusivity",
    "source_tier",
    "confidence",
    "source_url",
    "context_hook",
    "image_checked",
    "ImageURL1",
    "ImageURL2",
    "ImageURL3",
    "UG_take",
    "community_consensus",
    "engagement_question",
)

#: The count ARCHITECTURE.md's prose claims, kept so the discrepancy stays visible.
ARCHITECTURE_CLAIMED_COLUMN_COUNT = 18

#: Placeholder used for empty string cells (ARCHITECTURE.md section 4: "TBA or -").
EMPTY_CELL = "-"


@dataclass
class WorkingDataRow:
    """One Working Data entry.

    The first 17 fields are the documented columns, in the documented order.
    Everything declared after ``_METADATA_SENTINEL`` is metadata that the pipeline
    needs but that is deliberately NOT a table column:

    * ``date_published`` -- ARCHITECTURE.md section 5 sorts by it, yet it is not in
      the column list; keeping it off the table and on the row is what lets both
      rules hold at once.
    * ``reuse_not_permitted`` -- section 3 says to flag this "in metadata".
    """

    # -- the 17 documented columns, in documented order -----------------------
    kit_item: str = ""
    series: str = ""
    grade_type: str = ""
    release: str = ""
    msrp: str = ""
    exclusivity: str = ""
    source_tier: str = ""
    confidence: str = ""
    source_url: str = ""
    context_hook: str = ""
    image_checked: bool = False
    image_url_1: str = ""
    image_url_2: str = ""
    image_url_3: str = ""
    ug_take: str = ""
    community_consensus: str = ""
    engagement_question: str = ""

    # -- metadata (never rendered as a column) --------------------------------
    date_published: str = ""
    reuse_not_permitted: bool = False
    source_name: str = ""
    notes: list = field(default_factory=list)

    # ---- serialization ----
    def to_dict(self) -> dict[str, Any]:
        """Full record including metadata (superset of the JSON export)."""
        return asdict(self)

    def to_json_dict(self) -> dict[str, Any]:
        """The ARCHITECTURE.md section 4 JSON object: 17 keys, documented order."""
        out: dict[str, Any] = {}
        for fname, jkey in zip(WORKING_DATA_FIELDS, WORKING_DATA_JSON_KEYS):
            out[jkey] = getattr(self, fname)
        return out

    def to_cells(self) -> list[str]:
        """Markdown cell values, index-aligned with WORKING_DATA_COLUMNS."""
        cells: list[str] = []
        for fname in WORKING_DATA_FIELDS:
            value = getattr(self, fname)
            if isinstance(value, bool):
                cells.append("true" if value else "false")
            else:
                text = "" if value is None else str(value)
                cells.append(text if text.strip() else EMPTY_CELL)
        return cells

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> "WorkingDataRow":
        """Inverse of :meth:`to_json_dict` (round-trip safe for the 17 columns)."""
        kwargs: dict[str, Any] = {}
        for fname, jkey in zip(WORKING_DATA_FIELDS, WORKING_DATA_JSON_KEYS):
            if jkey in data:
                kwargs[fname] = data[jkey]
        # Metadata is carried through when present so full-record round trips work too.
        for extra in ("date_published", "reuse_not_permitted", "source_name", "notes"):
            if extra in data:
                kwargs[extra] = data[extra]
        return cls(**kwargs)


def new_working_row(**overrides: Any) -> WorkingDataRow:
    """Factory mirroring :func:`new_item`: unknown keys are ignored, not fatal."""
    row = WorkingDataRow()
    known = {f.name for f in dataclass_fields(row)}
    for k, v in overrides.items():
        if k in known:
            setattr(row, k, v)
    return row
