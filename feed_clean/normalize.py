"""Turn one raw row into one canonical row, logging every single edit.

The rule this module exists to enforce: a value either comes out in the
canonical form with a `Change` explaining how it got there, or it does not come
out at all and there is an `Issue` saying why. There is no third path where a
cell quietly becomes something else.

Rule ids are `<field>.<what>` and they are stable — they are what you grep the
change log for, and what you point a supplier at.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from typing import Iterable, Iterator

from . import parse
from .models import CHANGED, REVIEW, UNRESOLVED, Row
from .parse import Unreadable
from .profile import Profile


def read_feed(handle: Iterable[str], profile: Profile) -> tuple[list[Row], list[str], list[str]]:
    """Read the CSV into rows, mapping supplier headers onto canonical fields.

    Returns the rows, the headers that were understood, and the headers that
    were not. Unmapped columns are *kept*, carried through to the output and
    reported — a column you did not recognise is not a column you get to throw
    away, because it is usually the one the client's warehouse sorts on.
    """
    reader = csv.DictReader(handle)
    headers = reader.fieldnames or []
    mapped: dict[str, str] = {}
    unmapped: list[str] = []
    for header in headers:
        field = profile.canonical_field(header)
        if field is None:
            unmapped.append(header)
        else:
            mapped[header] = field

    rows: list[Row] = []
    for offset, record in enumerate(reader):
        # Line 1 is the header, so the first data row is line 2 — which is what
        # the client's spreadsheet says, and the number they will quote at you.
        row = Row(line=offset + 2, raw={}, extra={})
        for header, value in record.items():
            if header is None:
                continue
            value = value or ""
            row.original[header] = value
            if header in mapped:
                row.raw[mapped[header]] = value
            else:
                row.extra[header] = parse.tidy(value)
        rows.append(row)
    return rows, sorted(set(mapped.values())), unmapped


def normalize(row: Row, profile: Profile, image_base: str = "") -> None:
    """Apply every normalisation rule to one row, in place."""
    _text_fields(row)
    _title(row, profile)
    _vendor(row, profile)
    _money(row, profile)
    _weight(row)
    _dimensions(row)
    _quantity(row)
    _stock_status(row, profile)
    _booleans(row, profile)
    _barcode(row)
    _image(row, image_base)
    _description(row)
    _passthrough(row)


# ------------------------------------------------------------------ plain strings


def _set(row: Row, field: str, value, before: str, rule: str, note: str = "") -> None:
    """Store a value, and log a change only if the text actually moved."""
    after = "" if value is None else str(value)
    row.values[field] = value
    if after != before:
        row.record(field, rule, before, after, CHANGED, note)


def _unresolved(row: Row, field: str, rule: str, before: str, exc: Unreadable, severity=REVIEW):
    """Refuse to write a value, and say so in both places it needs saying."""
    row.values[field] = None
    row.record(field, rule, before, "", UNRESOLVED, str(exc))
    row.flag(rule, field, str(exc), severity)


def _text_fields(row: Row) -> None:
    for field in ("sku", "handle", "product_type", "tags", "updated_at"):
        before = row.raw.get(field, "")
        _set(row, field, parse.tidy(before), before, f"{field}.whitespace")


def _title(row: Row, profile: Profile) -> None:
    before = row.raw.get("title", "")
    text = parse.plain_text(before)
    if text and (text.isupper() or text.islower()):
        # Only rewrite casing nobody chose. A title with deliberate mixed case
        # ("iPhone", "pH Test Strips") is left exactly as the supplier sent it.
        text = parse.title_case(text, profile.acronyms, profile.minor_words)
        rule = "title.case"
    else:
        rule = "title.whitespace"
    _set(row, "title", text, before, rule)


def _vendor(row: Row, profile: Profile) -> None:
    before = row.raw.get("vendor", "")
    text = parse.plain_text(before)
    if not text:
        _set(row, "vendor", "", before, "vendor.whitespace")
        return
    canonical = profile.vendors.get(parse.fold(text))
    if canonical:
        _set(row, "vendor", canonical, before, "vendor.canonical")
        return
    # Not in the alias map. Case-normalise it and note it, rather than inventing
    # a mapping — "Harbourline" and "Harbourline Outfitters" might be one
    # company or two, and only the client knows.
    tidied = parse.title_case(text, profile.acronyms, profile.minor_words) if (
        text.isupper() or text.islower()
    ) else text
    _set(row, "vendor", tidied, before, "vendor.whitespace", note="not in the alias map")
    row.values["vendor_unmapped"] = True


# ------------------------------------------------------------------------- money


def _money_field(row: Row, field: str, profile: Profile) -> None:
    before = row.raw.get(field, "")
    if not parse.tidy(before):
        row.values[field] = None
        return
    try:
        money = parse.parse_money(before)
    except Unreadable as exc:
        _unresolved(row, field, f"{field}.format", before, exc)
        return
    if money is None:
        row.values[field] = None
        return

    currency = money.currency or profile.currency
    row.values[f"{field}_currency"] = currency
    _set(row, field, f"{money.amount:.2f}", before, f"{field}.format")
    if money.currency and money.currency != profile.currency:
        # Emphatically not converted. An FX rate this tool invented would be
        # wrong by the time the feed uploaded, and nobody would ever see it.
        row.flag(
            f"{field}.currency_mismatch",
            field,
            f"{money.currency} in a {profile.currency} feed — "
            "not converted, an exchange rate would be a guess",
            REVIEW,
        )


def _money(row: Row, profile: Profile) -> None:
    for field in ("price", "cost", "compare_at"):
        _money_field(row, field, profile)
    row.values.setdefault("currency", row.values.get("price_currency") or profile.currency)


# ------------------------------------------------------- weight and dimensions


def _weight(row: Row) -> None:
    before = row.raw.get("weight", "")
    unit_hint = row.raw.get("weight_unit", "")
    row.values["weight_unit"] = parse.tidy(unit_hint)
    if not parse.tidy(before):
        row.values["weight_g"] = None
        return
    try:
        grams = parse.parse_weight(before, unit_hint)
    except Unreadable as exc:
        _unresolved(row, "weight_g", "weight.unit", before, exc)
        return
    shown = before if not unit_hint else f"{parse.tidy(before)} {parse.tidy(unit_hint)}"
    _set(row, "weight_g", _plain(grams), shown, "weight.unit")


def _dimensions(row: Row) -> None:
    before = row.raw.get("dimensions", "")
    if not parse.tidy(before):
        for field in ("length_mm", "width_mm", "height_mm"):
            row.values[field] = None
        return
    try:
        dims = parse.parse_dimensions(before)
    except Unreadable as exc:
        for field in ("length_mm", "width_mm", "height_mm"):
            row.values[field] = None
        row.record("dimensions", "dimensions.unit", before, "", UNRESOLVED, str(exc))
        row.flag("dimensions.unit", "dimensions", str(exc), REVIEW)
        return
    after = " x ".join(_plain(d) for d in dims)
    row.values["length_mm"], row.values["width_mm"], row.values["height_mm"] = (
        _plain(d) for d in dims
    )
    if after != parse.tidy(before):
        row.record("dimensions", "dimensions.unit", before, after + " mm", CHANGED)


def _plain(value: Decimal) -> str:
    """A decimal without scientific notation or a trailing `.0`."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


