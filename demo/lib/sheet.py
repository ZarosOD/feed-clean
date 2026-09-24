#!/usr/bin/env python3
"""Film a file this run actually wrote, open in a spreadsheet grid.

Generic: do not edit per project. This is the shared renderer all four pieces
call, and `tools/demo_lib_drift.py` holds every copy of it to byte-identical.
The per-piece file is demo/scene.py, which decides *which* files to open and
what to say about them.

Why this exists
---------------
A terminal ASCII table cannot be told apart from a mock-up. The fix is not
better styling — a render that reads a fixture reproduces exactly the same
flaw with nicer borders. So the only public way into this module is
`read_table(path)`, which opens a real path and fails loudly if it is not
there. Nothing here can render a table it was handed as literal data:

    grid_html(view(read_table(out / "clean.xlsx")), ...)   # the only shape

`View` cannot be constructed without a `Table`, and `Table` cannot be
constructed without a file on disk. That is deliberate and is the whole
argument of the clip.

What a grid frame shows
-----------------------
A spreadsheet window: the filename in the title bar, real sheet tabs along the
bottom, column letters, row numbers, the file's own header as row 1, and its
values as text exactly as they are stored.

Showing a subset is allowed and is labelled. Columns keep the letter they have
in the source file, so picking columns 1, 2, 4 and 9 renders as A, B, D, I —
which is what hiding columns in Excel looks like, and it means a viewer can
tell a filtered view from a complete one. Row numbers work the same way: rows
keep their real 1-based sheet row, so a filtered set reads 1, 14, 22, 37 the
way a spreadsheet's row gutter does when rows are hidden. The caption says how
many of each are on screen.

The three beats
---------------
`grid_html` for BEFORE and AFTER, `terminal_html` for the thin middle. The
middle takes the argv it is filming *and* the captured stdout from the same
`run_command` call, so the command on screen cannot drift from the command
that produced the output below it.

Fonts are named explicitly (DejaVu, Ubuntu) rather than left to `sans-serif`:
the clip is re-recorded on whatever machine has the repo, and a font
substitution changes every column width in the grid.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from dataclasses import dataclass, field, replace
from html import escape
from pathlib import Path

# card.py is the sibling that draws the title card. This directory goes on
# sys.path first because tests/test_demo_sheet.py loads *this* file with
# importlib.util.spec_from_file_location, which puts nothing on sys.path — a
# plain `import card` would then be an ImportError in the one place the suite
# imports sheet.py at all. scene.py has already done the same insert; the
# guard keeps it to one entry.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import card  # noqa: E402

# 16:9, which is what a proposal gallery and a README both want. Every piece
# uses this one size so the four clips cut together.
VIEWPORT = {"width": 1280, "height": 720}

# Seconds per beat. One set of numbers for all four pieces — the consistency is
# the point, so a piece overriding these is a decision to argue for in its
# scene.py, not a knob to turn.
#
# The two BEFORE/COMMAND numbers came down in THE-261, which measured the clips
# at 0.5fps and found several consecutive pixel-identical samples in the first
# third — the part a client actually watches. HOLD_AFTER did not come down and
# is not available to trim: the company rule (COMPANY.md, Josue 2026-09-23) puts
# the AFTER frame at 8-10s and the BEFORE at 5-8s, so 5.0 is the BEFORE floor
# and 9.0 is inside the AFTER band with a second of room either side. Pacing
# does not get bought with the frame the whole clip exists to show.
HOLD_BEFORE = 5.0
HOLD_COMMAND = 3.6
HOLD_AFTER = 9.0

# How long the typewriter takes, and when the output lands under it. Both are
# inside HOLD_COMMAND with time to read what appeared.
#
# Also THE-261: at the old numbers the 0.5fps sample at ~6s caught a panel
# holding one typed character and nothing else, for about two seconds. The
# typewriter is flavour; the output under it is the beat. Getting to it in
# ~1s rather than ~2s is the whole of that fix.
TYPE_DELAY = 0.15
TYPE_SECONDS = 0.70
OUTPUT_DELAY = TYPE_DELAY + TYPE_SECONDS + 0.20

# The longest command that fits the terminal panel on one line.
#
# Geometry, at VIEWPORT width 1280: the panel is inset 26px by `main` and
# another 26px by `.term`, both sides, leaving 1176px. `.term` sets 15.5px
# mono, and DejaVu Sans Mono advances 0.602em, so a character is 9.33px and
# 126 fit — 124 after the `$ ` prompt. 110 is the limit enforced, which leaves
# room for a substituted mono font up to ~12% wider on a machine without the
# named ones.
#
# This is a ceiling, not a target: a command at 110 characters is not thereby a
# good one to film. It is the point past which the right-hand end of what is on
# screen is simply not on screen.
MAX_COMMAND_CHARS = 110

SANS = '"Ubuntu", "DejaVu Sans", "Segoe UI", Roboto, Arial, sans-serif'
MONO = '"Ubuntu Mono", "DejaVu Sans Mono", ui-monospace, Menlo, Consolas, monospace'

# Row tints. `flag` is "the tool kept this row but marked it", `reject` is "the
# tool refused to vouch for it", `change` is "this row moved since last time".
# A frame that uses one of these has to name it in `legend`, because an
# unexplained coloured row is decoration.
TINTS = {
    "flag": ("#fff4d6", "#e8a838"),
    "reject": ("#ffe3e0", "#d9534f"),
    "change": ("#dff3e6", "#1a7f4b"),
}


# --------------------------------------------------------------------------
# reading a real file
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Table:
    """A file on disk, as text. Built only by `read_table`."""

    path: Path
    headers: list[str]
    rows: list[list[str]]
    sheet: str
    sheet_names: tuple[str, ...]
    # What the footer counts. "rows" for a file, "files" for a directory
    # listing — the count is the same claim either way, but calling a mailbox
    # 33 rows reads as though we had already tabulated it.
    unit: str = "rows"
    # What the title bar prints as the file's directory. Relative to the repo
    # when `read_table` was given a base, because an absolute path on screen
    # is somebody's home directory and their username, in a clip that goes to
    # clients.
    where: str = "."

    def index_of(self, column: str) -> int:
        try:
            return self.headers.index(column)
        except ValueError:
            raise KeyError(
                f"{self.path.name} has no column {column!r}. It has: "
                + ", ".join(self.headers)
            ) from None

    def cell(self, row: int, column: str) -> str:
        return self.rows[row][self.index_of(column)]


def _text(value: object, number_format: str = "General") -> str:
    """One cell, as the spreadsheet itself would print it.

    openpyxl hands back ints, floats, datetimes and None; csv hands back str.
    `None` is an empty cell, not the word "None", and a float that is a whole
    number prints without the `.0`.

    The number format matters and is not decoration. A price column holding
    1299 with a `0.00` format reads "1299.00" in Excel and "1299" if you only
    look at the value — and the CSV next to it says "1299.00". Rendering the
    value alone would put a difference on screen that does not exist in the
    file. Only the decimal-places part is honoured; currency symbols, colours
    and section formats are not, and such a cell falls back to the raw value
    rather than being guessed at.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        places = _decimal_places(number_format)
        if places is not None:
            return f"{value:.{places}f}"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
    if hasattr(value, "isoformat"):
        text = value.isoformat()
        return text[:10] if text.endswith("T00:00:00") else text
    return str(value)


