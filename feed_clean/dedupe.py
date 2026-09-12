"""One sku, one row — and a stated reason for which row survived.

"First seen wins" is the default everybody implements and nobody can defend.
It means the winner is decided by the order the supplier happened to write the
file in, which is to say by nothing. The ladder here is decided by what the
duplicate usually *is*:

  1. **Identical rows collapse.** Same sku, same everything: the supplier
     exported the same product twice. There is no decision to make.
  2. **Newest `updated_at` wins.** Two different rows for one sku is nearly
     always an old row and a resend. The resend is the supplier's latest
     answer, so it is the one to believe.
  3. **Then: the more complete row wins.** No usable timestamps, or the same
     timestamp on both. A row with a price and an image beats a row with
     neither; it is the same product described better.
  4. **Then: the row with more populated columns at all.**
  5. **Otherwise it is a tie, and a tie is not resolved.** Two rows, equally
     fresh, equally complete, disagreeing about the price. Keeping either one
     is a coin flip with the client's margin, so *both* are rejected, and the
     reject reason names the columns they disagree on.

After a winner is chosen, empty fields in the winner are backfilled from the
losers — never overwritten, only filled, and every fill is logged with the line
number it came from. `--no-backfill` turns that off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .models import DROPPED, REJECT, Row
from .parse import fold

# The columns two rows have to agree on to count as the same row. `updated_at`
# is deliberately not here: an identical product resent with a new timestamp is
# still an identical product.
COMPARE = (
    "title",
    "vendor",
    "product_type",
    "price",
    "currency",
    "cost",
    "compare_at",
    "barcode",
    "weight_g",
    "length_mm",
    "width_mm",
    "height_mm",
    "quantity",
    "stock_status",
    "published",
    "taxable",
    "image_url",
    "description",
    "tags",
    "handle",
)

# Which fields "more complete" counts first. A product with these is sellable;
# a product with tags and a handle is not.
CORE = ("title", "price", "image_url", "barcode", "stock_status", "vendor")

# Backfillable: carrying a stale price or stock level across from an older row
# would be exactly the silent correction this tool exists not to do, so those
# are not in the list. Descriptive fields do not go stale the same way.
BACKFILL = (
    "title",
    "vendor",
    "product_type",
    "barcode",
    "weight_g",
    "length_mm",
    "width_mm",
    "height_mm",
    "image_url",
    "description",
    "tags",
    "handle",
)

_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?\s*(Z|[+-]\d{2}:?\d{2})?$"
)

REASONS = (
    "identical",
    "newest updated_at",
    "more complete",
    "more columns populated",
    "unresolved tie",
)


@dataclass
class DedupeResult:
    kept: list[Row] = field(default_factory=list)
    dropped: list[Row] = field(default_factory=list)
    tied: list[Row] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=dict)
    groups: int = 0
    rows_involved: int = 0
    backfills: int = 0


def parse_timestamp(value: str) -> datetime | None:
    """ISO 8601 only. A date in some other order is ambiguous, so it is ignored.

    `03/04/2026` is the 3rd of April to the supplier and the 4th of March to
    the marketplace, and there is no way to tell which from the file. Treating
    it as "no timestamp" drops the group down to the completeness rule, which
    is a decision that does not depend on guessing a date order.
    """
    match = _ISO.match((value or "").strip())
    if not match:
        return None
    year, month, day, hour, minute, second, _tz = match.groups()
    try:
        return datetime(
            int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0)
        )
    except ValueError:
        return None


def signature(row: Row) -> tuple:
    return tuple(row.get(name) for name in COMPARE) + tuple(sorted(row.extra.items()))


def _populated(row: Row, fields) -> int:
    return sum(1 for name in fields if row.get(name))


def _all_fields(row: Row) -> int:
    return sum(1 for value in row.values.values() if value not in (None, "")) + sum(
        1 for value in row.extra.values() if value
    )


def _conflicts(rows: list[Row]) -> list[str]:
    return [name for name in COMPARE if len({row.get(name) for row in rows}) > 1]


def deduplicate(rows: list[Row], backfill: bool = True) -> DedupeResult:
    result = DedupeResult(reasons={reason: 0 for reason in REASONS})

    groups: dict[str, list[Row]] = {}
    order: list[str] = []
    for row in rows:
        key = fold(row.sku)
        if not key:
            # No sku means nothing to dedupe on. validate.py rejects it; it is
            # not silently merged into some other product on a name match.
            result.kept.append(row)
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    for key in order:
        group = groups[key]
        if len(group) == 1:
            result.kept.append(group[0])
            continue

        result.groups += 1
        result.rows_involved += len(group)
        winner, reason, losers = _choose(group)

        if winner is None:
            result.reasons["unresolved tie"] += 1
            columns = _conflicts(group)
            lines = ", ".join(str(r.line) for r in group)
            # Front-loaded on purpose: the values that disagree are the first
            # thing a human needs, and the first thing that survives when this
            # sentence is shown in a fixed-width column.
            detail = "; ".join(
                f"{name} " + " vs ".join(sorted({r.get(name) or "(empty)" for r in group}))
                for name in columns[:3]
            )
            for row in group:
                others = [r for r in group if r is not row]
                row.flag(
                    "duplicate_unresolved",
                    "",
                    f"{len(group)} equally recent, equally complete rows disagree — "
                    f"{detail} (lines {lines}). Neither picked: choosing would be a guess",
                    REJECT,
                )
                row.record(
                    "sku",
                    "dedupe.unresolved",
                    row.sku,
                    "",
                    DROPPED,
                    f"tie with line(s) {', '.join(str(r.line) for r in others)}",
                )
            # Tied rows are kept in the pipeline so they land in rejects.csv
            # with their reason, rather than vanishing between two files.
            result.tied.extend(group)
            result.kept.extend(group)
            continue

        result.reasons[reason] += 1
        for loser in losers:
            loser.record(
                "sku",
                "dedupe.drop",
                loser.sku,
                "",
                DROPPED,
                f"kept line {winner.line} instead ({reason})",
            )
            result.dropped.append(loser)
        winner.record(
            "sku",
            "dedupe.keep",
            winner.sku,
            winner.sku,
            "changed",
            f"{len(group)} rows for this sku; kept this one ({reason}), "
            f"dropped line(s) {', '.join(str(r.line) for r in losers)}",
        )
        if backfill:
            result.backfills += _backfill(winner, losers)
        result.kept.append(winner)

    result.kept.sort(key=lambda row: row.line)
    return result


def _choose(group: list[Row]) -> tuple[Row | None, str, list[Row]]:
    """The ladder. Returns (winner or None, reason, losers)."""
    if len({signature(row) for row in group}) == 1:
        winner = min(group, key=lambda row: row.line)
        return winner, "identical", [r for r in group if r is not winner]

    stamped = [(parse_timestamp(row.get("updated_at")), row) for row in group]
    usable = [(ts, row) for ts, row in stamped if ts is not None]
    if usable:
        newest = max(ts for ts, _ in usable)
        leaders = [row for ts, row in usable if ts == newest]
        if len(leaders) == 1:
            winner = leaders[0]
            return winner, "newest updated_at", [r for r in group if r is not winner]
        group = leaders  # every later rule only considers the freshest rows

    for reason, score in (
        ("more complete", lambda row: _populated(row, CORE)),
        ("more columns populated", _all_fields),
    ):
        best = max(score(row) for row in group)
        leaders = [row for row in group if score(row) == best]
        if len(leaders) == 1:
            winner = leaders[0]
            return winner, reason, [r for r in group if r is not winner]
        group = leaders

    return None, "unresolved tie", []


def _backfill(winner: Row, losers: list[Row]) -> int:
    """Fill the winner's empty descriptive fields from the dropped rows.

    Only ever fills an empty cell, never replaces a populated one, and logs the
    line it took the value from so the provenance is in the change log and not
    in somebody's memory.
    """
    filled = 0
    for name in BACKFILL:
        if winner.get(name):
            continue
        for loser in sorted(losers, key=lambda row: row.line):
            value = loser.get(name)
            if not value:
                continue
            winner.values[name] = value
            winner.record(
                name,
                "dedupe.backfill",
                "",
                value,
                "changed",
                f"empty here, taken from dropped line {loser.line}",
            )
            filled += 1
            break
    return filled