# ------------------------------------------------------- vocabularies and counts


def _quantity(row: Row) -> None:
    before = row.raw.get("quantity", "")
    if not parse.tidy(before):
        row.values["quantity"] = None
        return
    try:
        _set(row, "quantity", parse.parse_quantity(before), before, "quantity.format")
    except Unreadable as exc:
        _unresolved(row, "quantity", "quantity.format", before, exc)


def _stock_status(row: Row, profile: Profile) -> None:
    before = row.raw.get("stock_status", "")
    text = parse.tidy(before)
    if not text:
        row.values["stock_status"] = None
        return
    canonical = profile.stock_status.get(parse.fold(text))
    if canonical is None:
        _unresolved(
            row,
            "stock_status",
            "stock_status.vocabulary",
            before,
            Unreadable(
                f"{text!r} is not a stock state this profile knows. "
                "Add it to stock_status in the profile if it is real"
            ),
        )
        return
    _set(row, "stock_status", canonical, before, "stock_status.vocabulary")


def _booleans(row: Row, profile: Profile) -> None:
    for field in ("published", "taxable"):
        before = row.raw.get(field, "")
        text = parse.tidy(before)
        if not text:
            row.values[field] = None
            continue
        value = profile.booleans.get(parse.fold(text))
        if value is None:
            _unresolved(
                row,
                field,
                f"{field}.vocabulary",
                before,
                Unreadable(f"{text!r} is not a yes or a no"),
            )
            continue
        _set(row, field, "true" if value else "false", before, f"{field}.vocabulary")


# ----------------------------------------------------------- barcode, image, copy


def _barcode(row: Row) -> None:
    before = row.raw.get("barcode", "")
    if not parse.tidy(before):
        row.values["barcode"] = None
        return
    try:
        _set(row, "barcode", parse.parse_barcode(before), before, "barcode.format")
    except Unreadable as exc:
        # Severity is decided in validate.py; here it is only recorded.
        row.values["barcode"] = None
        row.record("barcode", "barcode.check", before, "", UNRESOLVED, str(exc))
        row.values["barcode_error"] = str(exc)


def _image(row: Row, image_base: str) -> None:
    before = row.raw.get("image_url", "")
    if not parse.tidy(before):
        row.values["image_url"] = None
        return
    try:
        _set(row, "image_url", parse.parse_url(before, image_base), before, "image_url.scheme")
    except Unreadable as exc:
        row.values["image_url"] = None
        row.record("image_url", "image_url.scheme", before, "", UNRESOLVED, str(exc))
        row.values["image_error"] = str(exc)


def _description(row: Row) -> None:
    before = row.raw.get("description", "")
    _set(row, "description", parse.plain_text(before), before, "description.html")


def _passthrough(row: Row) -> None:
    """Fields that are carried, not interpreted."""
    for field in ("compare_at_currency", "cost_currency"):
        row.values.setdefault(field, None)


def normalize_all(rows: Iterable[Row], profile: Profile, image_base: str = "") -> Iterator[Row]:
    for row in rows:
        normalize(row, profile, image_base)
        yield row
