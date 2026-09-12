"""Arguments, the pipeline, and exit codes you can alert on."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report
from .dedupe import deduplicate
from .normalize import normalize, read_feed
from .profile import ProfileError, load_profile
from .validate import validate

OK = 0
REVIEW_FOUND = 1
REJECTS_FOUND = 2
USAGE = 3
UNREADABLE_INPUT = 4

DEFAULT_PROFILE = Path(__file__).resolve().parent.parent / "profiles" / "supplier.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clean.py",
        description="Dedupe, normalise, validate and report on a product feed CSV.",
    )
    parser.add_argument("feed", help="the supplier CSV to clean")
    parser.add_argument(
        "--profile",
        default=str(DEFAULT_PROFILE),
        help="column aliases and vocabularies (default: profiles/supplier.json)",
    )
    parser.add_argument("--out", default="out", help="output directory (default: out)")
    parser.add_argument(
        "--image-base",
        default="",
        help="base URL to resolve relative image paths against; without it a "
        "relative path is a rejection rather than a guess",
    )
    parser.add_argument(
        "--no-backfill",
        action="store_true",
        help="do not fill a winner's empty fields from the duplicate rows it beat",
    )
    parser.add_argument("--report", action="store_true", help="print the full summary to stdout")
    parser.add_argument(
        "--brief",
        action="store_true",
        help="print the eight-line version instead: what a cron log wants",
    )
    parser.add_argument("--quiet", action="store_true", help="say nothing except the summary")
    parser.add_argument(
        "--fail-on-review", action="store_true", help=f"exit {REVIEW_FOUND} if any row is flagged"
    )
    parser.add_argument(
        "--fail-on-reject",
        action="store_true",
        help=f"exit {REJECTS_FOUND} if any row is rejected",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    say = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"clean.py: {exc}", file=sys.stderr)
        return USAGE

    feed_path = Path(args.feed)
    try:
        with feed_path.open(newline="", encoding="utf-8-sig") as handle:
            rows, mapped, unmapped = read_feed(handle, profile)
    except FileNotFoundError:
        print(f"clean.py: no such file: {feed_path}", file=sys.stderr)
        return UNREADABLE_INPUT
    except UnicodeDecodeError as exc:
        print(f"clean.py: {feed_path} is not UTF-8 text ({exc})", file=sys.stderr)
        return UNREADABLE_INPUT

    if not rows:
        print(f"clean.py: {feed_path} has a header but no rows", file=sys.stderr)
        return UNREADABLE_INPUT

    say(f"read {len(rows)} rows from {feed_path}")

    # Normalise before deduping: two rows that disagree only about how they
    # spell "$1,299.00" are the same row, and only canonical values can say so.
    for row in rows:
        normalize(row, profile, args.image_base)

    result = deduplicate(rows, backfill=not args.no_backfill)

    for row in result.kept:
        validate(row, profile)

    clean_rows = [row for row in result.kept if not row.rejected]
    reject_rows = [row for row in result.kept if row.rejected]
    reject_rows.sort(key=lambda row: row.line)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    clean_count = report.write_clean(out_dir / "clean.csv", clean_rows, unmapped)
    reject_count = report.write_rejects(
        out_dir / "rejects.csv", reject_rows, list(rows[0].original)
    )
    change_count = report.write_changes(out_dir / "changes.csv", rows)

    summary = report.summarise(
        source=str(feed_path),
        profile_name=profile.name,
        all_rows=rows,
        clean_rows=clean_rows,
        reject_rows=reject_rows,
        result=result,
        mapped=mapped,
        unmapped=unmapped,
    )
    summary.files = {
        f"{out_dir}/clean.csv": clean_count,
        f"{out_dir}/rejects.csv": reject_count,
        f"{out_dir}/changes.csv": change_count,
    }
    text = report.render(summary)
    (out_dir / "summary.txt").write_text(text, encoding="utf-8")

    if args.brief:
        print(report.render_brief(summary), end="")
    elif args.report:
        print(text, end="")
    else:
        say(
            f"{clean_count} clean, {reject_count} rejected, {summary.flagged} flagged. "
            f"Wrote {out_dir}/clean.csv, rejects.csv, changes.csv, summary.txt"
        )

    if args.fail_on_reject and reject_rows:
        return REJECTS_FOUND
    if args.fail_on_review and summary.flagged:
        return REVIEW_FOUND
    return OK
