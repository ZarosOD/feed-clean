"""The rules a marketplace would bounce the row on, applied before they do.

Two severities, and the difference matters:

  **reject** — the row cannot be listed. It goes to `rejects.csv` with the rule
  and a sentence saying what to fix, and it is not in the clean feed. Better an
  import of 287 rows that all work than 306 rows and an error report.

  **review** — the row can be listed but something in it could not be resolved.
  It is in the clean feed with `needs_review=yes` and the reason in `issues`.

Nothing here edits a value. By the time validation runs, every value is either
canonical or empty; this only decides what that means.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .models import REJECT, REVIEW, Row
from .profile import Profile

# What a missing required field is called in the reject report.
MISSING = {
    "sku": "no sku — this row cannot be matched, updated or deduped",
    "title": "no title — nothing to list it under",
    "price": "no price",
    "image_url": "no image",
    "barcode": "no barcode",
    "vendor": "no vendor",
    "description": "no description",
}


def _decimal(row: Row, field: str) -> Decimal | None:
    value = row.get(field)
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:  # pragma: no cover - normalize guarantees the format
        return None


def _escalate(row: Row, field: str) -> str:
    """Promote an existing review flag on a required field to a rejection.

    A weight that could not be read is a note. A *price* that could not be read
    is the same fact about a field the marketplace requires, so it stops being
    a note and starts being a rejection — without losing the original message,
    which is the part that tells you what the cell actually said.
    """
    detail = ""
    for index, issue in enumerate(row.issues):
        if issue.field == field and issue.severity == REVIEW:
            detail = issue.message
            row.issues[index] = type(issue)(
                rule=issue.rule, field=issue.field, message=issue.message, severity=REJECT
            )
    return detail


def validate(row: Row, profile: Profile) -> None:
    # The field-specific rules run first so that _required can see a rejection
    # that already explains the empty cell and keep quiet. One empty price
    # should produce one reason, not "missing_price" stacked on top of the
    # sentence that says what the cell actually contained.
    _barcode(row)
    _image(row)
    _required(row, profile)
    _prices(row)
    _lengths(row, profile)
    _stock(row)


def _required(row: Row, profile: Profile) -> None:
    for field in profile.required:
        if row.get(field):
            continue
        if any(issue.field == field and issue.severity == REJECT for issue in row.issues):
            continue  # already rejected on this field, with a better sentence
        if _escalate(row, field):
            # The field was there and unreadable, which is a different problem
            # from the field being absent and a different conversation with the
            # supplier. Its own message is the one worth keeping.
            continue
        row.flag(f"missing_{field}", field, MISSING.get(field, f"no {field}"), REJECT)


def _prices(row: Row) -> None:
    price = _decimal(row, "price")
    cost = _decimal(row, "cost")
    compare_at = _decimal(row, "compare_at")

    if price is not None and price <= 0:
        row.flag(
            "price_not_positive",
            "price",
            f"price is {price:.2f} — a marketplace reads that as free, not as a placeholder",
            REJECT,
        )
    if price is not None and cost is not None and price < cost:
        row.flag(
            "price_below_cost",
            "price",
            f"price {price:.2f} is below cost {cost:.2f} — selling at a "
            f"{cost - price:.2f} loss per unit",
            REJECT,
        )
    if price is not None and compare_at is not None and compare_at <= price and compare_at > 0:
        row.flag(
            "compare_at_not_above_price",
            "compare_at",
            f"compare-at {compare_at:.2f} is not above the price {price:.2f} — "
            "the strike-through would show a fake discount",
            REVIEW,
        )


def _barcode(row: Row) -> None:
    error = row.values.get("barcode_error")
    if error:
        row.flag("barcode_invalid", "barcode", str(error), REJECT)


def _image(row: Row) -> None:
    error = row.values.get("image_error")
    if error and not row.get("image_url"):
        row.flag("image_unusable", "image_url", str(error), REJECT)


def _lengths(row: Row, profile: Profile) -> None:
    description = row.get("description")
    if len(description) > profile.description_max:
        row.flag(
            "description_too_long",
            "description",
            f"{len(description)} characters of visible text, cap is "
            f"{profile.description_max} — truncating it here would cut a sentence in half",
            REJECT,
        )
    title = row.get("title")
    if len(title) > profile.title_max:
        row.flag(
            "title_too_long",
            "title",
            f"{len(title)} characters, cap is {profile.title_max}",
            REVIEW,
        )


def _stock(row: Row) -> None:
    """Quantity and stock state telling different stories."""
    quantity = row.values.get("quantity")
    status = row.get("stock_status")
    if not isinstance(quantity, int) or not status:
        return
    if quantity <= 0 and status == "in_stock":
        row.flag(
            "stock_inconsistent",
            "stock_status",
            f"says in stock with {quantity} on hand — one of the two columns is wrong",
            REVIEW,
        )
    if quantity > 0 and status in ("out_of_stock", "discontinued"):
        row.flag(
            "stock_inconsistent",
            "stock_status",
            f"says {status.replace('_', ' ')} with {quantity} on hand — "
            "one of the two columns is wrong",
            REVIEW,
        )
