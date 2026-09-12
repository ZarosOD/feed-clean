"""End to end over the bundled feed, asserting against tests/expected.json.

The ground truth was written by `fixtures/generate_feed.py` at the same moment
as the dirty CSV, from the same values. So these tests compare the tool against
what the fixture *means*, not against what the tool produced the first time it
ran — which is the difference between catching a parser bug and enshrining one.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from feed_clean.cli import OK, REJECTS_FOUND, REVIEW_FOUND, UNREADABLE_INPUT, USAGE, main


@pytest.fixture(scope="module")
def run(tmp_path_factory, request):
    """One real run of the whole pipeline, shared by the assertions below."""
    repo = Path(__file__).resolve().parent.parent
    out = tmp_path_factory.mktemp("out")
    code = main(
        [
            str(repo / "fixtures" / "supplier-feed.csv"),
            "--profile",
            str(repo / "profiles" / "supplier.json"),
            "--out",
            str(out),
            "--quiet",
        ]
    )
    assert code == OK
    return {
        "dir": out,
        "clean": list(csv.DictReader((out / "clean.csv").open(encoding="utf-8"))),
        "rejects": list(csv.DictReader((out / "rejects.csv").open(encoding="utf-8"))),
        "changes": list(csv.DictReader((out / "changes.csv").open(encoding="utf-8"))),
        "summary": (out / "summary.txt").read_text(encoding="utf-8"),
    }


# --------------------------------------------------------------- the headline


def test_every_input_row_is_accounted_for(run, expected):
    """Nothing disappears. Every row is clean, rejected, or deduped away."""
    dropped = {
        int(c["line"])
        for c in run["changes"]
        if c["rule"] in ("dedupe.drop", "dedupe.unresolved")
    }
    clean_lines = len(run["clean"])
    reject_lines = len({int(r["line"]) for r in run["rejects"]})
    # A tied row is both dropped and rejected, so count it once.
    dropped_only = dropped - {int(r["line"]) for r in run["rejects"]}
    assert clean_lines + reject_lines + len(dropped_only) == expected["rows_in"]


def test_clean_skus_match_the_ground_truth_exactly(run, expected):
    assert [row["sku"] for row in run["clean"]] == expected["clean_skus"]


def test_rejects_match_the_ground_truth_exactly(run, expected):
    got = {r["line"]: sorted(r["reject_rules"].split()) for r in run["rejects"]}
    want = {line: item["rules"] for line, item in expected["rejects"].items()}
    assert got == want


def test_flagged_rows_match_the_ground_truth_exactly(run, expected):
    want = {item["sku"] for item in expected["flags"].values()}
    got = {row["sku"] for row in run["clean"] if row["needs_review"] == "yes"}
    assert got == want


def test_every_flagged_row_says_why(run):
    for row in run["clean"]:
        if row["needs_review"] == "yes":
            assert row["issues"], f"{row['sku']} is flagged with no reason"


def test_spot_values_match_the_fixture(run, expected):
    by_sku = {row["sku"]: row for row in run["clean"]}
    wrong = [
        (item["sku"], item["field"], item["value"], by_sku[item["sku"]][item["field"]])
        for item in expected["spot"]
        if by_sku[item["sku"]][item["field"]] != item["value"]
    ]
    assert wrong == []


# ------------------------------------------------------------------- dedupe


def test_each_duplicate_group_was_decided_the_way_the_fixture_intended(run, expected):
    keeps = {}
    for change in run["changes"]:
        if change["rule"] == "dedupe.keep":
            keeps[change["sku"]] = change
    for sku, item in expected["dedupe"].items():
        if item["winner_line"] is None:
            assert sku not in keeps  # a tie has no winner at all
            continue
        assert int(keeps[sku]["line"]) == item["winner_line"]
        assert item["reason"] in keeps[sku]["note"]


def test_the_unresolvable_duplicate_is_rejected_not_guessed(run, expected):
    tied = [r for r in run["rejects"] if r["sku"] == "NW-D004"]
    assert len(tied) == 2
    assert all("duplicate_unresolved" in r["reject_rules"] for r in tied)
    # Both original prices are in the reason, so the client can pick one.
    assert "64.00" in tied[0]["reason"] and "71.00" in tied[0]["reason"]
    assert "NW-D004" not in {row["sku"] for row in run["clean"]}


def test_backfilled_fields_name_the_line_they_came_from(run, expected):
    fills = [c for c in run["changes"] if c["rule"] == "dedupe.backfill"]
    assert fills
    for change in fills:
        assert "dropped line" in change["note"]
        assert change["before"] == ""
        assert change["after"]


# ---------------------------------------------------------------- change log


def test_the_change_log_covers_every_row_that_changed(run):
    logged = {int(c["line"]) for c in run["changes"]}
    # Every row in this fixture has at least an HTML-stripped description.
    assert len(logged) == 318


def test_an_unresolved_change_keeps_the_original_and_writes_nothing(run):
    unresolved = [c for c in run["changes"] if c["outcome"] == "unresolved"]
    assert unresolved
    for change in unresolved:
        assert change["before"].strip() != ""
        assert change["after"] == ""
        assert change["note"], "an unresolved change must say why"


def test_no_value_is_changed_without_a_rule_naming_it(run):
    for change in run["changes"]:
        assert change["rule"]
        assert change["field"]


# ------------------------------------------------------------------- rejects


def test_the_rejects_file_carries_the_suppliers_original_row(run):
    """So the supplier can fix the cell in front of them and resend."""
    row = next(r for r in run["rejects"] if r["sku"] == "NW-R008")
    assert row["Variant Barcode"] == "5.06E+12"
    assert row["Title"] == "Spreadsheet Mangled Mallet"


def test_every_reject_has_a_sentence_not_just_a_rule(run):
    for row in run["rejects"]:
        assert row["reason"]
        assert row["reject_rules"]


# ------------------------------------------------------------------- columns


def test_the_unmapped_column_survives_into_the_clean_feed(run, expected):
    header = expected["unmapped_headers"][0]
    assert header in run["clean"][0]
    assert run["clean"][0][header]


def test_the_summary_names_the_unmapped_column_and_vendors(run, expected):
    assert expected["unmapped_headers"][0] in run["summary"]
    for vendor in expected["unmapped_vendors"]:
        assert vendor in run["summary"]


def test_the_summary_fits_on_a_screen(run):
    lines = run["summary"].splitlines()
    assert len(lines) <= 40, f"summary is {len(lines)} lines"
    assert max(len(line) for line in lines) <= 120


# ---------------------------------------------------------------- exit codes


def test_fail_on_reject(tmp_path, repo):
    code = main([str(repo / "fixtures" / "supplier-feed.csv"), "--out", str(tmp_path), "--quiet", "--fail-on-reject"])
    assert code == REJECTS_FOUND


def test_fail_on_review(tmp_path, repo):
    code = main([str(repo / "fixtures" / "supplier-feed.csv"), "--out", str(tmp_path), "--quiet", "--fail-on-review"])
    assert code == REVIEW_FOUND


def test_a_missing_feed_is_exit_4(tmp_path):
    assert main([str(tmp_path / "nope.csv"), "--out", str(tmp_path), "--quiet"]) == UNREADABLE_INPUT


def test_a_bad_profile_is_exit_3(tmp_path, repo):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"columns": {"prcie": ["Price"]}}), encoding="utf-8")
    code = main(
        [str(repo / "fixtures" / "supplier-feed.csv"), "--profile", str(bad), "--out", str(tmp_path), "--quiet"]
    )
    assert code == USAGE


def test_a_header_only_file_is_exit_4(tmp_path):
    feed = tmp_path / "empty.csv"
    feed.write_text("Variant SKU,Title\n", encoding="utf-8")
    assert main([str(feed), "--out", str(tmp_path), "--quiet"]) == UNREADABLE_INPUT


# ------------------------------------------------------------------- options


def test_image_base_resolves_what_would_otherwise_be_rejected(tmp_path, repo):
    main(
        [
            str(repo / "fixtures" / "supplier-feed.csv"),
            "--out",
            str(tmp_path),
            "--quiet",
            "--image-base",
            "https://cdn.example-supplier.test/",
        ]
    )
    rejects = list(csv.DictReader((tmp_path / "rejects.csv").open(encoding="utf-8")))
    assert "NW-R005" not in {r["sku"] for r in rejects}


def test_no_backfill_changes_the_outcome_visibly(tmp_path, repo):
    main([str(repo / "fixtures" / "supplier-feed.csv"), "--out", str(tmp_path), "--quiet", "--no-backfill"])
    changes = list(csv.DictReader((tmp_path / "changes.csv").open(encoding="utf-8")))
    assert not [c for c in changes if c["rule"] == "dedupe.backfill"]
    rejects = list(csv.DictReader((tmp_path / "rejects.csv").open(encoding="utf-8")))
    # NW-D005's winner has no image of its own; without the backfill it fails.
    assert "NW-D005" in {r["sku"] for r in rejects}


def test_the_script_runs_as_a_script(tmp_path, repo):
    result = subprocess.run(
        [sys.executable, "clean.py", "fixtures/supplier-feed.csv", "--out", str(tmp_path), "--report", "--quiet"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == OK
    assert "rows in" in result.stdout
