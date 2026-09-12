"""Normalisation at the row level: what got written, and what got logged.

The contract these tests exist to hold is that every edit leaves a Change and
every refusal leaves both a Change and an Issue. A rule that fixes a value
without logging it is the same as a rule that corrupts one, from the point of
view of the person who has to explain the feed to a supplier.
"""

from __future__ import annotations

import io

from feed_clean.models import CHANGED, REVIEW, UNRESOLVED
from feed_clean.normalize import normalize, read_feed


def one_row(profile, header: str, values: str):
    rows, mapped, unmapped = read_feed(io.StringIO(f"{header}\n{values}\n"), profile)
    normalize(rows[0], profile)
    return rows[0], mapped, unmapped


def changes_for(row, field):
    return [c for c in row.changes if c.field == field]


# ------------------------------------------------------------- header mapping


def test_supplier_headers_map_onto_canonical_fields(profile):
    row, mapped, unmapped = one_row(profile, "Variant SKU,Variant Price", "A-1,10.00")
    assert row.get("sku") == "A-1"
    assert "price" in mapped
    assert unmapped == []


def test_an_unmapped_column_is_carried_through_not_dropped(profile):
    row, _, unmapped = one_row(profile, "Variant SKU,Warehouse Bay", "A-1,B12")
    assert unmapped == ["Warehouse Bay"]
    assert row.extra["Warehouse Bay"] == "B12"


def test_line_numbers_match_the_spreadsheet(profile):
    rows, _, _ = read_feed(io.StringIO("Variant SKU\nA-1\nA-2\n"), profile)
    assert [row.line for row in rows] == [2, 3]


# ------------------------------------------------------------------- casing


def test_an_all_caps_title_is_recased_and_logged(profile):
    row, _, _ = one_row(profile, "Variant SKU,Title", "A-1,BRASS LANTERN")
    assert row.get("title") == "Brass Lantern"
    assert changes_for(row, "title")[0].rule == "title.case"


def test_a_deliberately_cased_title_is_left_alone(profile):
    """"pH Test Strips" is not a casing mistake and must not be treated as one."""
    row, _, _ = one_row(profile, "Variant SKU,Title", "A-1,pH Test Strips")
    assert row.get("title") == "pH Test Strips"
    assert not [c for c in row.changes if c.rule == "title.case"]


def test_html_and_entities_leave_the_description(profile):
    row, _, _ = one_row(
        profile, "Variant SKU,Body (HTML)", "A-1,<p>Hard-wearing &amp; simple</p>"
    )
    assert row.get("description") == "Hard-wearing & simple"


# ------------------------------------------------------------------- vendors


def test_a_vendor_alias_becomes_the_canonical_spelling(profile):
    row, _, _ = one_row(profile, "Variant SKU,Vendor", "A-1,marrow tools")
    assert row.get("vendor") == "Marrow Tool Works"
    assert changes_for(row, "vendor")[0].rule == "vendor.canonical"


def test_an_unmapped_vendor_is_tidied_and_noted_but_not_invented(profile):
    """"Harbourline" and "Harbourline Outfitters" might be one company or two,
    and only the client knows, so nothing is inferred."""
    row, _, _ = one_row(profile, "Variant SKU,Vendor", "A-1,tidepool goods")
    assert row.get("vendor") == "Tidepool Goods"
    assert row.values.get("vendor_unmapped") is True
    assert not row.needs_review  # a note in the summary, not a per-row flag


# -------------------------------------------------------------------- money


def test_price_is_reformatted_and_the_currency_recorded(profile):
    row, _, _ = one_row(profile, "Variant SKU,Variant Price", 'A-1,"$1,299.00"')
    assert row.get("price") == "1299.00"
    assert row.get("currency") == "USD"


def test_a_foreign_currency_is_flagged_and_never_converted(profile):
    """An exchange rate this tool invented would be wrong by upload time."""
    row, _, _ = one_row(profile, "Variant SKU,Variant Price", "A-1,€89,00")
    assert row.get("price") == "89.00"
    assert row.get("currency") == "EUR"
    assert "price.currency_mismatch" in row.rules(REVIEW)


def test_an_unreadable_price_leaves_the_cell_empty_and_keeps_the_original(profile):
    row, _, _ = one_row(profile, "Variant SKU,Variant Price", "A-1,Call for quote")
    assert row.get("price") == ""
    change = changes_for(row, "price")[0]
    assert change.outcome == UNRESOLVED
    assert change.before == "Call for quote"
    assert change.after == ""


# ------------------------------------------------------- weights and dimensions


def test_weight_converts_to_grams_using_the_unit_column(profile):
    row, _, _ = one_row(profile, "Variant SKU,Weight,Weight Unit", "A-1,2.5,kg")
    assert row.get("weight_g") == "2500"


def test_a_unitless_weight_is_flagged_and_left_empty(profile):
    row, _, _ = one_row(profile, "Variant SKU,Weight,Weight Unit", "A-1,1.2,")
    assert row.get("weight_g") == ""
    assert "weight.unit" in row.rules(REVIEW)
    assert "1.2" in row.issue_text()


def test_dimensions_split_into_three_millimetre_columns(profile):
    row, _, _ = one_row(profile, "Variant SKU,Dimensions", "A-1,12 x 8 x 4 in")
    assert (row.get("length_mm"), row.get("width_mm"), row.get("height_mm")) == (
        "304.8",
        "203.2",
        "101.6",
    )


def test_unreadable_dimensions_clear_all_three_columns(profile):
    row, _, _ = one_row(profile, "Variant SKU,Dimensions", "A-1,12 x 8")
    assert row.get("length_mm") == row.get("width_mm") == row.get("height_mm") == ""
    assert "dimensions.unit" in row.rules(REVIEW)


# --------------------------------------------------------------- vocabularies


def test_stock_states_collapse_to_one_vocabulary(profile):
    for spelling in ("In Stock", "instock", "AVAILABLE", "yes"):
        row, _, _ = one_row(profile, "Variant SKU,Stock Status", f"A-1,{spelling}")
        assert row.get("stock_status") == "in_stock"


def test_an_unknown_stock_state_is_flagged_with_advice(profile):
    row, _, _ = one_row(profile, "Variant SKU,Stock Status", "A-1,Ask in store")
    assert row.get("stock_status") == ""
    assert "stock_status.vocabulary" in row.rules(REVIEW)
    assert "profile" in row.issue_text()


def test_booleans_collapse_to_true_and_false(profile):
    for spelling, want in [("TRUE", "true"), ("yes", "true"), ("1", "true"), ("N", "false")]:
        row, _, _ = one_row(profile, "Variant SKU,Published", f"A-1,{spelling}")
        assert row.get("published") == want


def test_a_boolean_that_is_neither_is_flagged(profile):
    row, _, _ = one_row(profile, "Variant SKU,Published", "A-1,maybe")
    assert row.get("published") == ""
    assert "published.vocabulary" in row.rules(REVIEW)


# ----------------------------------------------------------------- log shape


def test_an_untouched_value_produces_no_change(profile):
    row, _, _ = one_row(profile, "Variant SKU,Title", "A-1,Brass Lantern")
    assert changes_for(row, "title") == []


def test_every_change_carries_the_line_the_sku_and_the_rule(profile):
    row, _, _ = one_row(
        profile, "Variant SKU,Title,Variant Price", 'A-1,BRASS LANTERN,"$1,299.00"'
    )
    assert row.changes
    for change in row.changes:
        assert change.line == 2
        assert change.sku == "A-1"
        assert change.rule
        assert change.outcome in (CHANGED, UNRESOLVED)
