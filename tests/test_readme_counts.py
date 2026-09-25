"""The README's test-count claims, read back off pytest's own collection.

This file is byte-identical in all four portfolio repos, the same way
test_readme_clip.py, test_demo_fetch.py and test_demo_sheet.py are, because
what it checks is the same set of sentences in four READMEs. It imports nothing
from the piece it runs inside.

Why it exists. test_readme_clip.py guards one number in these READMEs — the
clip length — and the issue that shipped it (THE-269) found that two of the
four test counts were *already* stale: feed-clean said 304 against 308
collected, inbox-filer 245 against 247, both from commits that added tests four
days after a human had re-measured every number in those files by hand. The
counts were corrected. Within a day catalog-watch's had gone stale again (231
claimed, 235 collected, from the one commit pushed after THE-269 closed). Three
strikes on the same number is not a person being careless; it is a number that
nobody can see.

Unlike the wall-clock timings in the same READMEs, a test count is
deterministic: `pytest --collect-only` answers it identically on any machine,
in under a second, with no toolchain and no network. So it gets a test. The
timings get `make timings` and a human — see tools/timings.py, which explains
why asserting a wall clock here would buy a flaky suite rather than a guard.

What this guards, exactly:

  * every "N tests" in the README equals what pytest collects, and there is at
    least one of them;
  * the node ids pytest lists and the total pytest reports agree with each
    other (two counts of the same thing, because a reader that silently
    answers zero is worse than one that raises);
  * the "four of which skip in a dead clone" sentence names the number of
    tests that need a toolchain, found by node id rather than restated;
  * any per-file claim ("the nine in `test_make_targets.py`") equals that
    file's collected count — feed-clean is the only one of the four that makes
    one today, and the parser is pinned on synthetic text so it is proved in
    every repo whether or not that repo has a claim to apply it to;
  * any "the other N" remainder equals the total minus the per-file claims.

What it cannot see, said out loud:

  * **Whether a *reworded* claim is a claim.** A regex cannot tell "we dropped
    this sentence" from "we rephrased it". So CLAIMED_AT_BIRTH records which
    rows each repo stated when this file was written, and a repo that stops
    matching one fails rather than quietly guarding nothing. A genuinely
    deleted sentence means deleting its entry here, on purpose, in the same
    commit.
  * **Whether four is really all that skips in a dead clone.** Only a dead
    clone can answer that. Each suite has five other conditional skips — bash
    missing (test_demo_fetch.py, test_demo_outputs.py), make or .venv missing
    (test_make_targets.py), openpyxl missing (test_workbook.py or
    test_index.py) — and none of them fires on a machine that got through
    `make setup`, which is why the measured dead-clone runs skip four. That is
    a property of the machine, not of this file, and this file does not claim
    it. It checks the number in the sentence against the collected count of
    the tests named in TOOLCHAIN_SKIPS.

    **TOOLCHAIN_SKIPS is a declared list and nothing discovers it**, which is
    the same weakness SHARED_ROOT has one directory over: a new test that
    skips without a toolchain is invisible here until someone adds its node
    id. It was two entries and one file until THE-285 added the title card,
    and the sentence in four READMEs saying "they are the suite's only skips"
    was false the moment the second file appeared. Adding an entry is one
    line; noticing that one is missing is a dead-clone run.

The maintainers' drift checker holds the four copies of this file identical,
from its SHARED_ROOT list (THE-274). It is a rookery tool and is not in this
repo, so there is nothing here to run. That list is declared rather than
discovered, so a new shared file beside this one stays checked by nothing until
its path is added to it.
"""

from __future__ import annotations

import functools
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"

# The tests the READMEs mean by "four of which skip in a dead clone": the ones
# that want something `make demo` downloads.
# Every test that skips for want of a toolchain, as node-id prefixes. The
# count comes out of collection rather than being restated here, so a
# parametrised test contributes however many cases it really has, and renaming
# one fails this file loudly (test_every_toolchain_skip_still_exists) instead
# of freeing its own guard.
TOOLCHAIN_SKIPS = (
    # Needs ffprobe. Parametrised over the gif and the mp4, so this one prefix
    # is two collected tests, and adding a third encode moves the README.
    "tests/test_readme_clip.py::test_the_readers_agree_with_ffprobe",
    # Needs ffmpeg to decode H.264: the poster against frame 0 of the mp4.
    "tests/test_demo_card.py::test_the_mp4_frame_zero_is_the_poster",
    # Needs the vendored Chromium and the vendored face.
    "tests/test_demo_card.py::test_the_card_font_is_jailed",
)

