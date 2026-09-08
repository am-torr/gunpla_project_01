"""AC1 -- the Working Data schema and its lossless JSON round trip."""
from __future__ import annotations

import json
from dataclasses import fields as dataclass_fields

import pytest

from gunpla_official_news.models import (
    ARCHITECTURE_CLAIMED_COLUMN_COUNT,
    WORKING_DATA_COLUMNS,
    WORKING_DATA_FIELDS,
    WORKING_DATA_JSON_KEYS,
    WorkingDataRow,
    new_working_row,
)

#: Verbatim from ARCHITECTURE.md section 1 (Level 3, "Build Working Data table").
DOCUMENTED_ORDER = (
    "kit_item | series | grade_type | release | msrp | exclusivity | source_tier | "
    "confidence | source_url | context_hook | image_checked | ImageURL1 | ImageURL2 | "
    "ImageURL3 | UG's take | community_consensus | engagement_question"
)


def test_columns_match_the_documented_order_exactly():
    expected = tuple(part.strip() for part in DOCUMENTED_ORDER.split("|"))
    assert WORKING_DATA_COLUMNS == expected


def test_documented_column_list_is_authoritative_over_the_18_count():
    """ARCHITECTURE.md's prose says "18 columns" but enumerates 17 names.

    The enumerated list is the contract (it is the thing labelled "exact order")
    and section 4's JSON schema independently corroborates it, key for key.  This
    test pins BOTH facts so the mismatch cannot be mistaken for a dropped column.
    """
    assert len(WORKING_DATA_COLUMNS) == 17
    assert ARCHITECTURE_CLAIMED_COLUMN_COUNT == 18
    # Section 4's JSON schema has exactly the same cardinality as section 1's table.
    assert len(WORKING_DATA_JSON_KEYS) == len(WORKING_DATA_COLUMNS)


def test_three_name_tuples_stay_index_aligned():
    assert len(WORKING_DATA_FIELDS) == len(WORKING_DATA_COLUMNS)
    assert len(WORKING_DATA_JSON_KEYS) == len(WORKING_DATA_COLUMNS)
    # The two names that are not valid Python identifiers are the only ones that differ.
    differing = {
        (c, f, j)
        for c, f, j in zip(WORKING_DATA_COLUMNS, WORKING_DATA_FIELDS, WORKING_DATA_JSON_KEYS)
        if not (c == f == j)
    }
    assert differing == {
        ("ImageURL1", "image_url_1", "ImageURL1"),
        ("ImageURL2", "image_url_2", "ImageURL2"),
        ("ImageURL3", "image_url_3", "ImageURL3"),
        ("UG's take", "ug_take", "UG_take"),
    }


def test_dataclass_declares_the_columns_first_and_in_order():
    declared = [f.name for f in dataclass_fields(WorkingDataRow)]
    assert tuple(declared[: len(WORKING_DATA_FIELDS)]) == WORKING_DATA_FIELDS


def test_metadata_fields_are_not_columns():
    declared = {f.name for f in dataclass_fields(WorkingDataRow)}
    metadata = declared - set(WORKING_DATA_FIELDS)
    assert metadata == {"date_published", "reuse_not_permitted", "source_name", "notes"}
    for name in metadata:
        assert name not in WORKING_DATA_COLUMNS
        assert name not in WORKING_DATA_JSON_KEYS


@pytest.fixture()
def populated_row() -> WorkingDataRow:
    """Every one of the columns carries a distinct, non-default value."""
    return WorkingDataRow(
        kit_item="MGEX 1/100 Strike Freedom Gundam",
        series="SEED",
        grade_type="Kit",
        release="November 2026",
        msrp="27,500 yen",
        exclusivity="Retail",
        source_tier="official",
        confidence="High",
        source_url="https://en.gundam-official.com/news/1001",
        context_hook="First MGEX since the Unicorn Ver.Ka.",
        image_checked=True,
        image_url_1="https://en.gundam-official.com/media/a.jpg",
        image_url_2="https://en.gundam-official.com/media/b.jpg",
        image_url_3="https://en.gundam-official.com/media/c.png",
        ug_take="The internal LED frame is the whole point.",
        community_consensus="corroborated: 3 post(s) agree",
        engagement_question="Is an MGEX worth triple an MG?",
        date_published="2026-09-04",
        reuse_not_permitted=True,
        source_name="GUNDAM Official",
        notes=["reuse_not_permitted"],
    )


def test_to_json_dict_has_exactly_the_documented_keys_in_order(populated_row):
    payload = populated_row.to_json_dict()
    assert tuple(payload.keys()) == WORKING_DATA_JSON_KEYS


def test_json_round_trip_loses_nothing_on_the_columns(populated_row):
    """AC1: in-memory object -> exported JSON -> object, with no data loss."""
    encoded = json.dumps(populated_row.to_json_dict(), ensure_ascii=False)
    restored = WorkingDataRow.from_json_dict(json.loads(encoded))
    for name in WORKING_DATA_FIELDS:
        assert getattr(restored, name) == getattr(populated_row, name), name


def test_full_record_round_trip_also_preserves_metadata(populated_row):
    encoded = json.dumps(populated_row.to_dict(), ensure_ascii=False)
    restored = WorkingDataRow.from_json_dict(json.loads(encoded))
    # to_dict() uses field names, so the ImageURL/UG keys are not present; the
    # columns still survive because from_json_dict() also accepts field names.
    assert restored.date_published == populated_row.date_published
    assert restored.reuse_not_permitted is True
    assert restored.source_name == "GUNDAM Official"
    assert restored.notes == ["reuse_not_permitted"]


def test_image_checked_survives_as_a_real_boolean(populated_row):
    payload = populated_row.to_json_dict()
    assert payload["image_checked"] is True
    assert WorkingDataRow.from_json_dict(payload).image_checked is True

    empty = WorkingDataRow()
    assert empty.to_json_dict()["image_checked"] is False


def test_to_cells_is_column_aligned_and_placeholders_empties(populated_row):
    cells = populated_row.to_cells()
    assert len(cells) == len(WORKING_DATA_COLUMNS)
    assert cells[0] == "MGEX 1/100 Strike Freedom Gundam"
    assert cells[WORKING_DATA_COLUMNS.index("image_checked")] == "true"
    assert cells[WORKING_DATA_COLUMNS.index("UG's take")].startswith("The internal LED")
    blank = WorkingDataRow().to_cells()
    assert blank[0] == "-"
    assert blank[WORKING_DATA_COLUMNS.index("image_checked")] == "false"


def test_new_working_row_ignores_unknown_keys():
    row = new_working_row(kit_item="x", not_a_field="boom")
    assert row.kit_item == "x"
    assert not hasattr(row, "not_a_field")


def test_from_json_dict_tolerates_a_partial_object():
    row = WorkingDataRow.from_json_dict({"kit_item": "Solo", "UG_take": "terse"})
    assert row.kit_item == "Solo"
    assert row.ug_take == "terse"
    assert row.series == ""
