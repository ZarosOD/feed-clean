"""The dedupe ladder, one rung at a time, on hand-built rows.

Each test names the rung it is on, because the value of a stated rule is that
somebody can check it rung by rung and disagree with a specific one.
"""

from __future__ import annotations

import io

import pytest

from feed_clean.dedupe import deduplicate, parse_timestamp
from feed_clean.models import REJECT
from feed_clean.normalize import normalize, read_feed

HEADER = (
    "Variant SKU,Title,Vendor,Variant Price,Variant Barcode,Image Src,Tags,Updated At"
)


def rows_from(*lines: str, profile):
    text = HEADER + "\n" + "\n".join(lines) + "\n"
    rows, _, _ = read_feed(io.StringIO(text), profile)
    for row in rows:
        normalize(row, profile)
    return rows


def line(sku, title="Thing", vendor="Harbourline", price="10.00", barcode="", image="", tags="", updated=""):
    return f"{sku},{title},{vendor},{price},{barcode},{image},{tags},{updated}"


# ------------------------------------------------------------------- rung 1


def test_identical_rows_collapse(profile):
    rows = rows_from(line("A-1"), line("A-1"), profile=profile)
    result = deduplicate(rows)
    assert len(result.kept) == 1
    assert result.kept[0].line == 2
    assert result.reasons["identical"] == 1


def test_identical_apart_from_the_timestamp_still_counts_as_identical(profile):
    """A resend of an unchanged product is not a decision."""
    rows = rows_from(
        line("A-1", updated="2026-01-01"), line("A-1", updated="2026-05-05"), profile=profile
    )
    result = deduplicate(rows)
    assert result.reasons["identical"] == 1


# ------------------------------------------------------------------- rung 2


def test_newest_updated_at_wins(profile):
    rows = rows_from(
        line("A-1", price="42.00", updated="2026-08-30T09:00:00Z"),
        line("A-1", price="38.50", updated="2026-09-07T09:00:00Z"),
        profile=profile,
    )
    result = deduplicate(rows)
    assert len(result.kept) == 1
    assert result.kept[0].get("price") == "38.50"
    assert result.reasons["newest updated_at"] == 1


def test_a_row_with_no_timestamp_does_not_beat_one_with_a_timestamp(profile):
    rows = rows_from(
        line("A-1", price="42.00", updated=""),
        line("A-1", price="38.50", updated="2026-09-07T09:00:00Z"),
        profile=profile,
    )
    result = deduplicate(rows)
    assert result.kept[0].get("price") == "38.50"


@pytest.mark.parametrize(
    "value", ["03/04/2026", "4 March 2026", "next tuesday", "2026-13-45", ""]
)
def test_an_ambiguous_or_unparseable_date_is_ignored_not_guessed(value):
    assert parse_timestamp(value) is None


@pytest.mark.parametrize(
    "value", ["2026-09-07", "2026-09-07T09:00:00Z", "2026-09-07 09:00", "2026-09-07T09:00:00+01:00"]
)
def test_iso_forms_parse(value):
    assert parse_timestamp(value) is not None


def test_ambiguous_dates_fall_through_to_completeness(profile):
    """Both rows say 03/04/2026 and 04/03/2026. Neither date is usable, so the
    group is decided by the rule that does not depend on guessing a date order."""
    rows = rows_from(
        line("A-1", barcode="", image="", updated="03/04/2026"),
        line("A-1", barcode="5060000007916", image="https://x.test/a.jpg", updated="04/03/2026"),
        profile=profile,
    )
    result = deduplicate(rows)
    assert result.kept[0].line == 3
    assert result.reasons["more complete"] == 1


# ------------------------------------------------------------------- rung 3


def test_the_more_complete_row_wins_when_nothing_is_dated(profile):
    rows = rows_from(
        line("A-1", price="", barcode="", image=""),
        line("A-1", price="31.00", barcode="5060000007916", image="https://x.test/a.jpg"),
        profile=profile,
    )
    result = deduplicate(rows)
    assert result.kept[0].line == 3
    assert result.reasons["more complete"] == 1


# ------------------------------------------------------------------- rung 5