# Number words these READMEs actually use in a count claim, plus the digits.
# Narrow on purpose: only a numeric claim matches the per-file and skip
# patterns below, so "several tests in `test_parse.py`" is not silently read as
# a claim about a number. If a README wants a per-file count guarded, it writes
# the word or the digit.
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}
_NUMBER = "|".join([*NUMBER_WORDS, r"\d+"])

# "304 tests", "the same 333 tests", "| dead clone -> make test (272 tests) |".
TOTAL = re.compile(r"(\d+) tests\b")

# "two of which skip in a dead clone", "Two of them skip in a dead clone",
# "Two of the 333 skip in a dead clone". Group 2 is the total when the
# sentence restates it, which is a second place for the total to go stale.
SKIPS = re.compile(
    rf"\b({_NUMBER})\s+of\s+(?:which|them|the\s+(\d+))\b[^.]*?\bskip", re.IGNORECASE
)

# "The nine in `test_make_targets.py` run `make` in a throwaway copy".
# `\s+` rather than a literal space because these READMEs are hard-wrapped at
# 79 columns and the line break lands between the count and its file as often
# as not — which is exactly how the first draft of this pattern found nothing
# in the one repo that makes the claim.
PER_FILE = re.compile(
    rf"\b({_NUMBER})\s+in\s+`(?:tests/)?(test_[a-z0-9_]+\.py)`", re.IGNORECASE
)

# "the other 324 take 42" — the complement of the per-file claims.
REMAINDER = re.compile(r"\bthe other (\d+)\b")

# Which rows each repo stated a number for when this file was written
# (2026-09-23), so that a reworded sentence reads as a failure rather than as
# "this piece makes no claim". A regex cannot tell those apart; this can.
#
# Rows: total (an "N tests" figure), skips (the dead-clone skip sentence),
# per_file (at least one per-file count), remainder (an "the other N").
CLAIMED_AT_BIRTH = {
    "pdf-to-csv": {"total", "skips"},
    "catalog-watch": {"total", "skips"},
    "feed-clean": {"total", "skips", "per_file", "remainder"},
    "inbox-filer": {"total", "skips"},
}


