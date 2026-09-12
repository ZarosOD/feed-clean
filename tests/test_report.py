"""The shape of the four output files, and the wording of the summary."""

from __future__ import annotations

import csv
import io

from feed_clean import report
from feed_clean.dedupe import deduplicate
from feed_clean.normalize import normalize, read_feed
from feed_clean.validate import validate

HEADER = "Variant SKU,Title,Variant Price,Image Src,Warehouse Bay"


def pipeline(profile, *lines: str):
    rows, mapped, unmapped = read_feed(
        io.StringIO(HEADER + "\n" + "\n".join(lines) + "\n"), profile
    )
    for row in rows:
        normalize(row, profile)
    result = deduplicate(rows)
    for row in result.kept:
        validate(row, profile)
    return rows, result, mapped, unmapped


def read(path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def test_clean_columns_state_their_units(tmp_path, profile):
    rows, result, _, unmapped = pipeline(profile, "A-1,Lantern,24.00,https://x.test/a.jpg,B12")
    report.write_clean(tmp_path / "clean.csv", result.kept, unmapped)
    columns = read(tmp_path / "clean.csv")[0].keys()
    for name in ("weight_g", "length_mm", "width_mm", "height_mm"):
        assert name in columns
    assert "weight" not in columns  # no unitless twin to be confused with


def test_unmapped_columns_come_after_the_canonical_ones_and_before_the_verdict(
    tmp_path, profile
):
    rows, result, _, unmapped = pipeline(profile, "A-1,Lantern,24.00,https://x.test/a.jpg,B12")
    report.write_clean(tmp_path / "clean.csv", result.kept, unmapped)
    columns = list(read(tmp_path / "clean.csv")[0])
    assert columns[-2:] == ["needs_review", "issues"]
    assert columns[-3] == "Warehouse Bay"


def test_rejects_carry_every_original_column(tmp_path, profile):
    rows, result, _, _ = pipeline(profile, "A-1,Lantern,0.00,https://x.test/a.jpg,B12")
    rejected = [row for row in result.kept if row.rejected]
    report.write_rejects(tmp_path / "rejects.csv", rejected, list(rows[0].original))
    record = read(tmp_path / "rejects.csv")[0]
    assert record["Variant Price"] == "0.00"
    assert record["Warehouse Bay"] == "B12"
    assert record["reject_rules"] == "price_not_positive"
    assert record["line"] == "2"


def test_changes_are_ordered_by_line(tmp_path, profile):
    rows, _, _, _ = pipeline(
        profile,
        "A-1,LANTERN,24.00,https://x.test/a.jpg,B12",
        "A-2,CHISEL,18.00,https://x.test/b.jpg,B13",
    )
    report.write_changes(tmp_path / "changes.csv", rows)
    lines = [int(c["line"]) for c in read(tmp_path / "changes.csv")]
    assert lines == sorted(lines)


def test_an_empty_output_file_still_has_its_header(tmp_path, profile):
    report.write_rejects(tmp_path / "rejects.csv", [], ["Variant SKU"])
    text = (tmp_path / "rejects.csv").read_text(encoding="utf-8")
    assert text.startswith("line,sku,reject_rules,reason,Variant SKU")


def summary_for(profile, *lines):
    rows, result, mapped, unmapped = pipeline(profile, *lines)
    clean = [row for row in result.kept if not row.rejected]
    rejects = [row for row in result.kept if row.rejected]
    summary = report.summarise(
        "feed.csv", profile.name, rows, clean, rejects, result, mapped, unmapped
    )
    return report.render(summary)


def test_the_summary_says_when_nothing_was_duplicated(profile):
    text = summary_for(profile, "A-1,Lantern,24.00,https://x.test/a.jpg,B12")
    assert "no sku appeared twice" in text


def test_the_summary_names_the_unmapped_column(profile):
    text = summary_for(profile, "A-1,Lantern,24.00,https://x.test/a.jpg,B12")
    assert "Warehouse Bay" in text


def test_the_summary_says_a_tie_rejected_the_whole_group(profile):
    text = summary_for(
        profile,
        "A-1,Lantern,24.00,https://x.test/a.jpg,B12",
        "A-1,Lantern,31.00,https://x.test/a.jpg,B12",
    )
    assert "unresolved tie" in text
    assert "every row in the group rejected" in text


def test_the_summary_points_at_the_change_log_for_unresolved_values(profile):
    text = summary_for(profile, "A-1,Lantern,Call for quote,https://x.test/a.jpg,B12")
    assert "could not be resolved" in text
    assert "changes.csv" in text


def test_a_capped_breakdown_says_how_much_it_did_not_show(profile):
    """Same discipline as the demo's table preview: never let a top-N list read
    as the whole list."""
    counter = report.Counter({f"rule.{i}": 10 - i for i in range(9)})
    lines = report._breakdown(counter)
    assert "... and 5 more rule(s)" in lines[-1]
