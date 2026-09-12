"""The reject and review rules, and the line between them."""

from __future__ import annotations

import io

from feed_clean.models import REJECT, REVIEW
from feed_clean.normalize import normalize, read_feed
from feed_clean.validate import validate

FULL = "Variant SKU,Title,Variant Price,Cost per item,Compare At Price,Variant Barcode,Image Src,Body (HTML),Variant Inventory Qty,Stock Status"
GOOD = 'A-1,Brass Lantern,24.00,9.00,,5060000007916,https://x.test/a.jpg,Nice,12,In Stock'


def check(profile, values: str, header: str = FULL):
    rows, _, _ = read_feed(io.StringIO(f"{header}\n{values}\n"), profile)
    row = rows[0]
    normalize(row, profile)
    validate(row, profile)
    return row


def test_a_good_row_is_neither_rejected_nor_flagged(profile):
    row = check(profile, GOOD)
    assert not row.rejected
    assert not row.needs_review


# ------------------------------------------------------------------- rejects


def test_missing_sku(profile):
    row = check(profile, GOOD.replace("A-1,", ",", 1))
    assert "missing_sku" in row.rules(REJECT)


def test_missing_title(profile):
    row = check(profile, GOOD.replace("Brass Lantern", ""))
    assert "missing_title" in row.rules(REJECT)


def test_zero_price(profile):
    row = check(profile, GOOD.replace(",24.00,9.00,", ",0.00,,"))
    assert "price_not_positive" in row.rules(REJECT)


def test_negative_price(profile):
    row = check(profile, GOOD.replace(",24.00,9.00,", ",-12.00,,"))
    assert "price_not_positive" in row.rules(REJECT)


def test_price_below_cost_says_how_much_it_loses(profile):
    row = check(profile, GOOD.replace(",24.00,9.00,", ",8.00,11.50,"))
    assert "price_below_cost" in row.rules(REJECT)
    assert "3.50" in row.issue_text()


def test_missing_image(profile):
    row = check(profile, GOOD.replace("https://x.test/a.jpg", ""))
    assert "missing_image_url" in row.rules(REJECT)


def test_a_relative_image_path_is_rejected_with_the_fix_in_the_message(profile):
    row = check(profile, GOOD.replace("https://x.test/a.jpg", "images/a.jpg"))
    assert "image_unusable" in row.rules(REJECT)
    assert "--image-base" in row.issue_text()


def test_description_over_the_cap(profile):
    row = check(profile, GOOD.replace(",Nice,", "," + "word " * 1200 + ","))
    assert "description_too_long" in row.rules(REJECT)


def test_the_cap_applies_to_visible_text_not_markup(profile):
    """5000 characters of `<span>` is not 5000 characters of description."""
    body = "<span class='x'>" * 400 + "Short copy" + "</span>" * 400
    row = check(profile, GOOD.replace(",Nice,", f',"{body}",'))
    assert "description_too_long" not in row.rules(REJECT)


def test_bad_barcode_checksum(profile):
    row = check(profile, GOOD.replace("5060000007916", "5060123456780"))
    assert "barcode_invalid" in row.rules(REJECT)


def test_an_empty_barcode_is_not_an_invalid_one(profile):
    row = check(profile, GOOD.replace("5060000007916", ""))
    assert "barcode_invalid" not in row.rules(REJECT)


def test_an_unreadable_required_field_is_rejected_once_with_the_better_message(profile):
    """Not "missing_price" stacked on top of the sentence that says what the
    cell actually contained — one empty price, one reason."""
    row = check(profile, GOOD.replace(",24.00,", ",Call for quote,"))
    rules = row.rules(REJECT)
    assert rules == ["price.format"]
    assert "Call for quote" in row.issue_text()


def test_an_absent_required_field_is_rejected_as_missing(profile):
    row = check(profile, GOOD.replace(",24.00,", ",,"))
    assert row.rules(REJECT) == ["missing_price"]


# -------------------------------------------------------------------- reviews


def test_an_unreadable_weight_is_a_review_not_a_rejection(profile):
    """Weight is not a required field, so an unresolvable one is a note."""
    header = FULL + ",Weight,Weight Unit"
    row = check(profile, GOOD + ",1.2,", header)
    assert not row.rejected
    assert "weight.unit" in row.rules(REVIEW)


def test_fake_discount(profile):
    row = check(profile, GOOD.replace(",24.00,9.00,,", ",24.00,9.00,19.99,"))
    assert "compare_at_not_above_price" in row.rules(REVIEW)
    assert not row.rejected


def test_in_stock_with_nothing_on_hand(profile):
    row = check(profile, GOOD.replace(",12,In Stock", ",0,In Stock"))
    assert "stock_inconsistent" in row.rules(REVIEW)


def test_out_of_stock_with_units_on_hand(profile):
    row = check(profile, GOOD.replace(",12,In Stock", ",9,Out of stock"))
    assert "stock_inconsistent" in row.rules(REVIEW)


def test_backorder_with_no_units_is_not_inconsistent(profile):
    row = check(profile, GOOD.replace(",12,In Stock", ",0,Back-Order"))
    assert "stock_inconsistent" not in row.rules(REVIEW)


def test_an_unreadable_quantity_does_not_produce_a_phantom_inconsistency(profile):
    row = check(profile, GOOD.replace(",12,In Stock", ",lots,In Stock"))
    assert "quantity.format" in row.rules(REVIEW)
    assert "stock_inconsistent" not in row.rules(REVIEW)


def test_title_over_the_cap_is_a_review_not_a_rejection(profile):
    row = check(profile, GOOD.replace("Brass Lantern", "Lantern " * 30))
    assert "title_too_long" in row.rules(REVIEW)
    assert not row.rejected