def _decimal_places(number_format: str) -> int | None:
    """`0.00` -> 2, `#,##0` -> 0, anything with a symbol or section -> None."""
    if not number_format or number_format == "General":
        return None
    if any(ch in number_format for ch in ";$€£%\"[") or "/" in number_format:
        return None
    body = number_format.replace(",", "").replace("#", "0")
    if set(body) - set("0."):
        return None
    return len(body.split(".", 1)[1]) if "." in body else 0


def read_table(path: str | Path, sheet: str | None = None,
               base: str | Path | None = None) -> Table:
    """Open a real .csv or .xlsx and return its contents.

    Raises if the file is not there. That is the point: every AFTER frame in
    every clip is one of these calls, so a run that did not write its output
    cannot be filmed as though it had.

    `base` is the repo root, and only affects the directory printed in the
    title bar: `out/` rather than `/home/somebody/…/out/`.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"sheet.py: {path} does not exist, so there is nothing truthful to "
            f"film. The scene must run the tool before it renders the output."
        )

    if path.suffix.lower() == ".xlsx":
        table = _read_xlsx(path, sheet)
    elif path.suffix.lower() in (".csv", ".tsv"):
        table = _read_csv(path)
    else:
        raise ValueError(f"sheet.py: cannot open {path.name}; expected .csv or .xlsx")

    return replace(table, where=_where(path, base))


def _where(path: Path, base: str | Path | None) -> str:
    """The directory to print, relative to the repo when it is inside it."""
    folder = path.resolve().parent
    if base is not None:
        try:
            relative = folder.relative_to(Path(base).resolve())
        except ValueError:
            pass
        else:
            base_name = Path(base).resolve().name
            return f"{relative}/" if str(relative) != "." else f"{base_name}/"
    return f"{folder.name}/"


def read_dir(path: str | Path, pattern: str = "*", base: str | Path | None = None,
             sort: str = "name") -> Table:
    """A real directory, as the listing a file manager shows.

    The BEFORE frame of a piece whose input is a pile of files rather than a
    spreadsheet — a mailbox, a folder of PDFs. Every value is `stat`ed off disk
    at record time, so it is the same kind of claim the AFTER frame makes: this
    is what is there, not a drawing of what is usually there.

    Sizes are printed the way a file manager prints them. The modified column
    is the date only: a time-of-day on screen dates the recording and tells a
    viewer nothing about the tool.
    """
    from datetime import datetime

    folder = Path(path)
    if not folder.is_dir():
        raise FileNotFoundError(f"sheet.py: {folder} is not a directory")

    found = [p for p in folder.glob(pattern) if p.is_file()]
    if sort == "name":
        found.sort(key=lambda p: p.name)
    elif sort == "size":
        found.sort(key=lambda p: p.stat().st_size, reverse=True)
    else:
        raise ValueError(f"sheet.py: no sort {sort!r}; have 'name' or 'size'")

    rows = [
        [
            item.name,
            item.suffix.lstrip(".").upper() or "file",
            _size(item.stat().st_size),
            datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d"),
        ]
        for item in found
    ]
    table = Table(
        folder, ["name", "type", "size", "modified"], rows, folder.name,
        (folder.name,), unit="files",
    )
    return replace(table, where=_where(folder / "x", base))


def _size(count: int) -> str:
    for unit in ("B", "KB", "MB"):
        if count < 1024 or unit == "MB":
            return f"{count:,} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024.0


def _read_csv(path: Path) -> Table:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError(f"sheet.py: {path.name} is empty")
    headers, body = rows[0], rows[1:]
    width = len(headers)
    # A short row in the file is a short row on screen, padded rather than
    # ragged; a long one keeps its extra cells so a malformed line is visible.
    body = [r + [""] * (width - len(r)) if len(r) < width else r for r in body]
    return Table(path, headers, body, path.name, (path.name,))


def _read_xlsx(path: Path, sheet: str | None) -> Table:
    import openpyxl  # lazy: only the pieces that write .xlsx need it installed

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        names = tuple(book.sheetnames)
        name = sheet or names[0]
        if name not in names:
            raise KeyError(
                f"{path.name} has no sheet {name!r}. It has: " + ", ".join(names)
            )
        # values_only=False, because the number format lives on the cell and
        # is part of what the sheet shows. See _text.
        grid = [
            [_text(cell.value, cell.number_format) for cell in row]
            for row in book[name].iter_rows()
        ]
    finally:
        book.close()

    if not grid:
        raise ValueError(f"sheet.py: {path.name}!{sheet} is empty")
    headers, body = grid[0], grid[1:]
    width = len(headers)
    body = [r + [""] * (width - len(r)) if len(r) < width else r for r in body]
    return Table(path, headers, body, name, names)


# --------------------------------------------------------------------------
# choosing what to show
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class View:
    """A window onto a `Table`: which columns, which rows, in which order."""

    table: Table
    columns: list[int]
    rows: list[int]
    tints: dict[int, str] = field(default_factory=dict)
    # Relative column widths, keyed by source column index. Absent means 1.
    widths: dict[int, float] = field(default_factory=dict)


def view(
    table: Table,
    columns: list[str | int] | None = None,
    rows: list[int] | None = None,
    limit: int = 13,
    widths: dict[str, float] | None = None,
) -> View:
    """Pick columns by name (or index) and rows by source index.

    `limit` applies only when `rows` is not given, and takes the file's first
    rows — the top of the file, not a flattering selection from the middle.

    `widths` widens a column relative to the others: `{"issues": 2.4}` gives
    that column two and a bit shares. Equal columns are the default and are
    usually right; a free-text column that would otherwise be all ellipsis is
    the case this exists for.
    """
    if columns is None:
        picked = list(range(len(table.headers)))
    else:
        picked = [c if isinstance(c, int) else table.index_of(c) for c in columns]
    chosen = list(rows) if rows is not None else list(range(min(limit, len(table.rows))))
    shares = {table.index_of(name): size for name, size in (widths or {}).items()}
    return View(table, picked, chosen, widths=shares)


def rows_where(table: Table, column: str, matches) -> list[int]:
    """Source row indices whose `column` satisfies `matches`.

    `matches` is a value or a callable. Used to put the flagged and rejected
    rows on screen, which is the half of the AFTER frame a client cares about.
    """
    index = table.index_of(column)
    test = matches if callable(matches) else lambda v: v == matches
    return [i for i, row in enumerate(table.rows) if test(row[index])]


def tint(view_: View, indices, kind: str) -> View:
    """Tint some rows, one of TINTS. Returns a new View."""
    if kind not in TINTS:
        raise KeyError(f"sheet.py: no tint {kind!r}; have {', '.join(TINTS)}")
    merged = dict(view_.tints)
    merged.update({i: kind for i in indices})
    return View(view_.table, view_.columns, view_.rows, merged, view_.widths)


def head_and(table: Table, extra: list[int], head: int = 7, limit: int = 13) -> list[int]:
    """The file's first `head` rows, then `extra` rows, in file order, capped.

    The shape an AFTER frame wants: the top of the output so it reads as the
    real file, then the rows that were flagged or rejected, which are usually
    further down. Non-contiguous on purpose — the row gutter shows the jump.
    """
    keep = sorted(set(range(min(head, len(table.rows)))) | set(extra))
    return keep[:limit]


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA. The letter the column has in the file."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


# --------------------------------------------------------------------------
# running the command the middle beat films
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Command:
    """One real invocation: what was typed, and what it printed."""

    display: str
    stdout: str
    returncode: int


def run_command(argv: list[str], cwd: Path, *, display: str | None = None,
                python: str = "python") -> Command:
    """Run it for real, and keep the argv and the output together.

    The middle beat renders this one object, so the command on screen and the
    output under it come from the same call and cannot disagree. `display`
    only ever rewrites argv[0] — the interpreter path, which is machine
    specific and is not the thing being demonstrated.
    """
    finished = subprocess.run(
        argv, cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    shown = display or " ".join([python, *argv[1:]])
    return Command(shown, finished.stdout.rstrip("\n"), finished.returncode)


# --------------------------------------------------------------------------
# the frames
# --------------------------------------------------------------------------

_CSS = f"""
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; }}
  body {{
    background: #eef1f5; color: #1b232c; font: 15px/1.4 {SANS};
    display: flex; flex-direction: column; height: {VIEWPORT['height']}px;
  }}

  /* The one line that says which beat this is. Same place in all four clips. */
  header {{
    flex: 0 0 auto; display: flex; align-items: baseline; gap: 16px;
    padding: 13px 26px 12px; background: #0f1720; color: #fff;
  }}
  header .step {{
    font-size: 12.5px; font-weight: 700; letter-spacing: 1.6px;
    color: #0f1720; background: #7fd1a6; border-radius: 4px; padding: 4px 9px;
  }}
  header .step.before {{ background: #cdd3e4; }}
  header .step.cmd {{ background: #f0c674; }}
  header .said {{ font-size: 18px; font-weight: 600; color: #e8eef5; }}

  main {{
    flex: 1 1 auto; padding: 18px 26px 0; min-height: 0;
    display: flex; align-items: center;
  }}

  /* The spreadsheet window. It hugs its rows rather than stretching, so a
     frame showing eight rows does not sit above 200px of blank white. */
  .book {{
    flex: 0 1 auto; width: 100%; display: flex; flex-direction: column; min-height: 0;
    background: #fff; border: 1px solid #b9c2cd; border-radius: 7px;
    box-shadow: 0 6px 18px rgba(15,23,32,.13); overflow: hidden;
  }}
  .titlebar {{
    flex: 0 0 auto; display: flex; align-items: center; gap: 10px;
    padding: 9px 14px; background: #f4f6f9; border-bottom: 1px solid #d5dbe3;
  }}
  .titlebar .dots {{ display: flex; gap: 6px; }}
  .titlebar .dots i {{ width: 11px; height: 11px; border-radius: 50%; background: #d0d6de; }}
  .titlebar .name {{ font-weight: 700; font-size: 14.5px; }}
  .titlebar .where {{ color: #6b7a8b; font-size: 13px; font-family: {MONO}; }}

  .scroll {{ flex: 1 1 auto; overflow: hidden; }}
  table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
  col.gutter {{ width: 46px; }}

  /* Column letters and row numbers: the spreadsheet's own chrome. */
  th.letter, td.rownum {{
    background: #eceff3; color: #5d6b7a; font: 600 12px/1 {SANS};
    text-align: center; border: 1px solid #d5dbe3; padding: 5px 4px;
    font-variant-numeric: tabular-nums;
  }}
  td.rownum {{ text-align: right; padding-right: 7px; }}
  /* Rows are hidden between this row and the one above it, the way a filtered
     spreadsheet shows it: the row numbers jump, and the join is marked. */
  tr.skip td {{ border-top: 2px dashed #8c9aa9; }}

  /* Row 1 is the file's own header row. */
  tr.headrow td {{ background: #dde3ea; font-weight: 700; }}

  td.cell {{
    border: 1px solid #dde2e8; padding: 6px 9px; font-size: 14.5px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  td.cell.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.cell.empty {{ background: #fafbfc; }}
  tr.zebra td.cell {{ background: #fbfcfd; }}
"""

_CSS += "".join(
    f"""
  tr.tint-{kind} td.cell {{ background: {fill}; }}
  tr.tint-{kind} td.rownum {{ background: {edge}; color: #fff; }}"""
    for kind, (fill, edge) in TINTS.items()
)

_CSS += f"""
  .tabs {{
    flex: 0 0 auto; display: flex; gap: 3px; align-items: flex-end;
    padding: 0 10px; background: #f4f6f9; border-top: 1px solid #d5dbe3;
  }}
  .tabs span {{
    padding: 6px 15px; font-size: 13px; color: #6b7a8b;
    border: 1px solid transparent; border-bottom: 0;
  }}
  .tabs span.on {{
    background: #fff; color: #1b232c; font-weight: 700;
    border-color: #d5dbe3; border-radius: 5px 5px 0 0; margin-bottom: -1px;
  }}

  footer {{
    flex: 0 0 auto; display: flex; justify-content: space-between; gap: 20px;
    padding: 11px 26px 14px; color: #556372; font-size: 13.5px;
  }}
  footer .legend {{ display: flex; gap: 18px; }}
  footer .legend b {{ font-weight: 600; color: #1b232c; }}
  footer .legend i {{
    display: inline-block; width: 11px; height: 11px; border-radius: 3px;
    margin-right: 6px; vertical-align: -1px; border: 1px solid #b9c2cd;
  }}
  footer .counts {{ font-family: {MONO}; font-size: 13px; white-space: nowrap; }}

  /* The thin middle: one command, its real output. Like `.book` above it hugs
     its lines rather than stretching, so a two-line run is a two-line panel and
     not 600px of empty dark with a prompt in the corner — which is what the
     0.5fps sheets in THE-261 showed. `.out` is faded in with opacity and so
     already occupies its space, which means the panel is its final height from
     the first frame and does not resize when the output lands. */
  .term {{
    flex: 0 1 auto; width: 100%; background: #12191f; border-radius: 7px; min-height: 0;
    padding: 22px 26px; font: 15.5px/1.6 {MONO}; color: #dfe8f1; overflow: hidden;
    box-shadow: 0 6px 18px rgba(15,23,32,.2);
  }}
  .term .line {{ white-space: pre; }}
  .term .prompt {{ color: #7fd1a6; }}
  .term .typed {{
    display: inline-block; overflow: hidden; white-space: pre; vertical-align: bottom;
    width: 0; border-right: 2px solid #7fd1a6;
    animation: type {TYPE_SECONDS}s steps(var(--n), end) {TYPE_DELAY}s forwards,
               caret .7s step-end {TYPE_DELAY}s 6;
  }}
  @keyframes type {{ to {{ width: var(--w); }} }}
  @keyframes caret {{ 50% {{ border-color: transparent; }} }}
  .term .out {{
    opacity: 0; margin-top: 10px; color: #c7d4e0; white-space: pre;
    animation: reveal .12s linear {OUTPUT_DELAY}s forwards;
  }}
  @keyframes reveal {{ to {{ opacity: 1; }} }}
  .term .more {{ color: #7d8b99; font-style: italic; }}

  /* One real page of a source document, beside the grid frames. */
  .paper {{
    flex: 1 1 auto; align-self: stretch; display: flex; min-height: 0;
    flex-direction: column; align-items: center; gap: 10px;
  }}
  .paper img {{
    min-height: 0; max-height: 100%; max-width: 100%; object-fit: contain;
    background: #fff; border: 1px solid #b9c2cd; border-radius: 4px;
    box-shadow: 0 6px 18px rgba(15,23,32,.16);
  }}
  .paper .caption {{ margin: 0; color: #556372; font-size: 13.5px; font-family: {MONO}; }}
"""

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>{css}</style></head>
<body>
  <header><span class="step {kind}">{step}</span><span class="said">{said}</span></header>
  <main>{body}</main>
  <footer>{footer}</footer>
</body></html>
"""


def _looks_numeric(text: str) -> bool:
    return bool(text) and text.replace(",", "").replace("-", "", 1).replace(
        ".", "", 1).isdigit()


def grid_html(
    view_: View,
    *,
    step: str,
    said: str,
    legend: dict[str, str] | None = None,
    kind: str = "after",
) -> str:
    """One spreadsheet frame, rendered from a file that exists on disk."""
    table = view_.table
    rows_out = []

    # Row 1 is the file's header row, so the data rows below it start at 2 —
    # the same arithmetic a spreadsheet does.
    header_cells = "".join(
        f'<td class="cell">{escape(table.headers[c])}</td>' for c in view_.columns
    )
    rows_out.append(f'<tr class="headrow"><td class="rownum">1</td>{header_cells}</tr>')

    previous = -1
    for n, source_row in enumerate(view_.rows):
        cells = []
        for c in view_.columns:
            value = table.rows[source_row][c] if c < len(table.rows[source_row]) else ""
            css = "cell num" if _looks_numeric(value) else "cell"
            if not value:
                css += " empty"
            cells.append(f'<td class="{css}">{escape(value)}</td>')
        classes = []
        if source_row != previous + 1 and previous != -1:
            classes.append("skip")          # rows are hidden between these two
        if n % 2:
            classes.append("zebra")
        if source_row in view_.tints:
            classes.append(f"tint-{view_.tints[source_row]}")
        previous = source_row
        attr = f' class="{" ".join(classes)}"' if classes else ""
        rows_out.append(
            f'<tr{attr}><td class="rownum">{source_row + 2}</td>{"".join(cells)}</tr>'
        )

    letters = "".join(
        f'<th class="letter">{column_letter(c)}</th>' for c in view_.columns
    )
    # One <col> per shown column. table-layout:fixed divides the row by these,
    # so a share of 2.4 really is 2.4 times a plain column.
    total = sum(view_.widths.get(c, 1.0) for c in view_.columns)
    cols = '<col class="gutter">' + "".join(
        f'<col style="width:{view_.widths.get(c, 1.0) / total:.4%}">'
        for c in view_.columns
    )
    tabs = "".join(
        f'<span class="{"on" if name == table.sheet else ""}">{escape(name)}</span>'
        for name in table.sheet_names
    )

    body = f"""<div class="book">
      <div class="titlebar"><span class="dots"><i></i><i></i><i></i></span>
        <span class="name">{escape(table.path.name)}</span>
        <span class="where">{escape(table.where)}</span></div>
      <div class="scroll"><table>{cols}
        <tr><th class="letter"></th>{letters}</tr>
        {"".join(rows_out)}
      </table></div>
      <div class="tabs">{tabs}</div>
    </div>"""

    keys = "".join(
        f'<span><i style="background:{TINTS[k][0]};border-color:{TINTS[k][1]}"></i>'
        f"<b>{escape(text)}</b></span>"
        for k, text in (legend or {}).items()
    )
    shown_cols = len(view_.columns)
    counts = (
        f"{len(table.rows):,} {table.unit} × {len(table.headers)} columns · "
        f"showing {len(view_.rows)}"
        + (f" of them, {shown_cols} of {len(table.headers)} columns"
           if shown_cols != len(table.headers) else "")
    )
    footer = f'<div class="legend">{keys}</div><div class="counts">{counts}</div>'

    return _PAGE.format(
        title=table.path.name, css=_CSS, step=escape(step), kind=kind,
        said=escape(said), body=body, footer=footer,
    )


def document_html(png: bytes, *, step: str, said: str, caption: str,
                  kind: str = "before") -> str:
    """A frame showing one real page image, rendered from the source document.

    For the piece whose input is a PDF: a listing tells you there are twelve
    invoices, and this tells you what one of them looks like. The bytes are
    rendered from the file on disk by the scene that calls this — nothing here
    draws an invoice.
    """
    import base64

    data = base64.b64encode(png).decode("ascii")
    body = f"""<div class="paper">
      <img src="data:image/png;base64,{data}" alt="">
      <p class="caption">{escape(caption)}</p>
    </div>"""
    return _PAGE.format(
        title=caption, css=_CSS, step=escape(step), kind=kind,
        said=escape(said), body=body, footer="",
    )


def _check_display(display: str) -> None:
    """Refuse to film a command line a client should not be reading.

    Two failures, both found on catalog-watch in THE-261 and both invisible to
    every check we had, because a clip with a bad middle beat still encodes,
    still hits its byte count, and still ends on the right frame:

      * an absolute path is this machine's filesystem layout and its login
        name, published on an asset that goes out with bids. Every scene runs
        its command with `cwd=REPO`, so the repo-relative form names the same
        file and says nothing about the box;
      * a line past MAX_COMMAND_CHARS has its right-hand end off the edge of
        the panel, where the flags usually are.

    Raising rather than truncating on purpose. A truncated command on screen is
    no longer the command that produced the output beneath it, which is the one
    promise this beat makes.
    """
    absolute = [word for word in display.split() if word.startswith("/")]
    if absolute:
        raise ValueError(
            f"sheet.py: {absolute[0]} is an absolute path, and the command beat "
            f"goes to clients. Pass it relative to the cwd the scene runs the "
            f"command in. Whole line: {display}"
        )
    if len(display) > MAX_COMMAND_CHARS:
        raise ValueError(
            f"sheet.py: the command is {len(display)} characters and only "
            f"{MAX_COMMAND_CHARS} fit the panel, so the end of it would be off "
            f"screen. Shorten it or shorten the paths in it: {display}"
        )


def terminal_html(
    command: Command,
    *,
    step: str = "THE COMMAND",
    said: str,
    max_lines: int = 14,
) -> str:
    """The thin middle: the argv that just ran, and what it really printed."""
    _check_display(command.display)
    lines = command.stdout.split("\n")
    trimmed = lines[:max_lines]
    more = (
        f'\n<span class="more">… {len(lines) - max_lines} more lines '
        f"(the files it wrote are next)</span>"
        if len(lines) > max_lines else ""
    )
    # steps() counts the characters; the width has to be the same count in ch
    # or the caret lands mid-word when it stops.
    n = len(command.display)
    printed = escape("\n".join(trimmed))
    body = f"""<div class="term">
      <div class="line"><span class="prompt">$ </span><span class="typed"
        style="--n:{n};--w:{n}ch">{escape(command.display)}</span></div>
      <div class="out">{printed}{more}</div>
    </div>"""
    return _PAGE.format(
        title=command.display, css=_CSS, step=escape(step), kind="cmd",
        said=escape(said), body=body, footer="",
    )


# --------------------------------------------------------------------------
# filming it
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Beat:
    """One `show`/`goto` — where the beat came from, and how long it held."""

    kind: str       # "html" for set_content, "url" for goto
    source: str
    hold: float


@dataclass(frozen=True)
class _Mark:
    """A beat the scene asked to keep for the title card, not yet shot.

    `dom` is the *serialised page* as it stood when `panel()` was called, not
    `beat.source`. The two are the same thing only when the beat's source is
    the whole truth about what is on screen, and for one of the five pieces it
    is not: catalog-watch `goto`s a served page and then paints the narration
    bar with `add_style_tag`/`evaluate` and the change highlights with a second
    `evaluate`. Replaying the URL re-fetched the bare storefront, so the card's
    AFTER half came out identical to its BEFORE half under a caption reading
    "Every change, marked" (THE-303).

    `page.content()` is a DOM read, not a raster: it never touches the capture
    surface, which is the thing that leaked frames into the video. Controlled,
    not assumed -- see the class docstring.
    """

    tone: str
    label: str
    detail: str
    selector: str | None
    beat: _Beat
    dom: str


class Scene:
    """A Playwright page that records video, driven one beat at a time.

        with Scene(video_dir, poster=out / "poster.png") as scene:
            scene.show(grid_html(...), HOLD_BEFORE)
            scene.panel("before", "Messy supplier feed", "318 rows | 21 columns")
            scene.show(terminal_html(...), HOLD_COMMAND)
            scene.show(grid_html(...), HOLD_AFTER)
            scene.panel("after", "Clean .xlsx", "every change logged")
        print(scene.video_path)

    `show` renders a string with `set_content`, so a frame needs no web server.
    `goto` is there for the one piece whose BEFORE really is a served page.

    `panel` marks the beat on screen right now as one half of the title card,
    and on the way out the two panels become `poster` — see demo/lib/card.py.
    A scene given no `poster` collects nothing and behaves exactly as it did
    before.

    Nothing screenshots the recording page while it is recording. Chromium's
    element-screenshot path resizes the capture surface, and the screencast
    behind `record_video_dir` emits whatever is on that surface: the frames
    come out as the bare element pinned to the top-left of the video canvas
    with flat grey where the rest of the page should be. Measured on all five
    pieces, every `panel()` call leaked one to five such frames, and on three
    of them a leaked frame landed last — which is the frame a player holds
    after playback ends, so it is the image left on screen (THE-295).

    So `panel` serialises the page with `page.content()` and that DOM is put
    back up after the recording context is closed and the video finalised —
    same browser, same viewport, same markup, held for the same time, so the
    animated beats settle the way they settled on camera. See `_render_panels`.

    `page.content()` is a DOM read over CDP with no rasterisation, so it has no
    capture surface to resize. Controlled the same way the screenshot was, on
    the piece that exercises every path: two catalog-watch recordings, one
    calling `content()` at each panel and one calling nothing. Both mp4s came
    out clean over a full frame-by-frame decode (555 and 554 frames, no leaked
    frame in either). The no-`content()` arm's *gif* did flag one frame, at the
    0.8 s title-card boundary — that arm renders a blank card by construction,
    since suppressing the capture leaves the panels empty, so the flag is the
    control's own blank poster and not the recording. Stated rather than
    tidied away: it is the one reading in the pair that is not a clean zero
    (THE-303).
    """

    def __init__(self, video_dir: Path, viewport: dict | None = None,
                 poster: str | Path | None = None) -> None:
        self.video_dir = Path(video_dir)
        self.viewport = viewport or VIEWPORT
        self.video_path: Path | None = None
        self.poster = Path(poster) if poster else None
        self.poster_path: Path | None = None
        self.panels: list[card.Panel] = []
        self._marks: list[_Mark] = []
        self._beat: _Beat | None = None

    def __enter__(self) -> "Scene":
        from playwright.sync_api import sync_playwright

        self.video_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        self._context = self._browser.new_context(
            viewport=self.viewport,
            record_video_dir=str(self.video_dir),
            record_video_size=self.viewport,
            device_scale_factor=1,
        )
        self.page = self._context.new_page()
        return self

    def show(self, html: str, hold: float) -> None:
        self._beat = _Beat(kind="html", source=html, hold=hold)
        self.page.set_content(html, wait_until="load")
        self.page.wait_for_timeout(hold * 1000)

    def goto(self, url: str, hold: float) -> None:
        self._beat = _Beat(kind="url", source=url, hold=hold)
        self.page.goto(url, wait_until="networkidle")
        self.page.wait_for_timeout(hold * 1000)

    def _play(self, page, mark: _Mark) -> None:
        """Put one marked beat back on a page, as it stood when it was marked.

        The DOM that goes up is `mark.dom` -- the page serialised at `panel()`
        time -- rather than `beat.source`, so anything the scene painted on
        after the show/goto comes back with it. A `url` beat is navigated to
        first and only then overwritten: the navigation is what makes relative
        stylesheet and image URLs in that DOM resolve, because `set_content`
        leaves the document URL alone.

        The hold is replayed rather than skipped because a beat can be animated
        -- `terminal_html` types its command over TYPE_SECONDS -- so the layout
        gets the same settling time the camera gave it.
        """
        if mark.beat.kind == "url":
            page.goto(mark.beat.source, wait_until="networkidle")
        page.set_content(mark.dom, wait_until="load")
        page.wait_for_timeout(mark.beat.hold * 1000)

    def panel(self, tone: str, label: str, detail: str, *,
              selector: str | None = card.ARTIFACT) -> None:
        """Keep this beat as one half of the title card.

        Called *after* the `show`/`goto` whose frame it wants, so the panel is
        the frame the clip really contains rather than a page built for the
        card. `selector=None` shoots the whole viewport, which is what a piece
        whose frame is a served page wants; the default shoots the artifact
        inside a sheet.py frame and leaves the narration bar out.

        This only *marks* the beat, and marking it serialises the page with
        `page.content()`. The screenshot is taken after the video is finalised,
        off camera -- see the class docstring for the frames the old
        during-the-take screenshot leaked into the clip, and `_Mark` for why
        the serialised DOM rather than the beat's source is what gets kept.

        Exactly two panels, "before" then "after" — card.py draws two halves
        and a scene that offered three would have to decide which to drop, a
        decision that belongs in the scene where the beats are.
        """
        if self.poster is None:
            return
        if len(self._marks) == 2:
            raise ValueError(
                "Scene.panel: the title card has two halves and both are "
                f"already taken ({self._marks[0].tone}, {self._marks[1].tone})"
            )
        if self._beat is None:
            raise ValueError(
                "Scene.panel: nothing has been shown yet, so there is no beat "
                "to keep. Call panel() after the show()/goto() it wants."
            )
        self._marks.append(
            _Mark(tone=tone, label=label, detail=detail,
                  selector=selector, beat=self._beat,
                  dom=self.page.content())
        )

    def _render_panels(self) -> list[card.Panel]:
        """Re-render the marked beats in a context that is not recording.

        Same browser and same viewport as the take, so the fonts and the
        layout are the ones the clip shows; no `record_video_dir`, so the
        screenshots cannot land in a video that is already closed anyway.
        """
        context = self._browser.new_context(
            viewport=self.viewport, device_scale_factor=1,
        )
        try:
            page = context.new_page()
            panels = []
            for mark in self._marks:
                self._play(page, mark)
                target = (page if mark.selector is None
                          else page.locator(mark.selector).first)
                panels.append(card.Panel(
                    tone=mark.tone, label=mark.label, detail=mark.detail,
                    png=target.screenshot(type="png"),
                ))
            return panels
        finally:
            context.close()

    def __exit__(self, *exc) -> None:
        self.video_path = Path(self.page.video.path())
        self._context.close()
        # The video is finalised by the line above, so the panel screenshots
        # can no longer reach it. Still the recording browser, though: a second
        # Chromium would be a second font configuration.
        try:
            if exc[0] is None and self.poster is not None and self._marks:
                self.panels = self._render_panels()
        finally:
            self._browser.close()
            self._playwright.stop()
        # After the recording browser is gone, not before: the card gets its
        # own Chromium with a different font configuration (card.py explains
        # why), and two live browsers for no reason is two things to leak.
        if exc[0] is None and self.poster is not None:
            if len(self.panels) != 2:
                raise ValueError(
                    f"Scene: poster={self.poster} was asked for but the scene "
                    f"marked {len(self.panels)} panel(s); the card needs two, "
                    "a before and an after"
                )
            before, after = self.panels
            self.poster_path = card.write(before, after, self.poster,
                                          viewport=self.viewport)
