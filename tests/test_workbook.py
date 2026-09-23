"""out/clean.xlsx: the same three tables, in the file a client actually opens.

The thing worth testing is not that openpyxl can write a file. It is that the
workbook and the CSVs cannot disagree — they are rendered from one `Table` each
rather than built twice — and that the workbook is skipped rather than fatal on
a machine without openpyxl, because this tool's base install has no
dependencies at all and that claim has to stay true.
"""

from __future__ import annotations

import csv
import io

import pytest

from feed_clean import cli, report
from feed_clean.dedupe import deduplicate
from feed_clean.normalize import normalize, read_feed
from feed_clean.validate import validate

openpyxl = pytest.importorskip("openpyxl")

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


def tables(profile, *lines: str):
    rows, result, _, unmapped = pipeline(profile, *lines)
    clean = [r for r in result.kept if not r.rejected]
    rejected = [r for r in result.kept if r.rejected]
    return rows, [
        report.clean_table(clean, unmapped),
        report.rejects_table(rejected, list(rows[0].original)),
        report.changes_table(rows),
    ]


GOOD = "A-1,Lantern,24.00,https://x.test/a.jpg,B12"
NO_PRICE = "A-2,Chisel,0.00,https://x.test/b.jpg,B13"


class TestOneDefinitionTwoRenderers:
    """The property that replaces a test asserting the two agree: there is one
    definition, so there is nothing to disagree."""

    def test_the_sheet_and_the_csv_hold_the_same_header(self, tmp_path, profile):
        _, built = tables(profile, GOOD)
        report.write_csv(tmp_path / "clean.csv", built[0])
        report.write_workbook(tmp_path / "clean.xlsx", built)

        from_csv = list(csv.reader((tmp_path / "clean.csv").open(encoding="utf-8")))[0]
        book = openpyxl.load_workbook(tmp_path / "clean.xlsx")
        from_sheet = [cell.value for cell in book["Clean"][1]]
        assert from_csv == from_sheet

    def test_the_sheet_and_the_csv_hold_the_same_values(self, tmp_path, profile):
        _, built = tables(profile, GOOD, NO_PRICE)
        report.write_csv(tmp_path / "rejects.csv", built[1])
        report.write_workbook(tmp_path / "clean.xlsx", built)

        from_csv = list(csv.DictReader((tmp_path / "rejects.csv").open(encoding="utf-8")))
        sheet = openpyxl.load_workbook(tmp_path / "clean.xlsx")["Rejects"]
        header = [cell.value for cell in sheet[1]]
        from_sheet = [
            dict(zip(header, ["" if c.value is None else str(c.value) for c in row]))
            for row in sheet.iter_rows(min_row=2)
        ]
        assert [r["sku"] for r in from_csv] == [r["sku"] for r in from_sheet]
        assert [r["reason"] for r in from_csv] == [r["reason"] for r in from_sheet]

    def test_the_row_count_matches_the_csv(self, tmp_path, profile):
        _, built = tables(profile, GOOD, NO_PRICE)
        written = report.write_workbook(tmp_path / "clean.xlsx", built)
        assert written == sum(len(table) for table in built)


class TestWhatTheClientOpens:
    def test_sheet_order_puts_clean_first(self, tmp_path, profile):
        _, built = tables(profile, GOOD)
        report.write_workbook(tmp_path / "clean.xlsx", built)
        book = openpyxl.load_workbook(tmp_path / "clean.xlsx")
        assert book.sheetnames == ["Clean", "Rejects", "Changes"]

    def test_the_header_row_stays_put_when_you_scroll(self, tmp_path, profile):
        _, built = tables(profile, GOOD)
        report.write_workbook(tmp_path / "clean.xlsx", built)
        book = openpyxl.load_workbook(tmp_path / "clean.xlsx")
        assert all(book[name].freeze_panes == "A2" for name in book.sheetnames)

    def test_money_is_a_number_you_can_sum(self, tmp_path, profile):
        """A price stored as text is a price nobody can total, which is most of
        why a client asked for Excel rather than the CSV."""
        _, built = tables(profile, GOOD)
        report.write_workbook(tmp_path / "clean.xlsx", built)
        sheet = openpyxl.load_workbook(tmp_path / "clean.xlsx")["Clean"]
        header = [cell.value for cell in sheet[1]]
        price = sheet.cell(row=2, column=header.index("price") + 1)
        assert isinstance(price.value, (int, float))
        assert price.value == 24.0

    def test_money_still_prints_its_two_decimals(self, tmp_path, profile):
        """24.0 with no format reads "24" and clean.csv says "24.00". The value
        is the same; without the format the screen would disagree with it."""
        _, built = tables(profile, GOOD)
        report.write_workbook(tmp_path / "clean.xlsx", built)
        sheet = openpyxl.load_workbook(tmp_path / "clean.xlsx")["Clean"]
        header = [cell.value for cell in sheet[1]]
        assert sheet.cell(row=2, column=header.index("price") + 1).number_format == "0.00"

    def test_a_sku_keeps_its_leading_zero(self, tmp_path, profile):
        """Excel eats "0012" the moment anything decides it is a number."""
        _, built = tables(profile, "0012,Lantern,24.00,https://x.test/a.jpg,B12")
        report.write_workbook(tmp_path / "clean.xlsx", built)
        sheet = openpyxl.load_workbook(tmp_path / "clean.xlsx")["Clean"]
        assert sheet.cell(row=2, column=1).value == "0012"

    def test_a_rejected_row_is_tinted(self, tmp_path, profile):
        _, built = tables(profile, GOOD, NO_PRICE)
        report.write_workbook(tmp_path / "clean.xlsx", built)
        sheet = openpyxl.load_workbook(tmp_path / "clean.xlsx")["Rejects"]
        assert sheet.cell(row=2, column=1).fill.fgColor.rgb.endswith("FFF4D6")

    def test_an_empty_sheet_still_carries_its_header(self, tmp_path, profile):
        _, built = tables(profile, GOOD)          # nothing rejected
        report.write_workbook(tmp_path / "clean.xlsx", built)
        sheet = openpyxl.load_workbook(tmp_path / "clean.xlsx")["Rejects"]
        assert sheet.max_row == 1
        assert sheet[1][0].value == "line"


