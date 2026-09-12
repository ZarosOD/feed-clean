"""Tests for demo/lib/preview.py, the shared recording helper.

It is not part of the shipped tool — it is part of the demo layer that pieces
#3 and #4 inherit — but it is in this repo, so it is tested in this repo. A
helper that renders a table wrongly is a helper that puts a wrong table on
camera, and nobody reviews a GIF as carefully as they review a diff.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PREVIEW_PATH = Path(__file__).resolve().parents[1] / "demo" / "lib" / "preview.py"

spec = importlib.util.spec_from_file_location("demo_preview", PREVIEW_PATH)
assert spec and spec.loader
preview = importlib.util.module_from_spec(spec)
sys.modules["demo_preview"] = preview
spec.loader.exec_module(preview)


def write_csv(tmp_path: Path, text: str) -> str:
    path = tmp_path / "sample.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


def run(capsys, *argv: str) -> tuple[int, list[str]]:
    code = preview.main(list(argv))
    return code, capsys.readouterr().out.splitlines()


FEED = """sku,name,price
AB-1,Dock Line,41.50
AB-2,Fender,88.25
AB-3,Seacock,7.40
"""


def test_renders_header_rule_and_rows(tmp_path, capsys):
    code, lines = run(capsys, write_csv(tmp_path, FEED))
    assert code == 0
    assert lines[0].split() == ["sku", "name", "price"]
    assert set(lines[1]) <= {"-", " "}
    assert len(lines) == 5  # header, rule, three rows, no footer


def test_numeric_columns_are_right_aligned(tmp_path, capsys):
    _, lines = run(capsys, write_csv(tmp_path, FEED))
    # 7.40 is the shortest price; right alignment puts its last digit under the
    # last digit of the longest one.
    assert lines[-1].endswith("  7.40")
    assert lines[2].endswith("41.50")
    # The text column keeps left alignment.
    assert lines[2].startswith("AB-1  Dock Line")


def test_row_cap_says_how_many_it_did_not_show(tmp_path, capsys):
    _, lines = run(capsys, write_csv(tmp_path, FEED), "--rows", "1")
    assert lines[-1] == "... and 2 more rows (3 total)"


def test_no_footer_when_everything_fits(tmp_path, capsys):
    _, lines = run(capsys, write_csv(tmp_path, FEED), "--rows", "10")
    assert not any(line.startswith("...") for line in lines)


def test_long_cells_are_truncated_visibly(tmp_path, capsys):
    csv_text = "sku,name\nAB-1," + "x" * 60 + "\n"
    _, lines = run(capsys, write_csv(tmp_path, csv_text), "--cell", "10")
    assert lines[2] == "AB-1  " + "x" * 9 + "…"


def test_newlines_inside_a_cell_do_not_break_the_grid(tmp_path, capsys):
    csv_text = 'sku,name\nAB-1,"two\nlines"\n'
    _, lines = run(capsys, write_csv(tmp_path, csv_text))
    assert len(lines) == 3
    assert lines[2] == "AB-1  two lines"


def test_collapse_drops_a_repeat_of_the_row_above(tmp_path, capsys):
    csv_text = "vendor,total\nAcme,10\nAcme,10\nBravo,20\n"
    _, lines = run(capsys, write_csv(tmp_path, csv_text), "vendor", "total", "--collapse")
    assert [line.split()[0] for line in lines[2:]] == ["Acme", "Bravo"]
    # Collapsed rows are represented, not hidden, so there is no footer.
    assert not any(line.startswith("...") for line in lines)


def test_unknown_column_is_an_error_naming_the_real_ones(tmp_path, capsys):
    code = preview.main([write_csv(tmp_path, FEED), "sku", "cost"])
    err = capsys.readouterr().err
    assert code == 2
    assert "no column cost" in err
    assert "sku, name, price" in err


def test_empty_file_says_so_rather_than_printing_a_blank_table(tmp_path, capsys):
    code, lines = run(capsys, write_csv(tmp_path, ""))
    assert code == 0
    assert lines[0].endswith("is empty")


def test_unknown_option_stops_instead_of_being_read_as_a_column(tmp_path, capsys):
    with pytest.raises(SystemExit):
        preview.main([write_csv(tmp_path, FEED), "--nope"])


# --wrap. Added while piece #3 was the only caller: a rejects file's reason
# column is prose, and truncating prose cuts the part that explains the reject.

REJECTS = (
    "line,sku,reason\n"
    "288,AB-1,two equally recent rows disagree on price 64.00 versus 71.00 and neither wins\n"
    "289,AB-2,short reason\n"
)


def test_wrap_shows_all_of_a_long_cell_across_lines(tmp_path, capsys):
    _, lines = run(
        capsys, write_csv(tmp_path, REJECTS), "line", "sku", "reason",
        "--cell", "30", "--wrap", "reason",
    )
    # Nothing is elided, and the full sentence is recoverable from the screen.
    assert "…" not in "\n".join(lines)
    assert "neither wins" in " ".join(" ".join(lines).split())


def test_wrapped_continuation_lines_leave_the_other_columns_blank(tmp_path, capsys):
    _, lines = run(
        capsys, write_csv(tmp_path, REJECTS), "line", "sku", "reason",
        "--cell", "30", "--wrap", "reason",
    )
    body = lines[2:]
    # The first line of the record carries the key columns; its continuations
    # must not repeat them, or the block reads as several records. ("line" is
    # all-numeric, so it is right-aligned and the row starts with a space.)
    assert body[0].split()[:2] == ["288", "AB-1"]
    continuations = [line for line in body if line and not line.split()[0].isdigit()]
    assert continuations, "expected the long reason to wrap"
    for line in continuations:
        assert "AB-1" not in line and "288" not in line


def test_wrap_respects_the_cell_width(tmp_path, capsys):
    _, lines = run(
        capsys, write_csv(tmp_path, REJECTS), "line", "sku", "reason",
        "--cell", "24", "--wrap", "reason",
    )
    # Every rendered line stays inside the key columns plus the wrap width, so
    # the tape author can still predict whether it fits the terminal. The rule
    # line spans the full table, and its last segment is the wrap column.
    rule = lines[1]
    assert len(rule.split("  ")[-1]) <= 24
    assert max(len(line) for line in lines) <= len(rule)


def test_wrap_keeps_the_row_cap_counting_records_not_screen_lines(tmp_path, capsys):
    _, lines = run(
        capsys, write_csv(tmp_path, REJECTS), "line", "sku", "reason",
        "--cell", "30", "--wrap", "reason", "--rows", "1",
    )
    # One record shown, which occupies three screen lines — the footer counts
    # the record, otherwise a wrapped table would claim to have skipped rows
    # it actually displayed.
    assert lines[-1] == "... and 1 more rows (2 total)"


def test_wrap_never_right_aligns_the_prose_column(tmp_path, capsys):
    csv_text = "sku,note\nAB-1,100\nAB-2,2\n"
    _, lines = run(capsys, write_csv(tmp_path, csv_text), "sku", "note", "--wrap", "note")
    # Without --wrap this column is all-numeric and would be right-aligned;
    # a wrapped column is prose by contract and stays left.
    assert lines[3].startswith("AB-2  2")


def test_wrap_on_a_column_that_is_not_shown_is_an_error(tmp_path, capsys):
    code = preview.main([write_csv(tmp_path, REJECTS), "line", "sku", "--wrap", "reason"])
    err = capsys.readouterr().err
    assert code == 2
    assert "cannot wrap reason" in err
    assert "line, sku" in err


def test_two_wrapped_columns_are_refused(tmp_path):
    with pytest.raises(SystemExit):
        preview.main(
            [write_csv(tmp_path, REJECTS), "--wrap", "sku", "--wrap", "reason"]
        )


def test_wrap_is_off_by_default_so_existing_tapes_are_unchanged(tmp_path, capsys):
    _, lines = run(capsys, write_csv(tmp_path, REJECTS), "line", "sku", "reason", "--cell", "30")
    assert len(lines) == 4  # header, rule, two rows — one line per record
    assert "…" in lines[2]
