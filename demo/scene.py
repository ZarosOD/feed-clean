#!/usr/bin/env python3
"""The recorded scene. EDIT THIS FILE for a new piece — it is the Playwright
equivalent of a VHS tape. The rendering is not here: demo/lib/sheet.py is
shared by all four pieces and builds every frame.

Four beats, about 18 seconds, in the one shape all four clips use:

  1. BEFORE   fixtures/supplier-feed.csv — what the supplier actually sent.
  2. COMMAND  one line, and the real stdout it printed.
  3. AFTER    out/clean.xlsx, the Clean sheet, with the flagged rows on screen.
  4. AFTER    the same workbook's Rejects sheet.

Beats 3 and 4 open the file the run in beat 2 had just written, read off disk
at record time. Nothing in this file knows what is in that workbook; if
clean.py did not write it, `read_table` raises and there is no clip.

The feed is invented. `Northwind Trading Co.` is not a company and no real
product, vendor or client data appears here or in the recording.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "demo" / "lib"))

import sheet  # noqa: E402

# The supplier's own column names, spelled their way. Picking six of twenty-one
# keeps them readable; sheet.py keeps their real column letters so the gaps are
# visible rather than hidden.
SUPPLIER_COLUMNS = [
    "Variant SKU", "Title", "Vendor", "Variant Price", "Weight", "Stock Status",
]

# The same six fields after the run, under this tool's canonical names.
CLEAN_COLUMNS = [
    "sku", "title", "vendor", "price", "weight_g", "stock_status",
    "needs_review", "issues",
]

REJECT_COLUMNS = ["line", "sku", "reject_rules", "reason"]


def record(video_dir: Path) -> Path:
    feed = REPO / "fixtures" / "supplier-feed.csv"
    out = REPO / "out"

    # Beat 1 is built before the tool runs, so the BEFORE frame cannot
    # accidentally be showing anything the run produced.
    before = sheet.view(sheet.read_table(feed, base=REPO), SUPPLIER_COLUMNS)

    command = sheet.run_command(
        [sys.executable, "clean.py", str(feed.relative_to(REPO)), "--brief", "--quiet"],
        cwd=REPO,
    )

    book = out / "clean.xlsx"
    clean = sheet.read_table(book, "Clean", base=REPO)
    rejects = sheet.read_table(book, "Rejects", base=REPO)

    # The flagged rows are found by reading the file's own needs_review column,
    # not by hardcoding which rows they are. Change the fixture and the frame
    # follows it.
    flagged = sheet.rows_where(clean, "needs_review", "yes")
    clean_view = sheet.tint(
        sheet.view(clean, CLEAN_COLUMNS, rows=sheet.head_and(clean, flagged),
                   widths={"issues": 2.6, "title": 1.3, "needs_review": 0.8}),
        flagged,
        "flag",
    )
    reject_view = sheet.tint(
        sheet.view(rejects, REJECT_COLUMNS, widths={"reason": 4.0, "line": 0.5}),
        range(len(rejects.rows)),
        "reject",
    )

    with sheet.Scene(video_dir) as scene:
        scene.show(
            sheet.grid_html(
                before,
                step="BEFORE",
                said="the weekly export, as the supplier sent it",
                kind="before",
            ),
            sheet.HOLD_BEFORE,
        )
        scene.show(
            sheet.terminal_html(
                command,
                said="one command: dedupe, normalise, validate, report",
            ),
            sheet.HOLD_COMMAND,
        )
        scene.show(
            sheet.grid_html(
                clean_view,
                step="AFTER",
                said="the feed that will import — and the rows it would not vouch for",
                legend={"flag": f"{len(flagged)} rows kept but flagged needs_review"},
            ),
            sheet.HOLD_AFTER / 2,
        )
        scene.show(
            sheet.grid_html(
                reject_view,
                step="AFTER",
                said="the Rejects sheet: every row it refused, and why",
                legend={"reject": f"{len(rejects.rows)} rows not in the clean feed"},
            ),
            sheet.HOLD_AFTER / 2,
        )

    return scene.video_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    args.video_dir.mkdir(parents=True, exist_ok=True)
    print(record(args.video_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
