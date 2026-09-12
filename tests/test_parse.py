"""The parsers, on strings. No files, no rows, no profile.

Most of this suite is here: the parsers are where a feed cleaner is either
trustworthy or quietly wrong, and they are pure, so there is no excuse for
thin coverage.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feed_clean import parse
from feed_clean.parse import Unreadable


# ------------------------------------------------------------------------- text


@pytest.mark.parametrize(
    "raw, want",
    [
        ("  Brass   Lantern ", "Brass Lantern"),
        ("Brass Lantern", "Brass Lantern"),
        ("﻿Brass Lantern", "Brass Lantern"),
        ("", ""),
    ],
)
def test_tidy_collapses_and_neutralises_invisibles(raw, want):
    assert parse.tidy(raw) == want


def test_plain_text_strips_tags_then_unescapes():
    assert parse.plain_text("<p>Hard-wearing &amp; simple</p>") == "Hard-wearing & simple"


def test_plain_text_does_not_resurrect_escaped_markup():
    """`&lt;script&gt;` in the copy is words, not a tag, and must survive."""
    assert parse.plain_text("Use &lt;b&gt; for bold") == "Use <b> for bold"


# ------------------------------------------------------------------------ money


@pytest.mark.parametrize(
    "raw, amount, currency",
    [
        ("$1,299.00", "1299.00", "USD"),
        ("1.299,00", "1299.00", None),
        ("1 299,00", "1299.00", None),
        ("  18,50  ", "18.50", None),
        ("USD 45.50", "45.50", "USD"),
        ("45.50 usd", "45.50", "USD"),
        ("€89,00", "89.00", "EUR"),
        ("£39.99", "39.99", "GBP"),
        ("-12.00", "-12.00", None),
        ("1299", "1299", None),
        ("1.234.567", "1234567", None),
    ],
)
def test_parse_money(raw, amount, currency):
    money = parse.parse_money(raw)
    assert money is not None
    assert money.amount == Decimal(amount)
    assert money.currency == currency


@pytest.mark.parametrize("raw", ["", "  ", "-", "n/a", "—"])
def test_parse_money_empty_is_none_not_zero(raw):
    assert parse.parse_money(raw) is None


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ("Call for quote", "no number"),
        ("POA", "no number"),
        ("$60.00 $48.00", "more than one number"),
        ("AUDIO CABLE 1.50", "not a currency"),
    ],
)
def test_parse_money_refuses_rather_than_guesses(raw, fragment):
    with pytest.raises(Unreadable) as exc:
        parse.parse_money(raw)
    assert fragment in str(exc.value)
    assert raw.strip() in str(exc.value)


def test_was_now_cell_is_not_silently_concatenated():
    """The regression that made this test exist.

    A number pattern that allowed an internal space read `$60.00 $48.00` as the
    single number 60004800 and wrote it into the feed. Wrong by six orders of
    magnitude, and completely silent.
    """
    with pytest.raises(Unreadable):
        parse.parse_money("$60.00 $48.00")


@pytest.mark.parametrize(
    "raw, want",
    [("1,299", "1299"), ("1.299", "1299"), ("1,29", "1.29"), ("1.29", "1.29")],
)
def test_separator_rule_is_the_stated_one(raw, want):
    assert parse.parse_number(raw) == Decimal(want)


def test_four_decimals_is_ambiguous_and_refused():
    with pytest.raises(Unreadable):
        parse.parse_number("1.2999")


# ------------------------------------------------------------------------ weight


@pytest.mark.parametrize(
    "raw, hint, grams",
    [
        ("2.5", "kg", "2500"),
        ("500 g", "", "500"),
        ("1.1lb", "", "499"),
        ("12 oz", "", "340.2"),
        ("0,75 kg", "", "750"),
        ("2 KG", "", "2000"),
        ("1.5", "lbs", "680.4"),
    ],
)
def test_parse_weight(raw, hint, grams):
    assert parse.parse_weight(raw, hint) == Decimal(grams)


def test_a_bare_number_with_no_unit_anywhere_is_unreadable():
    with pytest.raises(Unreadable) as exc:
        parse.parse_weight("1.2", "")
    assert "no unit" in str(exc.value)


def test_unknown_unit_names_itself():
    with pytest.raises(Unreadable) as exc:
        parse.parse_weight("3 stone", "")
    assert "'stone'" in str(exc.value)


def test_weight_unit_column_supplies_the_missing_unit():
    assert parse.parse_weight("1.2", "kg") == Decimal("1200")


# -------------------------------------------------------------------- dimensions


@pytest.mark.parametrize(
    "raw, want",
    [
        ("12 x 8 x 4 in", ("304.8", "203.2", "101.6")),
        ("300mm x 200mm x 100mm", ("300", "200", "100")),
        ("30 × 20 × 10 cm", ("300", "200", "100")),
        ("1.2 x 0.4 x 0.4 m", ("1200", "400", "400")),
    ],
)
def test_parse_dimensions(raw, want):
    assert parse.parse_dimensions(raw) == tuple(Decimal(v) for v in want)


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ("12 x 8", "expected L x W x H"),
        ("12 x 8 x 4", "no unit"),
        ("30cm x 20in x 10cm", "mixed units"),
        ("30 x 20 x 10 furlongs", "unknown unit"),
    ],
)
def test_parse_dimensions_refusals(raw, fragment):
    with pytest.raises(Unreadable) as exc:
        parse.parse_dimensions(raw)
    assert fragment in str(exc.value)


# ---------------------------------------------------------------------- barcodes


def test_a_generated_ean13_validates():
    assert parse.parse_barcode("5060000007916") == "5060000007916"


def test_check_digit_is_reported_with_the_right_answer():
    with pytest.raises(Unreadable) as exc:
        parse.parse_barcode("5060123456780")
    assert "should be 3" in str(exc.value)


def test_spreadsheet_mangled_barcode_is_not_reconstructed():
    """Excel turned the GTIN into a float. Those digits are gone for good."""
    with pytest.raises(Unreadable) as exc:
        parse.parse_barcode("5.06E+12")
    assert "digits lost" in str(exc.value)


def test_eleven_digits_is_not_silently_zero_padded():
    """A lost leading zero is plausible. Plausible is not the same as known."""
    with pytest.raises(Unreadable) as exc:
        parse.parse_barcode("06012345678")
    assert "11 digits" in str(exc.value)


@pytest.mark.parametrize("raw", ["", "-", "0", "n/a"])
def test_absent_barcode_is_none(raw):
    assert parse.parse_barcode(raw) is None


def test_hyphens_and_spaces_are_removed_before_checking():
    assert parse.parse_barcode("506-0000 007916") == "5060000007916"


# --------------------------------------------------------------------------- url


def test_protocol_relative_url_is_fixed():
    assert parse.parse_url("//cdn.example.test/a.jpg") == "https://cdn.example.test/a.jpg"


def test_relative_path_without_a_base_is_unreadable():
    with pytest.raises(Unreadable) as exc:
        parse.parse_url("images/a.jpg")
    assert "--image-base" in str(exc.value)


def test_relative_path_with_a_base_resolves():
    assert parse.parse_url("images/a.jpg", "https://cdn.test/") == "https://cdn.test/images/a.jpg"


def test_non_http_scheme_is_refused():
    with pytest.raises(Unreadable):
        parse.parse_url("ftp://cdn.test/a.jpg")


# -------------------------------------------------------------------- title case

ACRONYMS = {"usb-c": "USB-C", "led": "LED", "uv": "UV"}
MINOR = {"and", "of", "the", "for", "with"}


@pytest.mark.parametrize(
    "raw, want",
    [
        ("BRASS LANTERN", "Brass Lantern"),
        ("stiff bristle deck brush", "Stiff Bristle Deck Brush"),
        ("BRAIDED 9M DOCK LINE", "Braided 9m Dock Line"),
        ("usb-c rechargeable head torch", "USB-C Rechargeable Head Torch"),
        ("RULED A5 NOTEBOOK", "Ruled A5 Notebook"),
        ("BOWL AND JUG SET", "Bowl and Jug Set"),
        ("THE LEDGER", "The Ledger"),
    ],
)
def test_title_case(raw, want):
    assert parse.title_case(raw, ACRONYMS, MINOR) == want


@pytest.mark.parametrize(
    "left, right",
    [
        ("Harbourline Outfitters", "  harbourline   OUTFITTERS "),
        ("KESTREL & CO.", "Kestrel Co"),
        ("Marrow Tool Works Ltd", "marrow tool works ltd"),
    ],
)
def test_fold_collapses_case_spacing_and_punctuation(left, right):
    assert parse.fold(left) == parse.fold(right)


def test_fold_does_not_equate_ampersand_with_the_word_and():
    """Deliberate. `&` and `and` are different strings and only the client
    knows they mean the same company, so it goes in the profile's alias list
    explicitly rather than being inferred here."""
    assert parse.fold("Kestrel & Co") != parse.fold("Kestrel and Co")