class TestItIsOptional:
    def test_the_csvs_are_written_whether_or_not_the_workbook_is(
        self, tmp_path, profile, feed_path
    ):
        out = tmp_path / "out"
        assert cli.main([str(feed_path), "--out", str(out), "--no-xlsx", "--quiet"]) == 0
        assert not (out / "clean.xlsx").exists()
        for name in ("clean.csv", "rejects.csv", "changes.csv", "summary.txt"):
            assert (out / name).is_file()

    def test_a_machine_without_openpyxl_gets_a_line_not_a_crash(
        self, tmp_path, profile, feed_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(report, "xlsx_available", lambda: False)
        out = tmp_path / "out"
        assert cli.main([str(feed_path), "--out", str(out)]) == 0
        assert not (out / "clean.xlsx").exists()
        assert (out / "clean.csv").is_file()
        assert "openpyxl is not installed" in capsys.readouterr().err

    def test_the_summary_lists_the_workbook_when_it_was_written(
        self, tmp_path, feed_path, capsys
    ):
        out = tmp_path / "out"
        assert cli.main([str(feed_path), "--out", str(out), "--brief", "--quiet"]) == 0
        assert (out / "clean.xlsx").is_file()
        assert "clean.xlsx" in capsys.readouterr().out

    def test_the_summary_does_not_mention_a_workbook_it_skipped(
        self, tmp_path, feed_path, capsys
    ):
        out = tmp_path / "out"
        assert cli.main([str(feed_path), "--out", str(out), "--no-xlsx",
                         "--brief", "--quiet"]) == 0
        assert "clean.xlsx" not in capsys.readouterr().out


class TestAgainstTheRealFeed:
    def test_the_bundled_feed_round_trips(self, tmp_path, feed_path):
        """The file the clip opens. Counted against the CSVs beside it, so a
        sheet that silently dropped rows would show up here rather than in a
        recording."""
        out = tmp_path / "out"
        assert cli.main([str(feed_path), "--out", str(out), "--quiet"]) == 0

        book = openpyxl.load_workbook(out / "clean.xlsx")
        for name, csv_name in (("Clean", "clean.csv"), ("Rejects", "rejects.csv"),
                               ("Changes", "changes.csv")):
            rows = list(csv.DictReader((out / csv_name).open(encoding="utf-8")))
            assert book[name].max_row - 1 == len(rows), name

    def test_the_flagged_rows_the_clip_points_at_are_really_flagged(
        self, tmp_path, feed_path
    ):
        out = tmp_path / "out"
        cli.main([str(feed_path), "--out", str(out), "--quiet"])
        sheet = openpyxl.load_workbook(out / "clean.xlsx")["Clean"]
        header = [cell.value for cell in sheet[1]]
        column = header.index("needs_review") + 1
        tinted = {
            row for row in range(2, sheet.max_row + 1)
            if sheet.cell(row=row, column=1).fill.fgColor.rgb.endswith("FFF4D6")
        }
        flagged = {
            row for row in range(2, sheet.max_row + 1)
            if sheet.cell(row=row, column=column).value == "yes"
        }
        assert tinted == flagged
        assert flagged, "the fixture is supposed to produce flagged rows"
