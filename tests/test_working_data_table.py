"""Working Data table: render, sort, and the markdown -> JSON export path."""
from __future__ import annotations

import json

import pytest

from gunpla_official_news.models import WORKING_DATA_COLUMNS, WorkingDataRow
from gunpla_official_news import working_data as W


def row(**kw) -> WorkingDataRow:
    base = dict(kit_item="kit", confidence="High", date_published="2026-01-01")
    base.update(kw)
    return WorkingDataRow(**base)


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def test_sorts_by_confidence_desc_then_date_desc():
    rows = [
        row(kit_item="low-new", confidence="Low", date_published="2026-09-09"),
        row(kit_item="high-old", confidence="High", date_published="2026-01-01"),
        row(kit_item="rumor", confidence="RUMOR", date_published="2026-12-31"),
        row(kit_item="high-new", confidence="High", date_published="2026-09-04"),
        row(kit_item="medium", confidence="Medium", date_published="2026-05-05"),
    ]
    assert [r.kit_item for r in W.sort_rows(rows)] == [
        "high-new",
        "high-old",
        "medium",
        "low-new",
        "rumor",
    ]


def test_missing_date_sorts_last_within_its_confidence_band():
    rows = [
        row(kit_item="no-date", confidence="High", date_published=""),
        row(kit_item="dated", confidence="High", date_published="2026-02-02"),
    ]
    assert [r.kit_item for r in W.sort_rows(rows)] == ["dated", "no-date"]


def test_unknown_confidence_sorts_below_rumor_rather_than_crashing():
    rows = [row(confidence="RUMOR", kit_item="r"), row(confidence="???", kit_item="x")]
    assert [r.kit_item for r in W.sort_rows(rows)] == ["r", "x"]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_header_is_the_documented_column_list():
    table = W.render_markdown_table([row()])
    header = table.splitlines()[0]
    assert header == "| " + " | ".join(WORKING_DATA_COLUMNS) + " |"


def test_every_row_has_one_cell_per_column():
    table = W.render_markdown_table([row(), row(kit_item="b")])
    for line in table.splitlines()[2:]:
        cells = line.strip().strip("|").split("|")
        assert len(cells) == len(WORKING_DATA_COLUMNS)


def test_pipes_inside_a_cell_are_escaped_so_the_table_stays_parseable():
    table = W.render_markdown_table([row(kit_item="A | B")])
    parsed = W.parse_markdown_table(table)
    assert parsed[0]["kit_item"] == "A | B"


# ---------------------------------------------------------------------------
# Parsing (the export_json.py logic)
# ---------------------------------------------------------------------------


def test_markdown_round_trips_back_into_json_objects():
    original = row(
        kit_item="MGEX Strike Freedom",
        series="SEED",
        confidence="High",
        source_tier="official",
        image_checked=True,
        image_url_1="https://x.example/media/a.jpg",
        ug_take="LED frame is the point",
        community_consensus="corroborated: 3 post(s) agree",
        engagement_question="Worth it?",
    )
    table = W.render_markdown_table([original])
    records = W.parse_markdown_table(table)
    assert len(records) == 1
    rec = records[0]
    assert rec["kit_item"] == "MGEX Strike Freedom"
    assert rec["UG_take"] == "LED frame is the point"
    assert rec["image_checked"] is True
    assert rec["ImageURL1"] == "https://x.example/media/a.jpg"
    # Placeholder cells decode back to empty strings, not to "-".
    assert rec["msrp"] == ""


def test_rows_from_markdown_reconstructs_the_column_values():
    original = row(kit_item="Kit X", series="UNICORN", msrp="4,400 yen")
    restored = W.rows_from_markdown(W.render_markdown_table([original]))[0]
    assert restored.kit_item == "Kit X"
    assert restored.series == "UNICORN"
    assert restored.msrp == "4,400 yen"


def test_a_wrong_header_is_rejected_rather_than_silently_accepted():
    bad = "| kit_item | series |\n| --- | --- |\n| a | b |\n"
    with pytest.raises(ValueError, match="header mismatch"):
        W.parse_markdown_table(bad)


def test_a_short_row_is_rejected():
    good = W.render_markdown_table([row()])
    broken = good.rstrip("\n") + "\n| only | two |\n"
    with pytest.raises(ValueError, match="expected"):
        W.parse_markdown_table(broken)


def test_no_table_at_all_is_an_error():
    with pytest.raises(ValueError, match="no markdown table"):
        W.parse_markdown_table("# Just a heading\n\nsome prose\n")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_writes_utf8_and_json_matches_the_markdown(tmp_path):
    rows = [
        row(kit_item="MGEX Strike Freedom", confidence="High", date_published="2026-09-04"),
        row(kit_item="PG Unicorn leak", confidence="RUMOR", date_published="2026-08-25"),
    ]
    md = W.write_markdown(rows, tmp_path / "working_data_2026-09-06.md")
    js = W.export_json_from_markdown(md, tmp_path / "working_data_2026-09-06.json")

    with open(js, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    assert [r["kit_item"] for r in payload] == ["MGEX Strike Freedom", "PG Unicorn leak"]

    # export_json() (rows -> JSON directly) must agree with the markdown-derived one.
    direct = W.export_json(rows, tmp_path / "direct.json")
    with open(direct, "r", encoding="utf-8") as fh:
        assert json.load(fh) == payload


def test_non_ascii_survives_the_round_trip(tmp_path):
    kit = "MG \u30e6\u30cb\u30b3\u30fc\u30f3 Ver.Ka"  # Japanese kit name
    md = W.write_markdown([row(kit_item=kit)], tmp_path / "wd.md")
    js = W.export_json_from_markdown(md, tmp_path / "wd.json")
    with open(js, "r", encoding="utf-8") as fh:
        assert json.load(fh)[0]["kit_item"] == kit
