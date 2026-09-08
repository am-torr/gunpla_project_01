"""Verified Brief renderer (ARCHITECTURE.md section 5, "Markdown brief").

Layout:

    # Gunpla News Brief <EM DASH> YYYY-MM-DD
    ## Verified Brief      (or ## Focused Brief when a topic filter is active)
    ## Viability Check     (confidence table)
    ## Image Assets        (verified URLs with reuse flag)
    ## Sources             (all source URLs)

RUMOR items are excluded from the brief body unless ``include_rumors=True``
(ARCHITECTURE.md section 3, "Never output in Verified Brief"); they still appear in
the Viability Check so the exclusion is auditable rather than invisible.

The title uses a literal em dash to match the spec.  It is written as ``\\u2014`` in
source so this .py file stays pure ASCII for the cp1252 console, and every write
passes ``encoding="utf-8"`` so the dash survives to disk.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from .images import REUSE_NOT_PERMITTED
from .models import WorkingDataRow
from .verification import CONFIDENCE_RUMOR
from .working_data import sort_rows

#: U+2014. Written as an escape so this source file stays pure ASCII (cp1252 console)
#: while the emitted .md -- always opened with encoding="utf-8" -- carries the real dash.
EM_DASH = "\u2014"


def _cell(value: str) -> str:
    text = ("" if value is None else str(value)).strip()
    return text.replace("|", "\\|") if text else "-"


def render_brief(
    rows: Sequence[WorkingDataRow],
    *,
    date: str,
    topic: Optional[str] = None,
    include_rumors: bool = False,
) -> str:
    ordered = sort_rows(rows)
    focused = bool(topic)
    body_rows = [
        r for r in ordered if include_rumors or r.confidence != CONFIDENCE_RUMOR
    ]

    out: list = []
    out.append("# Gunpla News Brief %s %s" % (EM_DASH, date))
    out.append("")

    # -- brief body ---------------------------------------------------------
    if focused:
        out.append("## Focused Brief")
        out.append("")
        out.append("Topic filter: `%s`" % topic)
    else:
        out.append("## Verified Brief")
    out.append("")

    if not body_rows:
        out.append("_No verified items for this run._")
        out.append("")
    for row in body_rows:
        out.append("### %s" % (row.kit_item or "(untitled)"))
        out.append("")
        out.append(
            "- **Series / Grade:** %s / %s" % (_cell(row.series), _cell(row.grade_type))
        )
        out.append(
            "- **Release / MSRP / Exclusivity:** %s / %s / %s"
            % (_cell(row.release), _cell(row.msrp), _cell(row.exclusivity))
        )
        out.append(
            "- **Confidence / Source tier:** %s / %s"
            % (_cell(row.confidence), _cell(row.source_tier))
        )
        out.append("- **Why it matters:** %s" % _cell(row.context_hook))
        out.append("- **UG's take:** %s" % _cell(row.ug_take))
        out.append("- **Community consensus:** %s" % _cell(row.community_consensus))
        out.append("- **Engagement question:** %s" % _cell(row.engagement_question))
        out.append("- **Source:** %s" % _cell(row.source_url))
        out.append("")

    # -- viability check ----------------------------------------------------
    out.append("## Viability Check")
    out.append("")
    out.append("| kit_item | confidence | source_tier | image_checked | in_brief |")
    out.append("| --- | --- | --- | --- | --- |")
    for row in ordered:
        in_brief = "yes" if (include_rumors or row.confidence != CONFIDENCE_RUMOR) else "no (RUMOR)"
        out.append(
            "| %s | %s | %s | %s | %s |"
            % (
                _cell(row.kit_item),
                _cell(row.confidence),
                _cell(row.source_tier),
                "true" if row.image_checked else "false",
                in_brief,
            )
        )
    out.append("")

    # -- image assets -------------------------------------------------------
    out.append("## Image Assets")
    out.append("")
    any_image = False
    for row in ordered:
        urls = [u for u in (row.image_url_1, row.image_url_2, row.image_url_3) if u]
        if not urls:
            continue
        any_image = True
        flag = REUSE_NOT_PERMITTED if row.reuse_not_permitted else "reuse_unassessed"
        out.append("- **%s** (`image_checked=%s`, `%s`)" % (
            _cell(row.kit_item), "true" if row.image_checked else "false", flag
        ))
        for url in urls:
            out.append("  - %s" % url)
    if not any_image:
        out.append("_No HEAD-verified images for this run._")
    out.append("")

    # -- sources ------------------------------------------------------------
    out.append("## Sources")
    out.append("")
    seen: set = set()
    for row in ordered:
        if row.source_url and row.source_url not in seen:
            seen.add(row.source_url)
            out.append("- %s" % row.source_url)
    if not seen:
        out.append("_No sources._")
    out.append("")

    return "\n".join(out)


def write_brief(
    rows: Sequence[WorkingDataRow],
    path: Path,
    *,
    date: str,
    topic: Optional[str] = None,
    include_rumors: bool = False,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_brief(rows, date=date, topic=topic, include_rumors=include_rumors)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path
