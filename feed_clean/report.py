"""The four files that come out, and the screen you read instead of them.

`clean.csv` is the feed you upload. `rejects.csv` is the file you send back to
the supplier. `changes.csv` is the answer to "what did your tool do to my
data", one line per edit, forever. `summary.txt` is what fits on a screen at
11pm when you want to know whether to upload or to go to bed.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .dedupe import DedupeResult
from .models import CHANGED, REJECT, REVIEW, UNRESOLVED, Row

# The shape of the clean feed. Canonical names, one unit per column, stated in
# the header where a unit is involved so nobody has to ask.
CLEAN_COLUMNS = (
    "sku",
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
    "updated_at",
)

CHANGE_COLUMNS = ("line", "sku", "field", "rule", "outcome", "before", "after", "note")


@dataclass
class Summary:
    source: str = ""
    profile: str = ""
    rows_in: int = 0
    clean: int = 0
    rejected: int = 0
    flagged: int = 0
    dedupe: DedupeResult | None = None
    normalized: Counter = field(default_factory=Counter)
    unresolved: Counter = field(default_factory=Counter)
    rejects: Counter = field(default_factory=Counter)
    flags: Counter = field(default_factory=Counter)
    rows_changed: int = 0
    mapped_headers: int = 0
    unmapped_headers: list[str] = field(default_factory=list)
    unmapped_vendors: list[str] = field(default_factory=list)
    files: dict[str, int] = field(default_factory=dict)


def _writer(path: Path, columns):
    handle = path.open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    return handle, writer


def write_clean(path: Path, rows: list[Row], extra_headers: list[str]) -> int:
    columns = list(CLEAN_COLUMNS) + list(extra_headers) + ["needs_review", "issues"]
    handle, writer = _writer(path, columns)
    with handle:
        for row in rows:
            record = {name: row.get(name) for name in CLEAN_COLUMNS}
            record.update({header: row.extra.get(header, "") for header in extra_headers})
            record["needs_review"] = "yes" if row.needs_review else "no"
            record["issues"] = row.issue_text()
            writer.writerow(record)
    return len(rows)


def write_rejects(path: Path, rows: list[Row], original_headers: list[str]) -> int:
    """Rejected rows, each carrying the supplier's original line unchanged.

    The point is that the supplier can open this, read the reason, fix the cell
    in front of them and send it back. A rejects file that shows our canonical
    version of their row makes them do the translation twice.
    """
    columns = ["line", "sku", "reject_rules", "reason"] + list(original_headers)
    handle, writer = _writer(path, columns)
    with handle:
        for row in rows:
            record = dict(row.original)
            record["line"] = row.line
            record["sku"] = row.sku
            record["reject_rules"] = " ".join(sorted(set(row.rules(REJECT))))
            record["reason"] = "; ".join(
                str(issue) for issue in row.issues if issue.severity == REJECT
            )
            writer.writerow(record)
    return len(rows)


def write_changes(path: Path, rows: list[Row]) -> int:
    handle, writer = _writer(path, CHANGE_COLUMNS)
    count = 0
    with handle:
        for change in sorted(
            (c for row in rows for c in row.changes), key=lambda c: (c.line, c.field, c.rule)
        ):
            writer.writerow(
                {
                    "line": change.line,
                    "sku": change.sku,
                    "field": change.field,
                    "rule": change.rule,
                    "outcome": change.outcome,
                    "before": change.before,
                    "after": change.after,
                    "note": change.note,
                }
            )
            count += 1
    return count


def summarise(
    source: str,
    profile_name: str,
    all_rows: list[Row],
    clean_rows: list[Row],
    reject_rows: list[Row],
    result: DedupeResult,
    mapped: list[str],
    unmapped: list[str],
) -> Summary:
    summary = Summary(
        source=source,
        profile=profile_name,
        rows_in=len(all_rows),
        clean=len(clean_rows),
        rejected=len(reject_rows),
        flagged=sum(1 for row in clean_rows if row.needs_review),
        dedupe=result,
        mapped_headers=len(mapped),
        unmapped_headers=list(unmapped),
    )

    changed_rows = set()
    for row in all_rows:
        for change in row.changes:
            if change.rule.startswith("dedupe."):
                continue
            if change.outcome == CHANGED:
                summary.normalized[change.rule] += 1
                changed_rows.add(row.line)
            elif change.outcome == UNRESOLVED:
                summary.unresolved[change.rule] += 1
    summary.rows_changed = len(changed_rows)

    for row in reject_rows:
        for rule in set(row.rules(REJECT)):
            summary.rejects[rule] += 1
    for row in clean_rows:
        for rule in set(row.rules(REVIEW)):
            summary.flags[rule] += 1

    seen: dict[str, None] = {}
    for row in clean_rows:
        if row.values.get("vendor_unmapped") and row.get("vendor"):
            seen[row.get("vendor")] = None
    summary.unmapped_vendors = sorted(seen)
    return summary


def _breakdown(counter: Counter, indent: str = "      ", top: int = 4) -> list[str]:
    lines = []
    for rule, count in counter.most_common(top):
        lines.append(f"{indent}{rule:<32}{count:>5}")
    remaining = len(counter) - top
    if remaining > 0:
        tail = sum(count for _, count in counter.most_common()[top:])
        lines.append(f"{indent}{f'... and {remaining} more rule(s)':<32}{tail:>5}")
    return lines


def _top(counter: Counter, top: int = 3) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{rule} {count}" for rule, count in counter.most_common(top))


def render_brief(summary: Summary) -> str:
    """Eight lines: what a cron log wants, and what fits in a screenshot.

    Every number here also appears in the full report, and the last line says
    where the full report went, so this is a shorter view of the same run
    rather than a different one.
    """
    out: list[str] = []
    result = summary.dedupe
    out.append(f"feed-clean · {summary.source}")
    out.append(
        f"  {summary.rows_in} rows in  ->  {summary.clean} clean  ·  "
        f"{summary.rejected} rejected  ·  {summary.flagged} kept but flagged"
    )
    if result and result.groups:
        tie = result.reasons.get("unresolved tie", 0)
        out.append(
            f"  dedupe      {result.groups} skus duplicated, {len(result.dropped)} rows dropped"
            + (f", {tie} tie rejected unresolved" if tie else "")
        )
    out.append(
        f"  normalize   {sum(summary.normalized.values())} values rewritten, "
        f"{sum(summary.unresolved.values())} left empty as unreadable"
    )
    out.append(f"  reject      {summary.rejected} rows   {_top(summary.rejects)}")
    out.append(f"  flag        {summary.flagged} rows   {_top(summary.flags)}")
    unmapped = (
        f", {len(summary.unmapped_headers)} unmapped ({', '.join(summary.unmapped_headers)})"
        if summary.unmapped_headers
        else ""
    )
    out.append(f"  columns     {summary.mapped_headers} mapped{unmapped}")
    out.append(
        "  "
        + " · ".join(f"{name} {count}" for name, count in summary.files.items())
        + " · full breakdown in summary.txt"
    )
    return "\n".join(out) + "\n"


def render(summary: Summary) -> str:
    out: list[str] = []
    add = out.append

    add(f"feed-clean · {summary.source}")
    add(f"profile   · {summary.profile}")
    add("")
    add(
        f"  {summary.rows_in} rows in  ->  {summary.clean} clean  ·  "
        f"{summary.rejected} rejected  ·  {summary.flagged} kept but flagged"
    )
    add("")

    result = summary.dedupe
    if result and result.groups:
        add(
            f"DEDUPE    {result.groups} sku(s) arrived more than once "
            f"({result.rows_involved} rows involved, {len(result.dropped)} dropped)"
        )
        for reason in ("newest updated_at", "identical", "more complete", "more columns populated"):
            if result.reasons.get(reason):
                add(f"      {reason:<32}{result.reasons[reason]:>5}   won")
        if result.reasons.get("unresolved tie"):
            add(
                f"      {'unresolved tie':<32}{result.reasons['unresolved tie']:>5}"
                "   -> every row in the group rejected"
            )
        if result.backfills:
            add(f"      {result.backfills} empty field(s) backfilled from a dropped row")
    else:
        add("DEDUPE    no sku appeared twice")

    total_changes = sum(summary.normalized.values())
    add(f"NORMALIZE {total_changes} value(s) rewritten across {summary.rows_changed} row(s)")
    out.extend(_breakdown(summary.normalized))
    if summary.unresolved:
        add(
            f"      {sum(summary.unresolved.values())} value(s) could not be resolved; "
            "left empty, original kept in changes.csv"
        )

    add(f"REJECT    {summary.rejected} row(s), not in the clean feed")
    out.extend(_breakdown(summary.rejects) or ["      none"])

    add(f"FLAG      {summary.flagged} row(s) in the clean feed, marked needs_review")
    out.extend(_breakdown(summary.flags) or ["      none"])

    add(f"COLUMNS   {summary.mapped_headers} supplier header(s) mapped")
    if summary.unmapped_headers:
        add(
            f"      {len(summary.unmapped_headers)} carried through unmapped: "
            + ", ".join(summary.unmapped_headers)
        )
    if summary.unmapped_vendors:
        shown = ", ".join(summary.unmapped_vendors[:3])
        more = len(summary.unmapped_vendors) - 3
        add(
            f"      {len(summary.unmapped_vendors)} vendor(s) not in the alias map: "
            + shown
            + (f", +{more} more" if more > 0 else "")
        )
    add("")

    for name, count in summary.files.items():
        add(f"  {name:<20}{count:>6} rows")
    return "\n".join(out).rstrip() + "\n"