def test_an_unresolved_tie_rejects_every_row_in_the_group(profile):
    """The point of the whole module. Two equally good rows disagreeing about
    the price is a coin flip with the client's margin, so neither is picked."""
    rows = rows_from(
        line("A-1", price="64.00", updated="2026-09-05T11:00:00Z"),
        line("A-1", price="71.00", updated="2026-09-05T11:00:00Z"),
        profile=profile,
    )
    result = deduplicate(rows)
    assert len(result.tied) == 2
    assert result.reasons["unresolved tie"] == 1
    for row in result.tied:
        assert "duplicate_unresolved" in row.rules(REJECT)
    # And the message names the column they disagree on, not just "a conflict".
    assert "price" in result.tied[0].issues[0].message
    assert "64.00" in result.tied[0].issues[0].message
    assert "71.00" in result.tied[0].issues[0].message


def test_tied_rows_stay_in_the_pipeline_so_they_reach_the_rejects_file(profile):
    rows = rows_from(
        line("A-1", price="64.00", updated="2026-09-05T11:00:00Z"),
        line("A-1", price="71.00", updated="2026-09-05T11:00:00Z"),
        profile=profile,
    )
    result = deduplicate(rows)
    assert len(result.kept) == 2
    assert all(row.rejected for row in result.kept)


# ---------------------------------------------------------------- backfilling


def test_backfill_fills_only_empty_fields_and_logs_the_source_line(profile):
    rows = rows_from(
        line("A-1", barcode="5060000007916", image="https://x.test/a.jpg", tags="kitchen",
             updated="2026-08-28T08:00:00Z"),
        line("A-1", price="16.00", barcode="", image="", tags="",
             updated="2026-09-09T08:00:00Z"),
        profile=profile,
    )
    result = deduplicate(rows)
    winner = result.kept[0]
    assert winner.line == 3
    assert winner.get("price") == "16.00"  # the winner's own value, not the loser's
    assert winner.get("barcode") == "5060000007916"
    fills = [c for c in winner.changes if c.rule == "dedupe.backfill"]
    assert {c.field for c in fills} == {"barcode", "image_url", "tags"}
    assert all("dropped line 2" in c.note for c in fills)


def test_backfill_never_overwrites_a_value_the_winner_already_has(profile):
    rows = rows_from(
        line("A-1", title="Old Title", updated="2026-01-01"),
        line("A-1", title="New Title", updated="2026-09-01"),
        profile=profile,
    )
    winner = deduplicate(rows).kept[0]
    assert winner.get("title") == "New Title"


def test_price_and_stock_are_never_backfilled(profile):
    """Carrying a stale price across from a dropped row is exactly the silent
    correction this tool exists not to do."""
    rows = rows_from(
        line("A-1", price="42.00", updated="2026-01-01"),
        line("A-1", price="", barcode="5060000007916", updated="2026-09-01"),
        profile=profile,
    )
    winner = deduplicate(rows).kept[0]
    assert winner.get("price") == ""


def test_no_backfill_flag(profile):
    rows = rows_from(
        line("A-1", tags="kitchen", updated="2026-01-01"),
        line("A-1", price="16.00", tags="", updated="2026-09-01"),
        profile=profile,
    )
    winner = deduplicate(rows, backfill=False).kept[0]
    assert winner.get("tags") == ""


# --------------------------------------------------------------------- misc


def test_sku_matching_ignores_case_and_surrounding_space(profile):
    rows = rows_from(line("a-1 "), line(" A-1"), profile=profile)
    assert len(deduplicate(rows).kept) == 1


def test_rows_with_no_sku_are_never_merged_together(profile):
    """Two unlabelled rows are two unknown products, not one."""
    rows = rows_from(line("", title="One"), line("", title="Two"), profile=profile)
    result = deduplicate(rows)
    assert len(result.kept) == 2
    assert result.groups == 0


def test_the_dropped_row_records_why_it_was_dropped(profile):
    rows = rows_from(
        line("A-1", price="42.00", updated="2026-01-01"),
        line("A-1", price="38.50", updated="2026-09-01"),
        profile=profile,
    )
    result = deduplicate(rows)
    drop = [c for c in result.dropped[0].changes if c.rule == "dedupe.drop"]
    assert len(drop) == 1
    assert "kept line 3" in drop[0].note
    assert "newest updated_at" in drop[0].note


def test_output_order_follows_the_input(profile):
    rows = rows_from(line("B-1"), line("A-1"), line("A-1"), line("C-1"), profile=profile)
    result = deduplicate(rows)
    assert [row.sku for row in result.kept] == ["B-1", "A-1", "C-1"]
