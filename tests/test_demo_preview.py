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
