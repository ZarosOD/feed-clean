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
import re
import zipfile

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


def with_a_moved_clock(data: bytes) -> bytes:
    """The same workbook as a machine whose clock reads differently wrote it.

    Both clocks move: the zip member stamps and the Office document's own
    `dcterms` timestamps. This exists because writing the file twice inside one
    test proves nothing — both saves land in the same second, so the check
    passes whether or not anything was flattened. Moving the clock by hand is
    what makes the assertion load-bearing.
    """
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            body = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                body = report._TIMESTAMP.sub(rb"\g<1>2031-07-04T11:22:33Z\g<2>", body)
            info = zipfile.ZipInfo(item.filename, date_time=(2031, 7, 4, 11, 22, 32))
            info.compress_type = item.compress_type
            info.external_attr = item.external_attr
            info.create_system = 0
            target.writestr(info, body)
    return out.getvalue()


class TestReproducible:
    """Two runs over the same feed leave the same bytes, so `cmp` can stand in
    for "trust me" — the pinned-checkout rule the README's recipe states. An
    .xlsx is a zip of timestamped members and an Office document with its own
    clock; both are flattened in `report._repack`."""

    def test_a_run_on_a_different_clock_produces_the_same_bytes(
        self, tmp_path, profile
    ):
        """The real claim: what the file holds decides its bytes, and when it
        was written does not. Feeding `_repack` a copy with both clocks moved
        has to give back exactly what the tool wrote."""
        _, built = tables(profile, GOOD, NO_PRICE)
        path = tmp_path / "clean.xlsx"
        report.write_workbook(path, built)
        written = path.read_bytes()

        assert report._repack(with_a_moved_clock(written)) == written

    def test_two_runs_produce_identical_bytes(self, tmp_path, profile):
        _, built = tables(profile, GOOD, NO_PRICE)
        report.write_workbook(tmp_path / "first.xlsx", built)
        report.write_workbook(tmp_path / "second.xlsx", built)

        assert (tmp_path / "first.xlsx").read_bytes() == (
            tmp_path / "second.xlsx"
        ).read_bytes()

    def test_two_cli_runs_over_the_bundled_feed_produce_identical_bytes(
        self, tmp_path, feed_path
    ):
        """The check the README tells a client to perform, on the real feed."""
        first, second = tmp_path / "a", tmp_path / "b"
        cli.main([str(feed_path), "--out", str(first), "--quiet"])
        cli.main([str(feed_path), "--out", str(second), "--quiet"])

        assert (first / "clean.xlsx").read_bytes() == (
            second / "clean.xlsx"
        ).read_bytes()

    def test_the_document_clock_is_flattened_not_just_the_zip(
        self, tmp_path, profile
    ):
        """Two clocks, two fixes. Rewriting only the zip member timestamps
        would leave docProps/core.xml differing every run, and the file would
        still fail `cmp` while looking like it had been handled.

        Measured on openpyxl 3.1.5: `created` honours the workbook property and
        `modified` is refreshed to the save time regardless, so both timestamps
        are checked by name. Asserting the epoch appears *somewhere* in
        core.xml passes on `created` alone while `modified` still moves.
        """
        _, built = tables(profile, GOOD)
        path = tmp_path / "clean.xlsx"
        report.write_workbook(path, built)

        with zipfile.ZipFile(path) as book:
            core = book.read("docProps/core.xml").decode("utf-8")
            stamps = dict(re.findall(r"<dcterms:(created|modified)[^>]*>([^<]*)<", core))
            assert stamps == {
                "created": "1980-01-01T00:00:00Z",
                "modified": "1980-01-01T00:00:00Z",
            }
            assert all(
                item.date_time == (1980, 1, 1, 0, 0, 0) for item in book.infolist()
            )
