"""The feed profile: which supplier header means what, and what the vocabulary is.

Every supplier names their columns differently and spells their own company
name three ways, so that knowledge is data, not code. Pointing this tool at a
different supplier is a JSON file, not a patch.

The profile is validated at *load* time, hard, with messages that name the
thing you got wrong and list the things you could have written instead. A typo
in a column alias should fail before the first row is read, not turn into a
silently empty column you notice after the feed is live.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .parse import fold

# The canonical field names. Everything downstream refers to these and never to
# a supplier's header text.
FIELDS = (
    "sku",
    "handle",
    "title",
    "vendor",
    "product_type",
    "price",
    "cost",
    "compare_at",
    "barcode",
    "weight",
    "weight_unit",
    "dimensions",
    "quantity",
    "stock_status",
    "published",
    "taxable",
    "image_url",
    "description",
    "tags",
    "updated_at",
)

STOCK_STATES = ("in_stock", "out_of_stock", "backorder", "preorder", "discontinued")


class ProfileError(Exception):
    """The profile is wrong. Raised at load time, before any row is read."""


@dataclass(frozen=True)
class Profile:
    name: str
    currency: str
    columns: dict[str, str]  # folded supplier header -> canonical field
    vendors: dict[str, str]  # folded alias -> canonical vendor name
    stock_status: dict[str, str]  # folded input -> canonical state
    booleans: dict[str, bool]  # folded input -> True/False
    acronyms: dict[str, str]  # lowercased -> preferred casing
    minor_words: set[str]
    required: tuple[str, ...]
    description_max: int
    title_max: int
    path: Path | None = None
    source: dict = field(default_factory=dict)

    def canonical_field(self, header: str) -> str | None:
        return self.columns.get(fold(header))

    def headers_for(self, name: str) -> list[str]:
        return [k for k, v in self.columns.items() if v == name]


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ProfileError(message)


def _alias_map(
    block: dict, valid: tuple[str, ...] | None, label: str, where: str
) -> dict[str, str]:
    """`{canonical: [aliases]}` inverted into `{folded alias: canonical}`.

    Two canonical values claiming the same alias is an error rather than a
    last-one-wins, because last-one-wins depends on dict ordering in a JSON
    file and is exactly the kind of bug that shows up as three products in the
    wrong vendor six weeks later.
    """
    _expect(isinstance(block, dict), f"{where}: {label} must be an object")
    out: dict[str, str] = {}
    for canonical, aliases in block.items():
        if valid is not None:
            _expect(
                canonical in valid,
                f"{where}: {label} has no {canonical!r}. Known: {', '.join(valid)}",
            )
        _expect(
            isinstance(aliases, list),
            f"{where}: {label}[{canonical!r}] must be a list of aliases",
        )
        for alias in [canonical, *aliases]:
            key = fold(str(alias))
            if not key:
                continue
            owner = out.get(key)
            _expect(
                owner in (None, canonical),
                f"{where}: {label} alias {alias!r} is claimed by both "
                f"{owner!r} and {canonical!r}",
            )
            out[key] = canonical
    return out


def load_profile(path: str | Path) -> Profile:
    path = Path(path)
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(f"no profile at {path}") from None
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{path}: not valid JSON ({exc})") from None
    return build_profile(source, where=str(path), path=path)


def build_profile(source: dict, where: str = "profile", path: Path | None = None) -> Profile:
    _expect(isinstance(source, dict), f"{where}: the top level must be an object")

    unknown = set(source) - {
        "name",
        "currency",
        "columns",
        "vendors",
        "stock_status",
        "booleans",
        "acronyms",
        "minor_words",
        "required",
        "limits",
    }
    _expect(not unknown, f"{where}: unknown key(s) {', '.join(sorted(unknown))}")

    columns = _alias_map(source.get("columns", {}), FIELDS, "columns", where)
    _expect("sku" in columns.values(), f"{where}: columns must map something to 'sku'")

    stock = _alias_map(source.get("stock_status", {}), STOCK_STATES, "stock_status", where)

    bool_map_raw = _alias_map(source.get("booleans", {}), ("true", "false"), "booleans", where)
    booleans = {k: v == "true" for k, v in bool_map_raw.items()}

    vendors_block = source.get("vendors", {})
    _expect(isinstance(vendors_block, dict), f"{where}: vendors must be an object")
    vendors = _alias_map(vendors_block, None, "vendors", where)

    required = tuple(source.get("required", ("sku", "title", "price")))
    for name in required:
        _expect(
            name in FIELDS,
            f"{where}: required lists {name!r}, which is not a field. "
            f"Known: {', '.join(FIELDS)}",
        )

    limits = source.get("limits", {})
    _expect(isinstance(limits, dict), f"{where}: limits must be an object")
    unknown_limits = set(limits) - {"description_max", "title_max"}
    _expect(
        not unknown_limits,
        f"{where}: unknown limit(s) {', '.join(sorted(unknown_limits))}. "
        "Known: description_max, title_max",
    )

    currency = str(source.get("currency", "USD")).upper()
    _expect(
        len(currency) == 3 and currency.isalpha(),
        f"{where}: currency must be a three-letter code, got {currency!r}",
    )

    acronyms_list = source.get("acronyms", [])
    _expect(isinstance(acronyms_list, list), f"{where}: acronyms must be a list")

    return Profile(
        name=str(source.get("name", path.stem if path else "profile")),
        currency=currency,
        columns=columns,
        vendors=vendors,
        stock_status=stock,
        booleans=booleans,
        acronyms={str(a).lower(): str(a) for a in acronyms_list},
        minor_words={str(w).lower() for w in source.get("minor_words", [])},
        required=required,
        description_max=int(limits.get("description_max", 5000)),
        title_max=int(limits.get("title_max", 255)),
        path=path,
        source=source,
    )
