#!/usr/bin/env python3
"""Write the synthetic supplier feed, and the ground truth for it, together.

Everything in here is invented: six vendors that do not exist, selling products
that do not exist, with barcodes computed from made-up numbers. No real
supplier, client, product or feed is anywhere in this repository.

The important structural point is that `fixtures/supplier-feed.csv` and
`tests/expected.json` come out of the *same* function call. The dirty cell and
the value it is supposed to clean up to are written next to each other, so the
end-to-end tests assert against what the fixture means rather than against what
the tool happened to produce the first time it ran. That is what catches a
parser bug instead of enshrining it.

    python fixtures/generate_feed.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "fixtures" / "supplier-feed.csv"
TRUTH = ROOT / "tests" / "expected.json"

# The supplier's own headers, in the supplier's own order, including one this
# tool has no mapping for.
HEADERS = [
    "Handle",
    "Variant SKU",
    "Title",
    "Vendor",
    "Product Type",
    "Variant Price",
    "Cost per item",
    "Compare At Price",
    "Variant Barcode",
    "Weight",
    "Weight Unit",
    "Dimensions",
    "Variant Inventory Qty",
    "Stock Status",
    "Published",
    "Variant Taxable",
    "Image Src",
    "Body (HTML)",
    "Tags",
    "Updated At",
    "Supplier Ref",
]

UNMAPPED_HEADERS = ["Supplier Ref"]

# Vendor: (canonical name, the spellings the supplier actually uses)
VENDORS = [
    ("Harbourline Outfitters", ["HARBOURLINE OUTFITTERS", "Harbourline", "harbourline outfitters inc"]),
    ("Kestrel & Co.", ["kestrel and co", "KESTREL & CO.", "Kestrel Co"]),
    ("Marrow Tool Works", ["marrow tools", "MARROW TOOLWORKS", "Marrow Tool Works Ltd"]),
    ("Pennyroyal Home", ["pennyroyal", "PENNYROYAL HOME GOODS", "Pennyroyal Home"]),
    ("Saltmarsh Supply", ["SALTMARSH", "salt marsh supply", "Saltmarsh Supply Co"]),
    ("Vellum Paper Goods", ["vellum paper", "VELLUM PAPERGOODS", "Vellum"]),
]

TYPES = [
    "Outdoor",
    "Hand Tools",
    "Kitchen",
    "Stationery",
    "Marine",
    "Storage",
    "Lighting",
    "Workshop",
]

# (noun, qualifier) pairs. Deliberately ordinary, deliberately invented.
NOUNS = [
    "Lantern", "Dry Bag", "Chisel", "Mixing Bowl", "Notebook", "Deck Brush",
    "Rope Ladder", "Tote", "Hand Plane", "Tea Caddy", "Ledger", "Fender",
    "Mallet", "Colander", "Sketchbook", "Bilge Pump", "Tool Roll", "Crate",
    "Head Torch", "Bench Hook", "Butter Dish", "Index Cards", "Cleat", "Bin",
]
QUALIFIERS = [
    "Brass", "Waxed Canvas", "Oak Handled", "Enamelled", "Ruled A5",
    "Stiff Bristle", "Braided 9m", "Heavyweight", "Bevel Edge", "Airtight",
    "Cloth Bound", "Cylindrical", "Rubber Faced", "Perforated", "Hardback",
    "Manual 12v", "Four Pocket", "Stackable", "USB-C Rechargeable",
    "Beech", "Stoneware", "Gridded", "Stainless", "Lidded",
]

DESCRIPTIONS = [
    "<p>Made in small batches and finished by hand. Ships flat.</p>",
    "<p>Hard-wearing &amp; simple to clean. Sold singly.</p>",
    "<p>Designed for daily use.<br>Guaranteed for two years.</p>",
    "<p>A workshop staple &mdash; nothing clever, just well made.</p>",
]


def ean13(seed: int) -> str:
    """A valid EAN-13 from an invented 12-digit body."""
    body = f"{5060000000000 + seed * 7919:013d}"[:12]
    return body + str(check_digit(body))


def check_digit(digits: str) -> int:
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(digits)))
    return (10 - total % 10) % 10


def money(value: float) -> str:
    return f"{value:.2f}"


class Feed:
    """Collects rows and, for each, what the cleaner is expected to make of it."""

    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        self.clean_skus: list[str] = []
        self.rejects: dict[str, dict] = {}
        self.flags: dict[str, dict] = {}
        self.dedupe: dict[str, dict] = {}
        self.spot: list[dict] = []

    @property
    def line(self) -> int:
        """The line number the next row will land on. Line 1 is the header."""
        return len(self.rows) + 2

    def add(self, row: dict, *, clean_sku: str | None = None) -> int:
        line = self.line
        self.rows.append({header: str(row.get(header, "")) for header in HEADERS})
        if clean_sku:
            self.clean_skus.append(clean_sku)
        return line

    def reject(self, line: int, sku: str, rules: list[str]) -> None:
        self.rejects[str(line)] = {"sku": sku, "rules": sorted(rules)}

    def flag(self, line: int, sku: str, rules: list[str]) -> None:
        self.flags[str(line)] = {"sku": sku, "rules": sorted(rules)}

    def expect(self, sku: str, field: str, value: str) -> None:
        self.spot.append({"sku": sku, "field": field, "value": value})


def base_row(**overrides) -> dict:
    """A complete, valid-but-differently-spelled row. Overrides make it dirty."""
    row = {
        "Handle": "",
        "Variant SKU": "",
        "Title": "",
        "Vendor": "",
        "Product Type": "Outdoor",
        "Variant Price": "24.00",
        "Cost per item": "9.00",
        "Compare At Price": "",
        "Variant Barcode": "",
        "Weight": "500",
        "Weight Unit": "g",
        "Dimensions": "200mm x 120mm x 60mm",
        "Variant Inventory Qty": "12",
        "Stock Status": "In Stock",
        "Published": "TRUE",
        "Variant Taxable": "TRUE",
        "Image Src": "https://cdn.example-supplier.test/img/placeholder.jpg",
        "Body (HTML)": DESCRIPTIONS[0],
        "Tags": "core",
        "Updated At": "2026-09-08T04:15:00Z",
        "Supplier Ref": "NW/000",
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------- bulk rows

# Each style is (how the supplier writes it, what it should clean up to).
PRICE_STYLES = [
    ("$1,299.00", "1299.00"),
    ("49.99", "49.99"),
    ("  18,50  ", "18.50"),
    ("USD 45.50", "45.50"),
    ("$7.25", "7.25"),
    ("1.299,00", "1299.00"),
]
WEIGHT_STYLES = [
    ("2.5", "kg", "2500"),
    ("500 g", "", "500"),
    ("1.1lb", "", "499"),
    ("12 oz", "", "340.2"),
    ("0,75 kg", "", "750"),
    ("340", "g", "340"),
]
DIM_STYLES = [
    ("12 x 8 x 4 in", ("304.8", "203.2", "101.6")),
    ("300mm x 200mm x 100mm", ("300", "200", "100")),
    ("30 × 20 × 10 cm", ("300", "200", "100")),
    ("1.2 x 0.4 x 0.4 m", ("1200", "400", "400")),
]
STOCK_STYLES = [
    ("In Stock", "in_stock", 14),
    ("instock", "in_stock", 3),
    ("OUT OF STOCK", "out_of_stock", 0),
    ("Back-Order", "backorder", 0),
    ("Pre-Order", "preorder", 0),
    ("Discontinued", "discontinued", 0),
]
BOOL_STYLES = [("TRUE", "true"), ("yes", "true"), ("1", "true"), ("N", "false"), ("false", "false")]
TITLE_STYLES = ["upper", "lower", "mixed"]


def bulk(feed: Feed, count: int) -> None:
    for index in range(count):
        sku = f"NW-{1000 + index * 3}"
        canonical_vendor, spellings = VENDORS[index % len(VENDORS)]
        noun = NOUNS[index % len(NOUNS)]
        qualifier = QUALIFIERS[(index * 5) % len(QUALIFIERS)]
        clean_title = f"{qualifier} {noun}"

        style = TITLE_STYLES[index % 3]
        if style == "upper":
            title_text = clean_title.upper()
        elif style == "lower":
            title_text = clean_title.lower()
        else:
            title_text = clean_title

        price_text, price_clean = PRICE_STYLES[index % len(PRICE_STYLES)]
        weight_text, weight_unit, weight_clean = WEIGHT_STYLES[index % len(WEIGHT_STYLES)]
        dim_text, dim_clean = DIM_STYLES[index % len(DIM_STYLES)]
        stock_text, stock_clean, qty = STOCK_STYLES[index % len(STOCK_STYLES)]
        published_text, published_clean = BOOL_STYLES[index % len(BOOL_STYLES)]

        cost = float(price_clean) * 0.4
        compare_at = "" if index % 4 else money(float(price_clean) * 1.3)

        feed.add(
            base_row(
                Handle=f"{noun.lower().replace(' ', '-')}-{sku.lower()}",
                **{"Variant SKU": sku},
                Title=title_text,
                Vendor=spellings[index % len(spellings)],
                **{"Product Type": TYPES[index % len(TYPES)]},
                **{"Variant Price": price_text},
                **{"Cost per item": money(cost)},
                **{"Compare At Price": compare_at},
                **{"Variant Barcode": ean13(index + 1)},
                Weight=weight_text,
                **{"Weight Unit": weight_unit},
                Dimensions=dim_text,
                **{"Variant Inventory Qty": str(qty)},
                **{"Stock Status": stock_text},
                Published=published_text,
                **{"Variant Taxable": BOOL_STYLES[(index + 1) % len(BOOL_STYLES)][0]},
                **{
                    "Image Src": (
                        f"//cdn.example-supplier.test/img/{sku.lower()}.jpg"
                        if index % 5 == 0
                        else f"https://cdn.example-supplier.test/img/{sku.lower()}.jpg"
                    )
                },
                **{"Body (HTML)": DESCRIPTIONS[index % len(DESCRIPTIONS)]},
                Tags=f"{TYPES[index % len(TYPES)].lower()}, catalogue",
                **{"Updated At": f"2026-09-0{1 + index % 8}T0{index % 9}:30:00Z"},
                **{"Supplier Ref": f"NW/{index:04d}"},
            ),
            clean_sku=sku,
        )

        # Spot-check a spread of them rather than all: enough to prove every
        # style of dirt in the rotation, few enough to read in the JSON.
        if index < 12:
            feed.expect(sku, "title", clean_title)
            feed.expect(sku, "vendor", canonical_vendor)
            feed.expect(sku, "price", price_clean)
            feed.expect(sku, "weight_g", weight_clean)
            feed.expect(sku, "length_mm", dim_clean[0])
            feed.expect(sku, "stock_status", stock_clean)
            feed.expect(sku, "published", published_clean)
            feed.expect(sku, "image_url", f"https://cdn.example-supplier.test/img/{sku.lower()}.jpg")


# ------------------------------------------------------------- duplicate groups


def duplicates(feed: Feed) -> None:
    # 1. Two rows, one stale. The newer one is the supplier's latest answer.
    old = feed.add(
        base_row(
            **{"Variant SKU": "NW-D001", "Variant Price": "$42.00", "Updated At": "2026-08-30T09:00:00Z"},
            Title="COPPER JUG",
            Vendor="Pennyroyal",
            **{"Variant Barcode": ean13(901)},
        )
    )
    new = feed.add(
        base_row(
            **{"Variant SKU": "NW-D001", "Variant Price": "$38.50", "Updated At": "2026-09-07T09:00:00Z"},
            Title="COPPER JUG",
            Vendor="Pennyroyal",
            **{"Variant Barcode": ean13(901)},
        ),
        clean_sku="NW-D001",
    )
    feed.dedupe["NW-D001"] = {
        "winner_line": new,
        "reason": "newest updated_at",
        "dropped_lines": [old],
    }
    feed.expect("NW-D001", "price", "38.50")

    # 2. The same row twice. Nothing to decide.
    first = feed.add(
        base_row(
            **{"Variant SKU": "NW-D002", "Variant Barcode": ean13(902)},
            Title="Beeswax Wrap Set",
            Vendor="Pennyroyal Home",
        ),
        clean_sku="NW-D002",
    )
    same = feed.add(
        base_row(
            **{"Variant SKU": "NW-D002", "Variant Barcode": ean13(902)},
            Title="Beeswax Wrap Set",
            Vendor="Pennyroyal Home",
        )
    )
    feed.dedupe["NW-D002"] = {
        "winner_line": first,
        "reason": "identical",
        "dropped_lines": [same],
    }

    # 3. No timestamps at all: the most complete row wins.
    thin = feed.add(
        base_row(
            **{
                "Variant SKU": "NW-D003",
                "Variant Price": "",
                "Variant Barcode": "",
                "Updated At": "",
                "Image Src": "",
            },
            Title="Rope Doormat",
            Vendor="saltmarsh",
        )
    )
    full = feed.add(
        base_row(
            **{"Variant SKU": "NW-D003", "Variant Price": "$31.00", "Variant Barcode": ean13(903), "Updated At": ""},
            Title="Rope Doormat",
            Vendor="saltmarsh",
        ),
        clean_sku="NW-D003",
    )
    feed.dedupe["NW-D003"] = {
        "winner_line": full,
        "reason": "more complete",
        "dropped_lines": [thin],
    }

    # 4. THE UNFIXABLE ONE. Same sku, same timestamp, same completeness, two
    #    different prices. There is no fact in the file that picks a winner, so
    #    the tool picks neither and says so.
    tie_a = feed.add(
        base_row(
            **{
                "Variant SKU": "NW-D004",
                "Variant Price": "$64.00",
                "Variant Barcode": ean13(904),
                "Updated At": "2026-09-05T11:00:00Z",
            },
            Title="Folding Camp Stool",
            Vendor="Harbourline",
        )
    )
    tie_b = feed.add(
        base_row(
            **{
                "Variant SKU": "NW-D004",
                "Variant Price": "$71.00",
                "Variant Barcode": ean13(904),
                "Updated At": "2026-09-05T11:00:00Z",
            },
            Title="Folding Camp Stool",
            Vendor="Harbourline",
        )
    )
    feed.dedupe["NW-D004"] = {
        "winner_line": None,
        "reason": "unresolved tie",
        "dropped_lines": [],
        "rejected_lines": [tie_a, tie_b],
    }
    feed.reject(tie_a, "NW-D004", ["duplicate_unresolved"])
    feed.reject(tie_b, "NW-D004", ["duplicate_unresolved"])

    # 5. The newest row is thinner than the one it beat, so the winner is
    #    backfilled from the loser — every fill logged with the line it
    #    came from.
    rich = feed.add(
        base_row(
            **{
                "Variant SKU": "NW-D005",
                "Variant Barcode": ean13(905),
                "Updated At": "2026-08-28T08:00:00Z",
                "Image Src": "https://cdn.example-supplier.test/img/nw-d005.jpg",
            },
            Title="Enamel Mug",
            Vendor="Pennyroyal Home",
            Tags="kitchen, enamel",
        )
    )
    thin_new = feed.add(
        base_row(
            **{
                "Variant SKU": "NW-D005",
                "Variant Price": "$16.00",
                "Variant Barcode": "",
                "Updated At": "2026-09-09T08:00:00Z",
                "Image Src": "",
            },
            Title="Enamel Mug",
            Vendor="Pennyroyal Home",
            Tags="",
        ),
        clean_sku="NW-D005",
    )
    feed.dedupe["NW-D005"] = {
        "winner_line": thin_new,
        "reason": "newest updated_at",
        "dropped_lines": [rich],
        "backfilled": ["barcode", "image_url", "tags"],
    }
    feed.expect("NW-D005", "price", "16.00")
    feed.expect("NW-D005", "barcode", ean13(905))
    feed.expect("NW-D005", "image_url", "https://cdn.example-supplier.test/img/nw-d005.jpg")

    # 6. Both rows dated 03/04/2026 — third of April or fourth of March, and
    #    the file does not say. Ambiguous dates are ignored rather than
    #    guessed, so the group falls through to the completeness rule.
    ambiguous_thin = feed.add(
        base_row(
            **{
                "Variant SKU": "NW-D006",
                "Variant Barcode": "",
                "Updated At": "03/04/2026",
                "Image Src": "",
            },
            Title="Canvas Log Carrier",
            Vendor="Saltmarsh Supply",
        )
    )
    ambiguous_full = feed.add(
        base_row(
            **{"Variant SKU": "NW-D006", "Variant Barcode": ean13(906), "Updated At": "04/03/2026"},
            Title="Canvas Log Carrier",
            Vendor="Saltmarsh Supply",
        ),
        clean_sku="NW-D006",
    )
    feed.dedupe["NW-D006"] = {
        "winner_line": ambiguous_full,
        "reason": "more complete",
        "dropped_lines": [ambiguous_thin],
    }


# --------------------------------------------------------------------- rejects


def rejects(feed: Feed) -> None:
    def add(sku: str, rules: list[str], **overrides) -> None:
        line = feed.add(base_row(**{"Variant SKU": sku}, **overrides))
        feed.reject(line, sku, rules)

    add(
        "",
        ["missing_sku"],
        Title="Unlabelled Storage Crate",
        Vendor="Saltmarsh Supply",
        **{"Variant Barcode": ean13(801)},
    )
    add(
        "NW-R001",
        ["price_not_positive"],
        Title="Zero Priced Trowel",
        Vendor="Marrow Tool Works",
        **{"Variant Price": "0.00", "Cost per item": "", "Variant Barcode": ean13(802)},
    )
    add(
        "NW-R002",
        ["price_not_positive"],
        Title="Negative Priced Shelf",
        Vendor="Marrow Tool Works",
        **{"Variant Price": "-12.00", "Cost per item": "", "Variant Barcode": ean13(803)},
    )
    add(
        "NW-R003",
        ["price_below_cost"],
        Title="Loss Making Kettle",
        Vendor="Pennyroyal Home",
        **{"Variant Price": "8.00", "Cost per item": "11.50", "Variant Barcode": ean13(804)},
    )
    add(
        "NW-R004",
        ["missing_image_url"],
        Title="Imageless Dry Bag",
        Vendor="Harbourline Outfitters",
        **{"Image Src": "", "Variant Barcode": ean13(805)},
    )
    add(
        "NW-R005",
        ["image_unusable"],
        Title="Relative Path Lantern",
        Vendor="Harbourline Outfitters",
        **{"Image Src": "images/lantern.jpg", "Variant Barcode": ean13(806)},
    )
    add(
        "NW-R006",
        ["description_too_long"],
        Title="Overlong Copy Notebook",
        Vendor="Vellum Paper Goods",
        **{
            "Body (HTML)": "<p>" + ("A durable notebook for everyday notes. " * 140) + "</p>",
            "Variant Barcode": ean13(807),
        },
    )
    add(
        "NW-R007",
        ["barcode_invalid"],
        Title="Bad Check Digit Chisel",
        Vendor="Marrow Tool Works",
        **{"Variant Barcode": "5060123456780"},
    )
    add(
        "NW-R008",
        ["barcode_invalid"],
        Title="Spreadsheet Mangled Mallet",
        Vendor="Marrow Tool Works",
        **{"Variant Barcode": "5.06E+12"},
    )
    add(
        "NW-R009",
        ["barcode_invalid"],
        Title="Lost Leading Zero Bowl",
        Vendor="Pennyroyal Home",
        **{"Variant Barcode": "06012345678"},
    )
    add(
        "NW-R010",
        ["missing_title"],
        Title="",
        Vendor="Vellum Paper Goods",
        **{"Variant Barcode": ean13(808)},
    )
    add(
        "NW-R011",
        ["price.format"],
        Title="Quote Only Bench",
        Vendor="Marrow Tool Works",
        **{"Variant Price": "Call for quote", "Variant Barcode": ean13(809)},
    )
    add(
        "NW-R012",
        ["price.format"],
        Title="Was Now Priced Tote",
        Vendor="Harbourline Outfitters",
        **{"Variant Price": "$60.00 $48.00", "Variant Barcode": ean13(810)},
    )


# ------------------------------------------------------------------ flagged rows


def flagged(feed: Feed) -> None:
    def add(sku: str, rules: list[str], **overrides) -> int:
        line = feed.add(base_row(**{"Variant SKU": sku}, **overrides), clean_sku=sku)
        feed.flag(line, sku, rules)
        return line

    add(
        "NW-F001",
        ["weight.unit"],
        Title="Unitless Weight Hand Plane",
        Vendor="Marrow Tool Works",
        Weight="1.2",
        **{"Weight Unit": "", "Variant Barcode": ean13(701)},
    )
    add(
        "NW-F002",
        ["weight.unit"],
        Title="Odd Unit Anchor Weight",
        Vendor="Harbourline Outfitters",
        Weight="3 stone",
        **{"Weight Unit": "", "Variant Barcode": ean13(702)},
    )
    add(
        "NW-F003",
        ["dimensions.unit"],
        Title="Two Dimension Doormat",
        Vendor="Saltmarsh Supply",
        Dimensions="12 x 8",
        **{"Variant Barcode": ean13(703)},
    )
    add(
        "NW-F004",
        ["dimensions.unit"],
        Title="Mixed Unit Crate",
        Vendor="Saltmarsh Supply",
        Dimensions="30cm x 20in x 10cm",
        **{"Variant Barcode": ean13(704)},
    )
    add(
        "NW-F005",
        ["stock_status.vocabulary"],
        Title="Unknown Stock State Ledger",
        Vendor="Vellum Paper Goods",
        **{"Stock Status": "Ask in store", "Variant Barcode": ean13(705)},
    )
    add(
        "NW-F006",
        ["published.vocabulary"],
        Title="Maybe Published Sketchbook",
        Vendor="Vellum Paper Goods",
        Published="maybe",
        **{"Variant Barcode": ean13(706)},
    )
    add(
        "NW-F007",
        ["price.currency_mismatch"],
        Title="Euro Priced Deck Brush",
        Vendor="Harbourline Outfitters",
        **{"Variant Price": "€89,00", "Variant Barcode": ean13(707)},
    )
    feed.expect("NW-F007", "price", "89.00")
    feed.expect("NW-F007", "currency", "EUR")

    add(
        "NW-F008",
        ["stock_inconsistent"],
        Title="In Stock With None Left Cleat",
        Vendor="Harbourline Outfitters",
        **{"Variant Inventory Qty": "0", "Stock Status": "In Stock", "Variant Barcode": ean13(708)},
    )
    add(
        "NW-F009",
        ["quantity.format"],
        Title="Unreadable Quantity Bin",
        Vendor="Saltmarsh Supply",
        **{"Variant Inventory Qty": "lots", "Variant Barcode": ean13(709)},
    )
    add(
        "NW-F010",
        ["compare_at_not_above_price"],
        Title="Fake Discount Tea Caddy",
        Vendor="Pennyroyal Home",
        **{"Variant Price": "24.00", "Compare At Price": "19.99", "Variant Barcode": ean13(710)},
    )
    add(
        "NW-F011",
        ["title_too_long"],
        Title="Extremely Long Title " + ("For A Perfectly Ordinary Shelf Bracket " * 4),
        Vendor="Marrow Tool Works",
        **{"Variant Barcode": ean13(711)},
    )

    # Two vendors nobody has mapped yet. Not an error and not flagged per row:
    # case-normalised, carried through, and counted in the summary so somebody
    # decides whether they are new suppliers or typos.
    for index, (sku, vendor) in enumerate(
        [("NW-V001", "tidepool goods"), ("NW-V002", "ZEPHYR WORKS")]
    ):
        feed.add(
            base_row(
                **{"Variant SKU": sku, "Variant Barcode": ean13(720 + index)},
                Title=f"Unmapped Vendor Item {index + 1}",
                Vendor=vendor,
            ),
            clean_sku=sku,
        )


def main() -> None:
    feed = Feed()
    bulk(feed, 280)
    duplicates(feed)
    rejects(feed)
    flagged(feed)

    FEED.parent.mkdir(parents=True, exist_ok=True)
    with FEED.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(feed.rows)

    truth = {
        "rows_in": len(feed.rows),
        "clean_skus": feed.clean_skus,
        "rejects": feed.rejects,
        "flags": feed.flags,
        "dedupe": feed.dedupe,
        "spot": feed.spot,
        "unmapped_headers": UNMAPPED_HEADERS,
        "unmapped_vendors": ["Tidepool Goods", "Zephyr Works"],
    }
    TRUTH.parent.mkdir(parents=True, exist_ok=True)
    TRUTH.write_text(json.dumps(truth, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print(f"wrote {FEED.relative_to(ROOT)} ({len(feed.rows)} rows)")
    print(f"wrote {TRUTH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
