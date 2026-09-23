"""The files that come out, and the screen you read instead of them.

`clean.csv` is the feed you upload. `rejects.csv` is the file you send back to
the supplier. `changes.csv` is the answer to "what did your tool do to my
data", one line per edit, forever. `summary.txt` is what fits on a screen at
11pm when you want to know whether to upload or to go to bed.

`clean.xlsx` is those same three tables in one workbook, because a client asks
for Excel and not for CSV. It is written whenever `openpyxl` imports and
skipped — with a line in the summary saying so — when it does not: this tool's
base install has no dependencies at all and that is worth keeping.

Each table is defined once, as a `Table` of `(columns, records)`, and then
rendered by whichever writer is asked for it. The CSV and the worksheet are two
renderers over one definition, rather than two definitions with a test holding
them level.
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


@dataclass(frozen=True)
class Table:
    """One output table: its header row and its records, defined once.

    Both `write_csv` and the worksheet builder consume this, so `clean.csv` and
    the workbook's Clean sheet cannot disagree about a column or a value —
    there is nothing for them to disagree about.

    `flagged` names the records the workbook should tint. It is a property of
    the table (which rows this tool would not vouch for), not of the renderer,
    which is why it lives here and not in the xlsx code.
    """

    name: str
    columns: list[str]
    records: list[dict]
    flagged: frozenset[int] = frozenset()

    def __len__(self) -> int:
        return len(self.records)

    def cells(self, record: dict) -> list:
        return [record.get(column, "") for column in self.columns]


def clean_table(rows: list[Row], extra_headers: list[str]) -> Table:
    columns = list(CLEAN_COLUMNS) + list(extra_headers) + ["needs_review", "issues"]
    records, flagged = [], set()
    for index, row in enumerate(rows):
        record = {name: row.get(name) for name in CLEAN_COLUMNS}
        record.update({header: row.extra.get(header, "") for header in extra_headers})
        record["needs_review"] = "yes" if row.needs_review else "no"
        record["issues"] = row.issue_text()
        records.append(record)
        if row.needs_review:
            flagged.add(index)
    return Table("Clean", columns, records, frozenset(flagged))


def rejects_table(rows: list[Row], original_headers: list[str]) -> Table:
    """Rejected rows, each carrying the supplier's original line unchanged.

    The point is that the supplier can open this, read the reason, fix the cell
    in front of them and send it back. A rejects file that shows our canonical
    version of their row makes them do the translation twice.
    """
    columns = ["line", "sku", "reject_rules", "reason"] + list(original_headers)
    records = []
    for row in rows:
        record = dict(row.original)
        record["line"] = row.line
        record["sku"] = row.sku
        record["reject_rules"] = " ".join(sorted(set(row.rules(REJECT))))
        record["reason"] = "; ".join(
            str(issue) for issue in row.issues if issue.severity == REJECT
        )
        records.append(record)
    # Every row in this file is a rejection, so every row is tinted.
    return Table("Rejects", columns, records, frozenset(range(len(records))))


def changes_table(rows: list[Row]) -> Table:
    records = [
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
        for change in sorted(
            (c for row in rows for c in row.changes), key=lambda c: (c.line, c.field, c.rule)
        )
    ]
    flagged = {i for i, r in enumerate(records) if r["outcome"] == UNRESOLVED}
    return Table("Changes", list(CHANGE_COLUMNS), records, frozenset(flagged))


def write_csv(path: Path, table: Table) -> int:
    handle = path.open("w", newline="", encoding="utf-8")
    with handle:
        writer = csv.DictWriter(handle, fieldnames=table.columns, extrasaction="ignore")
        writer.writeheader()
        for record in table.records:
            writer.writerow(record)
    return len(table)


def write_clean(path: Path, rows: list[Row], extra_headers: list[str]) -> int:
    return write_csv(path, clean_table(rows, extra_headers))


def write_rejects(path: Path, rows: list[Row], original_headers: list[str]) -> int:
    return write_csv(path, rejects_table(rows, original_headers))


def write_changes(path: Path, rows: list[Row]) -> int:
    return write_csv(path, changes_table(rows))


# --------------------------------------------------------------------------
# the workbook
# --------------------------------------------------------------------------

XLSX_AVAILABLE_ERROR = (
    "openpyxl is not installed, so out/clean.xlsx was not written. "
    "The CSVs are complete on their own; `pip install 'feed-clean[xlsx]'` "
    "adds the workbook."
)

# Numeric-looking columns are written as numbers, not text, so the client can
# sum a price column without retyping it. Anything not named here stays text —
# a sku like "0012" or a barcode is a string, and Excel eats the leading zero
# the moment it decides otherwise.
NUMERIC_COLUMNS = frozenset(
    {"price", "cost", "compare_at", "weight_g", "length_mm", "width_mm",
     "height_mm", "quantity", "line"}
)

# Money keeps its two decimals on screen. Without this the cell holds 1299 and
# Excel prints "1299", which disagrees with clean.csv's "1299.00" over nothing:
# the value is identical, only the display was missing.
MONEY_COLUMNS = frozenset({"price", "cost", "compare_at"})
MONEY_FORMAT = "0.00"

# Kept narrow enough to read; `description` is a paragraph and gets clipped by
# the column rather than stretching the sheet off the screen.
COLUMN_WIDTH = {"title": 34, "description": 40, "issues": 46, "reason": 46,
                "image_url": 30, "tags": 26, "note": 30}
DEFAULT_WIDTH = 15


def xlsx_available() -> bool:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return False
    return True


def _as_number(column: str, value):
    if column not in NUMERIC_COLUMNS or value in ("", None):
        return value
    try:
        text = str(value)
        return int(text) if text.lstrip("-").isdigit() else float(text)
    except ValueError:
        return value


def write_workbook(path: Path, tables: list[Table]) -> int:
    """The same tables, in one .xlsx. Returns the number of data rows written.

    Sheet order is the order it is handed, and the first sheet is the one the
    file opens on — Clean, because that is the file the client is here for.
    Flagged rows are tinted with the same meaning everywhere: amber is "kept,
    but we would not vouch for this cell".
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2F3E4E")
    flag_fill = PatternFill("solid", fgColor="FFF4D6")

    book = Workbook()
    book.remove(book.active)
    written = 0

    for table in tables:
        sheet = book.create_sheet(table.name)
        sheet.append(table.columns)
        for cell in sheet[1]:
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = Alignment(vertical="center")

        money = [i for i, c in enumerate(table.columns) if c in MONEY_COLUMNS]
        for index, record in enumerate(table.records):
            sheet.append(
                [_as_number(column, record.get(column, "")) for column in table.columns]
            )
            written_row = sheet[sheet.max_row]
            for position in money:
                if isinstance(written_row[position].value, (int, float)):
                    written_row[position].number_format = MONEY_FORMAT
            if index in table.flagged:
                for cell in written_row:
                    cell.fill = flag_fill
        written += len(table)

        for position, column in enumerate(table.columns, start=1):
            sheet.column_dimensions[get_column_letter(position)].width = COLUMN_WIDTH.get(
                column, DEFAULT_WIDTH
            )
        # The header stays put when the client scrolls, and the filter arrows
        # are there because the first thing anyone does to a rejects sheet is
        # filter it.
        sheet.freeze_panes = "A2"
        if len(table):
            sheet.auto_filter.ref = (
                f"A1:{get_column_letter(len(table.columns))}{len(table) + 1}"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    return written


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