def piece() -> str:
    """Which of the four this is, read off its own pyproject.toml.

    Not the directory name. A basename is not a property of a repo: `git clone
    <url> feeds` is an honest checkout wearing the wrong one, and so is the
    <tmp>/clone that tools/timings.py makes to time a dead clone. Keying on
    Path.name was the first draft of this file, and the first dead-clone `make
    test` run found it — five failures in a checkout whose only sin was being
    called "clone", in the one environment these READMEs describe.
    """
    found = re.search(
        r'^name\s*=\s*"([^"]+)"',
        (REPO / "pyproject.toml").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert found is not None, "no [project] name in pyproject.toml"
    return found.group(1)


def claimed(row: str) -> bool:
    """Whether this repo stated `row` when this file was written.

    A piece this file was copied into without being declared raises rather than
    defaulting to "claims nothing" — the default that makes every check below
    vacuous.
    """
    name = piece()
    try:
        return row in CLAIMED_AT_BIRTH[name]
    except KeyError:
        raise AssertionError(
            f"{name} is not in CLAIMED_AT_BIRTH. Add it with the rows its "
            f"README states, or this file guards nothing here. Known: "
            f"{', '.join(sorted(CLAIMED_AT_BIRTH))}"
        ) from None


# --- what pytest collects ---------------------------------------------------


@functools.lru_cache(maxsize=1)
def collected() -> tuple[int, tuple[str, ...]]:
    """(total pytest reports, every node id it listed).

    A subprocess rather than an in-process hook, because the number the README
    claims is the number a reader gets from running pytest, and reading it any
    other way would be a different measurement dressed as the same one. It
    costs one collection — measured at 0.20-0.31 s across the four pieces.

    `-o addopts=` neutralises anything a pyproject.toml adds to the command
    line, so this counts the suite rather than whatever the local config
    selects. `-p no:cacheprovider` keeps it from writing a cache inside a run.

    Every way of not getting an answer raises. A helper that returned 0 for a
    collection error would turn every assertion below into one that passes on
    rubble, which is the failure mode this whole file was written against.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-o", "addopts=", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"`pytest --collect-only` exited {proc.returncode}; there is no count "
            f"to compare the README against.\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
    return parse_collection(proc.stdout)


def parse_collection(stdout: str) -> tuple[int, tuple[str, ...]]:
    """Pull the total and the node ids out of `pytest --collect-only -q`.

    Kept a pure function of the text so it can be pinned on recorded output,
    including the shapes that must raise.
    """
    summary = re.search(r"^(\d+) tests? collected", stdout, re.MULTILINE)
    if summary is None:
        raise ValueError(
            "no 'N tests collected' line in pytest's output: the format changed, "
            "and a reader that shrugged at that would report a wrong count"
        )
    errors = re.search(r"^\d+ tests? collected, (\d+) errors?", stdout, re.MULTILINE)
    if errors is not None:
        raise ValueError(
            f"collection reported {errors.group(1)} error(s); the count is short by "
            f"however many tests are in the files that failed to import"
        )
    ids = tuple(line.strip() for line in stdout.splitlines() if "::" in line)
    return int(summary.group(1)), ids


def per_file_counts(ids: tuple[str, ...]) -> dict[str, int]:
    """Collected count keyed by test file basename."""
    counts: dict[str, int] = {}
    for node in ids:
        name = Path(node.split("::", 1)[0]).name
        counts[name] = counts.get(name, 0) + 1
    return counts


def number(text: str) -> int:
    """A count written as a digit string or as one of NUMBER_WORDS."""
    lowered = text.lower()
    if lowered in NUMBER_WORDS:
        return NUMBER_WORDS[lowered]
    return int(lowered)


# --- the totals -------------------------------------------------------------


def test_the_readme_states_a_total_test_count() -> None:
    """Zero matches means the sentence was reworded and every check below it is
    guarding nothing, which is the one failure this file cannot afford to be
    quiet about."""
    found = TOTAL.findall(README.read_text(encoding="utf-8"))
    assert claimed("total"), "unreachable: every piece claims a total"
    assert found, (
        "README.md states no test count in the form 'N tests'. If the sentence "
        "moved, move this pattern with it; do not leave the count unguarded."
    )


def test_every_total_in_the_readme_is_the_same_number() -> None:
    """feed-clean and inbox-filer each state theirs three times — in the quick
    start, in the limitations and in the tests section or the tree. Three
    copies of a number drift apart before they drift from reality."""
    found = [int(n) for n in TOTAL.findall(README.read_text(encoding="utf-8"))]
    assert len(set(found)) == 1, (
        f"README.md states {len(set(found))} different test counts: "
        f"{sorted(set(found))}. They are all the same claim."
    )


def test_the_stated_total_is_what_pytest_collects() -> None:
    total, _ = collected()
    found = [int(n) for n in TOTAL.findall(README.read_text(encoding="utf-8"))]
    assert found[0] == total, (
        f"README.md says {found[0]} tests; pytest collects {total}. Re-measure "
        f"the sentence and the timings beside it — a commit that changes the "
        f"count usually changes the suite's wall clock too. `make timings` "
        f"prints both."
    )


def test_the_node_ids_and_pytests_own_total_agree() -> None:
    """Two counts of the same thing. The node-id count is what the per-file
    checks below are built on, and nothing else would notice if the two
    readings of one collection disagreed."""
    total, ids = collected()
    assert len(ids) == total


# --- the dead-clone skips ---------------------------------------------------


def test_the_readme_states_the_dead_clone_skip_count_exactly_once() -> None:
    assert claimed("skips"), "unreachable: every piece claims a skip count"
    found = SKIPS.findall(README.read_text(encoding="utf-8"))
    assert len(found) == 1, (
        f"README.md must say how many tests skip in a dead clone exactly once; "
        f"found {len(found)}. Two statements of it is two numbers to keep right."
    )


def test_the_skip_count_is_the_toolchain_skips_own_count() -> None:
    """"Four" is not a constant anyone typed — it is what TOOLCHAIN_SKIPS
    collects. The first entry is parametrised over the gif and the mp4, so
    adding a third encode moves the README rather than passing quietly."""
    _, ids = collected()
    actual = sum(1 for node in ids
                 if any(node.startswith(p) for p in TOOLCHAIN_SKIPS))
    found = SKIPS.findall(README.read_text(encoding="utf-8"))
    assert number(found[0][0]) == actual, (
        f"README.md says {found[0][0]} test(s) skip in a dead clone; the tests "
        f"TOOLCHAIN_SKIPS names collect {actual}."
    )


def test_every_toolchain_skip_still_exists() -> None:
    """A test that no longer exists collects zero, and zero would agree with a
    README that had dropped the sentence — so each prefix is checked for
    directly, one at a time rather than as a total. A rename here is a rename
    of something the READMEs describe."""
    _, ids = collected()
    missing = [p for p in TOOLCHAIN_SKIPS
               if not any(node.startswith(p) for node in ids)]
    assert not missing, (
        f"nothing collects under {missing}. If it was renamed, rename it in "
        f"TOOLCHAIN_SKIPS; if it was deleted, the READMEs' skip sentence is "
        f"now wrong in all four repos."
    )


def test_a_total_restated_inside_the_skip_sentence_is_the_same_total() -> None:
    """feed-clean writes "Two of the 333 skip", which puts the total in a
    second place. Vacuous where the sentence does not restate it, and that is
    visible rather than assumed: the assertion below runs on the parse, not on
    a repo name."""
    total, _ = collected()
    found = SKIPS.findall(README.read_text(encoding="utf-8"))
    restated = found[0][1]
    if restated:
        assert int(restated) == total, (
            f"the skip sentence in README.md says {restated} tests; pytest "
            f"collects {total}."
        )


# --- the per-file splits ----------------------------------------------------


def test_the_readme_still_makes_the_per_file_claims_it_was_written_with() -> None:
    found = PER_FILE.findall(README.read_text(encoding="utf-8"))
    if claimed("per_file"):
        assert found, (
            "README.md made a per-file test-count claim when this file was "
            "written and now matches none. If the sentence was reworded, move "
            "the pattern; if it was deleted, drop 'per_file' from this repo's "
            "entry in CLAIMED_AT_BIRTH in the same commit."
        )
    else:
        assert not found, (
            f"README.md has grown a per-file test-count claim ({found}) that "
            f"CLAIMED_AT_BIRTH does not list. Add 'per_file' to this repo's "
            f"entry so the claim is declared as well as checked."
        )


def test_every_per_file_claim_matches_that_files_collected_count() -> None:
    _, ids = collected()
    counts = per_file_counts(ids)
    for written, filename in PER_FILE.findall(README.read_text(encoding="utf-8")):
        assert filename in counts, (
            f"README.md counts tests in {filename}, which collects nothing. "
            f"Collected files: {', '.join(sorted(counts))}"
        )
        assert number(written) == counts[filename], (
            f"README.md says {written} test(s) in {filename}; it collects "
            f"{counts[filename]}."
        )


def test_the_remainder_claim_is_the_total_minus_the_per_file_claims() -> None:
    """feed-clean's "the nine in test_make_targets.py ... the other 324" —
    a number that is arithmetic on two others and drifts when either moves."""
    text = README.read_text(encoding="utf-8")
    found = REMAINDER.findall(text)
    if claimed("remainder"):
        assert found, (
            "README.md stated a 'the other N' remainder when this file was "
            "written and now matches none. Move the pattern or drop "
            "'remainder' from CLAIMED_AT_BIRTH for this repo."
        )
    total, _ = collected()
    accounted = sum(number(w) for w, _ in PER_FILE.findall(text))
    for written in found:
        assert int(written) == total - accounted, (
            f"README.md says the other {written}; the total is {total} and "
            f"{accounted} are accounted for by name, so it is "
            f"{total - accounted}."
        )


# --- the parsers, proved on text rather than on this repo's README ----------
#
# Every check above is only as good as its pattern, and three of the four
# patterns are vacuous in three of the four repos. These run everywhere.


def test_total_reads_a_count_wherever_the_sentence_puts_it() -> None:
    assert TOTAL.findall("304 tests, two of which skip in a dead clone") == ["304"]
    assert TOTAL.findall("make test    # the same 333 tests: 72s warm") == ["333"]
    assert TOTAL.findall("| dead clone -> `make test` (272 tests) | 19.1 s |") == ["272"]
    assert TOTAL.findall("Tested against the bundled fixture and 333 tests.") == ["333"]


def test_total_ignores_numbers_that_are_not_test_counts() -> None:
    assert TOTAL.findall("Tested against the 12 documents in `samples/`") == []
    assert TOTAL.findall("318 rows of an invented supplier's weekly export") == []
    assert TOTAL.findall("**23 seconds** to re-record once the toolchain") == []
    assert TOTAL.findall("35 attachments: 29 filed by a rule, 6 unsorted") == []


@pytest.mark.parametrize(
    "text, count, restated",
    [
        ("304 tests, two of which skip in a dead clone — the cross-check", 2, ""),
        ("272 tests. Two of them skip in a dead clone — the cross-check", 2, ""),
        ("Two of the 333 skip in a dead clone — the `ffprobe` cross-check", 2, "333"),
        ("231 tests, 3 of which skip in a dead clone", 3, ""),
    ],
)
def test_skips_reads_each_wording_the_four_readmes_use(
    text: str, count: int, restated: str
) -> None:
    found = SKIPS.findall(text)
    assert len(found) == 1
    assert number(found[0][0]) == count
    assert found[0][1] == restated


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Two tests skip in a dead clone.",  # no "of which/them/the"
        "The suite runs skip-free from a dead clone.",
        # A sentence break between the count and the word: two claims, not one.
        "two of which are new. Nothing here can skip.",
    ],
)
def test_skips_does_not_invent_a_claim(text: str) -> None:
    assert SKIPS.findall(text) == []


def test_per_file_reads_a_word_or_a_digit_and_either_path_form() -> None:
    assert PER_FILE.findall("The nine in `test_make_targets.py` run `make`") == [
        ("nine", "test_make_targets.py")
    ]
    assert PER_FILE.findall("the 74 in `tests/test_parse.py` are the parsers") == [
        ("74", "test_parse.py")
    ]
    # Hard-wrapped at 79 columns, the break lands wherever it lands.
    assert PER_FILE.findall("Two files are most of that. The nine\nin `test_make_targets.py` run") == [
        ("nine", "test_make_targets.py")
    ]


def test_per_file_ignores_prose_that_merely_names_a_file() -> None:
    """The sentence every one of the four READMEs carries — "the `ffprobe`
    cross-check in `test_readme_clip.py`" — sits one word away from matching,
    and a pattern that read "check" as a number would turn three vacuous
    guards into three wrong ones."""
    assert PER_FILE.findall(
        "the `ffprobe` cross-check in `tests/test_readme_clip.py`, which needs"
    ) == []
    assert PER_FILE.findall("Which `make` targets may touch `out/`") == []
    assert PER_FILE.findall("several in `test_parse.py`") == []


def test_remainder_reads_only_a_digit_remainder() -> None:
    assert REMAINDER.findall("take 31 seconds between them; the other 324 take 42") == ["324"]
    assert REMAINDER.findall("the other files take 42 seconds") == []


def test_the_piece_names_itself_off_a_committed_file() -> None:
    """The identity every check above keys on must not be the directory name.
    A dead clone — the environment these READMEs are *about* — is checked out
    at whatever path the tool timing it chose."""
    assert piece() in CLAIMED_AT_BIRTH
    assert piece() == re.search(
        r'^name\s*=\s*"([^"]+)"',
        (REPO / "pyproject.toml").read_text(encoding="utf-8"),
        re.MULTILINE,
    ).group(1)


def test_number_reads_both_spellings_and_refuses_anything_else() -> None:
    assert number("nine") == 9
    assert number("Two") == 2
    assert number("324") == 324
    with pytest.raises(ValueError):
        number("several")


# --- the collection reader, proved on recorded output ----------------------


PYTEST_QUIET_COLLECT = """tests/test_cli.py::TestFirstRun::test_writes_all_three_outputs
tests/test_parse.py::test_money[1.50-150]
tests/test_parse.py::test_money[2,00-200]

3 tests collected in 0.31s
"""


def test_parse_collection_reads_the_total_and_the_node_ids() -> None:
    total, ids = parse_collection(PYTEST_QUIET_COLLECT)
    assert total == 3
    assert ids == (
        "tests/test_cli.py::TestFirstRun::test_writes_all_three_outputs",
        "tests/test_parse.py::test_money[1.50-150]",
        "tests/test_parse.py::test_money[2,00-200]",
    )


def test_parse_collection_handles_the_singular() -> None:
    total, ids = parse_collection("tests/test_a.py::test_b\n\n1 test collected in 0.1s\n")
    assert (total, len(ids)) == (1, 1)


def test_parse_collection_refuses_output_with_no_summary_line() -> None:
    with pytest.raises(ValueError, match="no 'N tests? collected' line|no 'N tests collected'"):
        parse_collection("tests/test_a.py::test_b\n")


def test_parse_collection_refuses_a_run_that_could_not_import_a_file() -> None:
    """The dangerous shape: pytest exits non-zero *and* prints a total, and
    that total is short by every test in the file it could not import."""
    text = "tests/test_a.py::test_b\n\n1 test collected, 1 error in 0.2s\n"
    with pytest.raises(ValueError, match="error"):
        parse_collection(text)


def test_per_file_counts_groups_by_basename() -> None:
    counts = per_file_counts((
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_two[x]",
        "tests/test_b.py::Klass::test_three",
    ))
    assert counts == {"test_a.py": 2, "test_b.py": 1}
