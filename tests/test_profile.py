"""Profiles fail at load time, with a message that says what to fix.

The failure mode this guards against is a typo in a column alias producing a
silently empty column, discovered three weeks later when somebody notices the
whole feed has no barcodes.
"""

from __future__ import annotations

import json

import pytest

from feed_clean.profile import ProfileError, build_profile, load_profile

MINIMAL = {"columns": {"sku": ["Variant SKU"]}}


def test_the_bundled_profile_loads(profile):
    assert profile.currency == "USD"
    assert profile.canonical_field("Variant SKU") == "sku"
    assert profile.canonical_field("variant  sku") == "sku"  # folded, so spacing is forgiven
    assert profile.canonical_field("Supplier Ref") is None


def test_load_reports_a_missing_file():
    with pytest.raises(ProfileError) as exc:
        load_profile("nope.json")
    assert "nope.json" in str(exc.value)


def test_load_reports_bad_json(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{nope}", encoding="utf-8")
    with pytest.raises(ProfileError) as exc:
        load_profile(path)
    assert "not valid JSON" in str(exc.value)


def test_an_unknown_field_name_lists_the_real_ones():
    source = {"columns": {"sku": ["SKU"], "prcie": ["Price"]}}
    with pytest.raises(ProfileError) as exc:
        build_profile(source)
    assert "prcie" in str(exc.value)
    assert "price" in str(exc.value)  # the list of what it could have been


def test_an_alias_claimed_twice_is_an_error_not_last_one_wins():
    """Silently letting the last one win makes the result depend on JSON key
    order, which is the least discoverable bug in the file."""
    source = {"columns": {"sku": ["Item"], "barcode": ["Item"]}}
    with pytest.raises(ProfileError) as exc:
        build_profile(source)
    assert "claimed by both" in str(exc.value)


def test_a_profile_with_no_sku_mapping_is_useless_and_says_so():
    with pytest.raises(ProfileError) as exc:
        build_profile({"columns": {"title": ["Title"]}})
    assert "sku" in str(exc.value)


def test_unknown_top_level_key():
    with pytest.raises(ProfileError) as exc:
        build_profile({**MINIMAL, "colunms": {}})
    assert "colunms" in str(exc.value)


def test_unknown_stock_state():
    source = {**MINIMAL, "stock_status": {"in_stok": ["in stock"]}}
    with pytest.raises(ProfileError) as exc:
        build_profile(source)
    assert "in_stok" in str(exc.value)


def test_required_lists_a_field_that_does_not_exist():
    with pytest.raises(ProfileError) as exc:
        build_profile({**MINIMAL, "required": ["sku", "colour"]})
    assert "colour" in str(exc.value)


def test_unknown_limit_name():
    with pytest.raises(ProfileError) as exc:
        build_profile({**MINIMAL, "limits": {"desc_max": 10}})
    assert "desc_max" in str(exc.value)


def test_currency_must_be_a_code():
    with pytest.raises(ProfileError) as exc:
        build_profile({**MINIMAL, "currency": "dollars"})
    assert "three-letter" in str(exc.value)


def test_vendor_aliases_invert_to_the_canonical_spelling(profile):
    assert profile.vendors["harbourline"] == "Harbourline Outfitters"
    assert profile.vendors["kestrel co"] == "Kestrel & Co."


def test_the_canonical_name_is_its_own_alias():
    source = {**MINIMAL, "vendors": {"Acme Supply Co.": []}}
    built = build_profile(source)
    assert built.vendors["acme supply co"] == "Acme Supply Co."


def test_the_bundled_profile_is_valid_json_on_disk(repo):
    json.loads((repo / "profiles" / "supplier.json").read_text(encoding="utf-8"))
