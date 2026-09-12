"""Text in, values out. Pure: no rows, no profile objects, no I/O.

Every parser here has the same contract, and it is the contract the whole tool
is built on:

    * empty in, empty out — returns None and says nothing
    * understood     — returns the value
    * not understood — raises Unreadable with a message that quotes the input

There is no fourth branch where it takes its best shot. If a weight says "1.2"
and no unit, that is Unreadable, not 1.2 kilograms, because a wrong weight in a
feed ships a parcel at the wrong postage and nobody finds out for a month.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class Unreadable(Exception):
    """A value was present, was read, and was not understood."""


# --------------------------------------------------------------------------- text


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# NBSP, narrow NBSP, zero-width space, BOM: invisible, and they break every
# naive strip() and every float() downstream.
_INVISIBLE = dict.fromkeys(map(ord, "  ​﻿  "), " ")


def tidy(value: str) -> str:
    """Collapse whitespace and neutralise the invisible characters."""
    return _WS.sub(" ", (value or "").translate(_INVISIBLE)).strip()


def plain_text(value: str) -> str:
    """HTML out, entities decoded, whitespace collapsed.

    Suppliers put `Body (HTML)` in a CSV cell, so a description arrives as
    markup with entities in it. The length cap has to apply to what a shopper
    sees, not to the tags.
    """
    if not value:
        return ""
    # Tags first, then entities: unescaping first would turn a literal
    # `&lt;script&gt;` in the copy into a tag and then delete the words.
    text = _TAG.sub(" ", value)
    text = html.unescape(text)
    return tidy(text)


# --------------------------------------------------------------------------- money

# Symbols and codes seen in the wild, mapped to ISO 4217. A feed that mixes
# currencies is a real thing; converting between them is not this tool's job.
CURRENCY_SYMBOLS = {
    "$": "USD",
    "US$": "USD",
    "£": "GBP",
    "€": "EUR",
    "¥": "JPY",
    "C$": "CAD",
    "A$": "AUD",
}
CURRENCY_CODES = {"USD", "GBP", "EUR", "JPY", "CAD", "AUD", "NZD", "CHF", "SEK"}

# No whitespace inside a number. Allowing it — to catch the French "1 299,00"
# grouping — also let "$60.00 $48.00" read as the single number 60004800, which
# is the exact class of silent wrongness this tool exists to refuse. The space
# form is handled by removing the separator first, and only where the space
# really is a thousands separator.
_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_SPACE_THOUSANDS = re.compile(r"(?<=\d)\s(?=\d{3}(?:\D|$))")


def strip_space_thousands(text: str) -> str:
    """Remove a space used as a thousands separator, and only then."""
    return _SPACE_THOUSANDS.sub("", text)


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str | None

    def __str__(self) -> str:
        return f"{self.amount:.2f}"


def parse_number(text: str) -> Decimal:
    """A number with unknown grouping/decimal conventions, made unambiguous.

    The rule, stated once here and in the README:

      * both `,` and `.` present  -> the rightmost one is the decimal point
      * one separator, exactly 3 digits after it -> thousands separator
      * one separator, 1 or 2 digits after it    -> decimal point
      * anything else -> Unreadable

    The three-digit rule is what makes `1.299` and `1,299` both mean 1299,
    which is correct for a European feed and harmless for a US one: retail
    prices do not have three decimal places.
    """
    cleaned = text.replace(" ", "").replace(" ", "")
    if not cleaned:
        raise Unreadable(f"no number in {text!r}")

    has_comma, has_dot = "," in cleaned, "." in cleaned
    if has_comma and has_dot:
        decimal_sep = "," if cleaned.rindex(",") > cleaned.rindex(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        cleaned = cleaned.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        if cleaned.count(sep) > 1:
            # 1.234.567 — repeated separator can only be grouping.
            cleaned = cleaned.replace(sep, "")
        else:
            tail = cleaned.split(sep)[1]
            if len(tail) == 3:
                cleaned = cleaned.replace(sep, "")
            elif len(tail) in (1, 2):
                cleaned = cleaned.replace(sep, ".")
            else:
                raise Unreadable(f"cannot tell decimals from thousands in {text!r}")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise Unreadable(f"no number in {text!r}") from exc


def parse_money(value: str) -> Money | None:
    """A price cell into an amount and, if the cell said so, a currency."""
    text = tidy(value)
    if not text or text in {"-", "--", "—", "n/a", "N/A"}:
        return None

    currency = None
    upper = text.upper()
    for code in CURRENCY_CODES:
        # Word-boundary match so "AUDIO CABLE 1.50" is not priced in AUD.
        if re.search(rf"(?<![A-Z]){code}(?![A-Z])", upper):
            currency = code
            upper = re.sub(rf"(?<![A-Z]){code}(?![A-Z])", " ", upper)
            text = re.sub(rf"(?<![A-Za-z]){code}(?![A-Za-z])", " ", text, flags=re.I)
            break
    for symbol, code in sorted(CURRENCY_SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        if symbol in text:
            currency = currency or code
            text = text.replace(symbol, " ")
            break

    text = strip_space_thousands(tidy(text))
    # A leading minus survives currency stripping and is meaningful: a negative
    # price is not unreadable, it is readable and wrong, and validate.py is
    # where that gets said.
    negative = text.startswith("-")
    if negative:
        text = text[1:].strip()

    numbers = _NUMBER.findall(text)
    if not numbers:
        raise Unreadable(f"no number in {value.strip()!r}")
    if len(numbers) > 1:
        # A was/now cell, or a price and a pack size. Picking one is a guess,
        # and it is usually the sale price you would have wanted.
        raise Unreadable(f"more than one number in {value.strip()!r}")

    leftover = tidy(text.replace(numbers[0], "", 1))
    if leftover:
        raise Unreadable(f"{leftover!r} is not a currency, in {value.strip()!r}")

    amount = parse_number(numbers[0])
    return Money(amount=-amount if negative else amount, currency=currency)


# ------------------------------------------------------------------------- weight

GRAMS_PER = {
    "g": Decimal("1"),
    "gram": Decimal("1"),
    "grams": Decimal("1"),
    "gr": Decimal("1"),
    "kg": Decimal("1000"),
    "kgs": Decimal("1000"),
    "kilo": Decimal("1000"),
    "kilos": Decimal("1000"),
    "kilogram": Decimal("1000"),
    "kilograms": Decimal("1000"),
    "lb": Decimal("453.59237"),
    "lbs": Decimal("453.59237"),
    "pound": Decimal("453.59237"),
    "pounds": Decimal("453.59237"),
    "#": Decimal("453.59237"),
    "oz": Decimal("28.349523125"),
    "ounce": Decimal("28.349523125"),
    "ounces": Decimal("28.349523125"),
}

_WEIGHT = re.compile(r"^([\d.,]+)\s*([a-z#]*)\.?$", re.I)


def parse_weight(value: str, unit_hint: str = "") -> Decimal | None:
    """A weight into grams. The unit must come from somewhere — anywhere.

    `unit_hint` is the feed's separate unit column, which suppliers fill in
    about half the time. A bare number with no unit in either place is the
    single most common unfixable cell in a product feed and it is Unreadable
    here: 1.2 could be kilograms or pounds, and the difference is a parcel that
    costs 2.7x what you quoted.
    """
    text = strip_space_thousands(tidy(value))
    if not text or text in {"-", "--", "—", "0", "n/a", "N/A"}:
        return None

    match = _WEIGHT.match(text)
    if not match:
        raise Unreadable(f"not a weight: {value.strip()!r}")
    number, unit = match.group(1), match.group(2).lower()

    if not unit:
        unit = tidy(unit_hint).lower().rstrip(".")
        if not unit:
            raise Unreadable(f"no unit on {text!r} and no weight unit column")
    if unit not in GRAMS_PER:
        raise Unreadable(f"unknown weight unit {unit!r} in {value.strip()!r}")

    grams = parse_number(number) * GRAMS_PER[unit]
    return grams.quantize(Decimal("0.1")).normalize()


# --------------------------------------------------------------------- dimensions

MM_PER = {
    "mm": Decimal("1"),
    "millimetre": Decimal("1"),
    "millimeter": Decimal("1"),
    "cm": Decimal("10"),
    "centimetre": Decimal("10"),
    "centimeter": Decimal("10"),
    "m": Decimal("1000"),
    "metre": Decimal("1000"),
    "meter": Decimal("1000"),
    "in": Decimal("25.4"),
    "inch": Decimal("25.4"),
    "inches": Decimal("25.4"),
    '"': Decimal("25.4"),
    "ft": Decimal("304.8"),
    "foot": Decimal("304.8"),
    "feet": Decimal("304.8"),
    "'": Decimal("304.8"),
}

# 12 x 8 x 4 in   /   300mm x 200mm x 100mm   /   30 × 20 × 10 cm
_DIM_SPLIT = re.compile(r"\s*[x×*]\s*", re.I)
_DIM_PART = re.compile(r"^([\d.,]+)\s*([a-z\"']*)\.?$", re.I)


def parse_dimensions(value: str) -> tuple[Decimal, Decimal, Decimal] | None:
    """`L x W x H` into millimetres. A trailing unit applies to all three."""
    text = tidy(value)
    if not text or text in {"-", "--", "—", "n/a", "N/A"}:
        return None

    parts = _DIM_SPLIT.split(text)
    if len(parts) != 3:
        raise Unreadable(f"expected L x W x H, got {value.strip()!r}")

    numbers: list[Decimal] = []
    units: list[str] = []
    for part in parts:
        match = _DIM_PART.match(part.strip())
        if not match:
            raise Unreadable(f"{part.strip()!r} is not a measurement, in {value.strip()!r}")
        numbers.append(parse_number(match.group(1)))
        units.append(match.group(2).lower())

    named = [u for u in units if u]
    if not named:
        raise Unreadable(f"no unit on any of the three measurements in {value.strip()!r}")
    if len(set(named)) > 1:
        # Mixed units are legal but almost always a typo, and the cost of
        # guessing which one was meant is a box that does not fit.
        raise Unreadable(f"mixed units {sorted(set(named))} in {value.strip()!r}")
    unit = named[0]
    if unit not in MM_PER:
        raise Unreadable(f"unknown unit {unit!r} in {value.strip()!r}")

    factor = MM_PER[unit]
    return tuple((n * factor).quantize(Decimal("0.1")).normalize() for n in numbers)  # type: ignore[return-value]


# ------------------------------------------------------------------------ integers


def parse_quantity(value: str) -> int | None:
    text = tidy(value)
    if not text or text in {"-", "--", "—", "n/a", "N/A"}:
        return None
    try:
        number = parse_number(text)
    except Unreadable:
        raise Unreadable(f"not a whole number: {value.strip()!r}") from None
    if number != number.to_integral_value():
        raise Unreadable(f"not a whole number: {value.strip()!r}")
    return int(number)


# ------------------------------------------------------------------------ barcodes


def gtin_check_digit(digits: str) -> int:
    """Mod-10 check digit over the body of a GTIN, rightmost weighted 3."""
    total = 0
    for position, char in enumerate(reversed(digits)):
        total += int(char) * (3 if position % 2 == 0 else 1)
    return (10 - total % 10) % 10


def parse_barcode(value: str) -> str | None:
    """A GTIN-8/12/13/14, or Unreadable saying what is wrong with it."""
    text = tidy(value).replace("-", "").replace(" ", "")
    if not text or text in {"-", "--", "—", "n/a", "N/A", "0"}:
        return None

    # The 11pm classic: the supplier opened the feed in Excel, Excel decided
    # 5060123456789 was a number, and saved it back as 5.06E+12. The digits are
    # gone. They cannot be reconstructed and must not be invented.
    if re.fullmatch(r"\d(\.\d+)?[eE][+-]?\d+", text):
        raise Unreadable(f"{value.strip()!r} is a spreadsheet-mangled number, digits lost")
    if not text.isdigit():
        raise Unreadable(f"{value.strip()!r} is not all digits")
    if len(text) not in (8, 12, 13, 14):
        raise Unreadable(f"{len(text)} digits is not a GTIN length (8, 12, 13 or 14)")

    expected = gtin_check_digit(text[:-1])
    if int(text[-1]) != expected:
        raise Unreadable(f"check digit is {text[-1]}, should be {expected}")
    return text


# ----------------------------------------------------------------------- urls


_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


def parse_url(value: str, base: str = "") -> str | None:
    """An absolute http(s) URL, or Unreadable.

    A protocol-relative `//cdn.example.com/x.jpg` is fixable — there is exactly
    one sensible scheme left in 2026 — so it is fixed and logged. A path like
    `images/x.jpg` is not fixable without knowing the CDN root, so it is only
    accepted when `--image-base` supplied one.
    """
    text = tidy(value)
    if not text or text in {"-", "--", "—", "n/a", "N/A"}:
        return None

    if text.startswith("//"):
        return "https:" + text
    if _SCHEME.match(text):
        if not text.lower().startswith(("http://", "https://")):
            raise Unreadable(f"not an http(s) URL: {value.strip()!r}")
        return text
    if base:
        return base.rstrip("/") + "/" + text.lstrip("/")
    raise Unreadable(f"relative path {value.strip()!r} with no --image-base to resolve it against")


# --------------------------------------------------------------------------- case


def title_case(value: str, acronyms: dict[str, str], minor_words: set[str]) -> str:
    """Consistent product-title casing that does not destroy real information.

    Applied only to titles that are entirely upper or entirely lower case —
    a title someone actually cased is left alone. `12MM` stays `12mm`, `USB-C`
    stays `USB-C`, and `of` stays lowercase unless it leads.
    """
    words = value.split(" ")
    out: list[str] = []
    for index, word in enumerate(words):
        out.append(_case_word(word, index, len(words), acronyms, minor_words))
    return " ".join(out)


def _case_word(
    word: str, index: int, total: int, acronyms: dict[str, str], minor_words: set[str]
) -> str:
    if not word:
        return word

    core = word.strip(".,()[]\"'")
    prefix = word[: len(word) - len(word.lstrip(".,()[]\"'"))]
    suffix = word[len(prefix) + len(core) :]
    if not core:
        return word

    # The whole word is looked up first, so a compound acronym like USB-C beats
    # the hyphen-splitting below. Splitting first produced "Usb-C" — a detail
    # a client notices on every product page at once.
    known = acronyms.get(core.lower())
    if known is not None:
        return prefix + known + suffix

    # Otherwise a hyphenated or slashed compound is cased part by part, so
    # "ip67/ipx4" still comes out right.
    for sep in ("-", "/"):
        if sep in core.strip(sep):
            parts = core.split(sep)
            return (
                prefix
                + sep.join(
                    _case_word(p, index if i == 0 else 1, total, acronyms, minor_words)
                    for i, p in enumerate(parts)
                )
                + suffix
            )

    if re.match(r"^\d+(\.\d+)?[a-z]{1,3}$", core, re.I):
        # A measurement: 12mm, 9m, 500g. Lower-case unit, never "12Mm".
        return prefix + core.lower() + suffix
    if any(ch.isdigit() for ch in core):
        return prefix + core.upper() + suffix
    if core.lower() in minor_words and 0 < index < total - 1:
        return prefix + core.lower() + suffix
    return prefix + core[0].upper() + core[1:].lower() + suffix


def fold(value: str) -> str:
    """The key two spellings of the same vendor name have in common."""
    return re.sub(r"[^a-z0-9]+", " ", tidy(value).lower()).strip()
