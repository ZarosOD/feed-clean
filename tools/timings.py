#!/usr/bin/env python3
"""Re-measure the numbers in README.md that a test cannot guard, and say which
sentences they contradict.

    make timings                      # everything, three repeats each
    make timings ARGS="--list"         # what it can measure, and the cost
    make timings ARGS="--only tests,test-warm --repeat 1"
    python3 tools/timings.py --help

This file is byte-identical in all four portfolio repos (pdf-to-csv,
catalog-watch, feed-clean, inbox-filer). It is stdlib only and needs no venv,
on purpose: half of what it measures is what a client gets from a dead clone,
and a tool that needed the venv first could not measure the clone that has not
built one yet.

--- Why this is a script and not a test ------------------------------------

tests/test_readme_clip.py guards the clip length. tests/test_readme_counts.py
guards the test counts. Both can, because both numbers are deterministic: the
clip is a property of a committed file, and `pytest --collect-only` answers the
same on any machine in under a second.

Everything else these READMEs claim is a wall clock or a disk size on one
machine:

    dead clone -> `make run`            moves with the network (it fetches uv
                                        and a wheel or two)
    dead clone -> `make test`           the above plus the suite
    `make test`, venv warm              the suite, on this CPU
    `make demo`, toolchain warm         a headless browser recording a scene
    `.venv` / `demo/.toolchain` sizes   pinned versions, so stable, but they
                                        move whenever a pin does

Asserting any of those in CI buys a flaky suite or a slow one, not a guard. So
they get this: a target run by hand before a push, which measures them and
prints the diff against what the README currently says. Nothing here runs in
CI, nothing here is asserted by the suite, and a REVIEW line below is a
sentence to go and read, not a build failure.

--- How the diff works, and what it cannot tell you ------------------------

Each row declares a `select` pattern that picks the README chunks stating it (a
chunk is one sentence, one table row, or one line of a fenced block) and a
`numbers` pattern that pulls the figures out of them. The verdict compares the
measured median against the *hull* of every figure in those chunks: inside is
`ok`, outside is `REVIEW`.

Two limits, both deliberate:

  * **One sentence can carry two rows' figures**, and then both hulls are
    wider than either claim. feed-clean's quick start says "the same 333 tests:
    72s warm, 78s from that dead clone" — one chunk, two rows, a hull of 72-78
    for each. The report prints the chunk and its figures under every row that
    selected it, so a reader can see that is what happened. A tighter pattern
    per wording was the alternative, and it would go quiet the first time
    somebody rewrapped a line.
  * **A reworded claim and a deleted claim look identical to a regex.** So
    CLAIMED_AT_BIRTH records which rows each README stated when this file was
    written, and a row that stops matching is reported `MISSING`, not `n/a`.
    Deleting a claim for real means deleting its entry here in the same commit.

Exit code: 0 when every row is `ok`, `n/a` or skipped with a stated reason; 1
when any row is `REVIEW`, `STALE` or `MISSING`; 2 when you invoked it wrong.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"

# A dead clone is measured under cron's environment, not your shell's: no `uv`
# on PATH, no caches, an empty HOME. Same shape THE-263 measured these numbers
# with (`env -i`, empty HOME, PATH=/usr/bin:/bin) — reproduced here rather than
# described, because "measured on a clean machine" is half of what the READMEs
# claim and a shell that happened to have uv would quietly measure something
# else.
DEAD_CLONE_PATH = "/usr/bin:/bin"

SECONDS = r"(\d+(?:\.\d+)?)\s*(?:s\b|secs?\b|seconds?\b)"
MEGABYTES = r"(\d+(?:\.\d+)?)\s*MB\b"
COUNT_OF_TESTS = r"(\d+) tests\b"


class Row:
    """One measurable claim: how to measure it, and where the README states it.

    `select` picks chunks; `numbers` pulls figures out of the chunks selected.
    Both are searched case-insensitively. `cost` is a human hint printed by
    --list so nobody starts a four-minute row expecting a second.
    """

    def __init__(self, key, title, unit, cost, select, numbers, exact=False):
        self.key = key
        self.title = title
        self.unit = unit
        self.cost = cost
        self.select = re.compile(select, re.IGNORECASE | re.DOTALL)
        self.numbers = re.compile(numbers, re.IGNORECASE)
        self.exact = exact  # deterministic: equality, not a hull


ROWS = [
    Row("tests", "tests collected", "", "instant",
        select=COUNT_OF_TESTS, numbers=COUNT_OF_TESTS, exact=True),
    Row("test-warm", "`make test`, .venv warm", "s", "one suite run",
        select=r"(?=.*\bwarm\b)(?=.*\btests?\b).*|\d+ tests,[^.]*seconds",
        numbers=SECONDS),
    Row("run-dead", "dead clone -> `make run`", "s", "~10 s per repeat, network",
        select=r"(?=.*dead clone)(?=.*(?:real output|filed output|make run)).*",
        numbers=SECONDS),
    Row("test-dead", "dead clone -> `make test`", "s", "clone + one suite run per repeat",
        select=r"(?=.*dead clone)(?=.*(?:make test|the suite)).*",
        numbers=SECONDS),
    Row("test-split", "the files the README times by name", "s", "two extra suite runs",
        select=r"(?=.*`test_[a-z0-9_]+\.py`)(?=.*second).*",
        numbers=SECONDS),
    Row("demo-warm", "`make demo`, toolchain warm", "s", "~25 s per repeat",
        select=r"re-record|(?=.*make demo)(?=.*warm).*",
        numbers=SECONDS),
    Row("toolchain-size", "`demo/.toolchain/`", "MB", "instant",
        select=r"(?=.*toolchain)(?=.*MB).*", numbers=MEGABYTES),
    Row("chromium-size", "the unpacked Chromium inside it", "MB", "instant",
        select=r"(?=.*chromium)(?=.*MB).*", numbers=MEGABYTES),
    Row("venv-size", "`.venv`", "MB", "instant",
        select=r"(?=.*\.venv)(?=.*MB).*", numbers=MEGABYTES),
]

BY_KEY = {row.key: row for row in ROWS}

# Which rows each README stated a figure for on 2026-09-23, when this file was
# written. A row listed here that now matches no chunk is MISSING — the README
# was reworded and the diff below it went quiet. A row *not* listed that starts
# matching is reported too: a new claim nobody declared is a new number nobody
# is re-measuring.
#
# The gaps are real editorial choices, not oversights: pdf-to-csv and
# catalog-watch quote no suite timing at all, and only inbox-filer quotes its
# `.venv` size.
CLAIMED_AT_BIRTH = {
    "pdf-to-csv": {"tests", "demo-warm", "toolchain-size", "chromium-size"},
    "catalog-watch": {"tests", "run-dead", "demo-warm", "toolchain-size",
                      "chromium-size"},
    "feed-clean": {"tests", "test-warm", "run-dead", "test-dead", "test-split",
                   "demo-warm", "toolchain-size", "chromium-size"},
    "inbox-filer": {"tests", "test-warm", "run-dead", "test-dead", "demo-warm",
                    "toolchain-size", "chromium-size", "venv-size"},
}


# --- reading the README -----------------------------------------------------


def chunks(text):
    """[(line number, text)] — one sentence, table row or fenced line each.

    The READMEs are hard-wrapped at 79 columns, so a claim is almost never one
    line: "**About 9 seconds** from a dead clone to real output" spans two.
    Selecting by line would miss every claim whose keyword and whose number
    landed on different sides of a wrap, which is most of them. So prose
    paragraphs are unwrapped and then split on sentence ends.

    Table rows and fenced-code lines stay whole lines: a `|`-row is already one
    claim, and feed-clean states its two suite timings in a code comment.
    """
    out = []
    fenced = False
    paragraph, start = [], 0
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            out.extend(_sentences(paragraph, start))
            paragraph, start = [], 0
            continue
        if fenced or stripped.startswith("|") or not stripped:
            out.extend(_sentences(paragraph, start))
            paragraph, start = [], 0
            if stripped:
                out.append((number, stripped))
            continue
        if not paragraph:
            start = number
        paragraph.append(stripped)
    out.extend(_sentences(paragraph, start))
    return out


def _sentences(lines, start):
    """Split an unwrapped paragraph into sentences, all tagged with its first
    line. A per-sentence line number would need the wrap put back; the first
    line of the paragraph is enough to find the prose in an editor, and the
    report prints the sentence itself."""
    if not lines:
        return []
    joined = " ".join(lines)
    return [(start, part.strip())
            for part in re.split(r"(?<=[.!?])\s+", joined) if part.strip()]


def claims(row, text):
    """[(line number, chunk, [figures])] for every chunk stating this row."""
    found = []
    for number, chunk in chunks(text):
        if row.select.search(chunk):
            figures = [float(m) for m in row.numbers.findall(chunk)]
            if figures:
                found.append((number, chunk, figures))
    return found


# --- measuring --------------------------------------------------------------


class Skip(Exception):
    """Cannot measure this here, with the reason. Never a silent pass: a row
    that could not run says so on its own line and is not counted as `ok`."""


def timed(argv, cwd, env=None):
    """Wall clock for one subprocess, and its output if it failed.

    A target that exits non-zero has not been timed — it has failed partway
    through — so it raises rather than contributing a fast, wrong number.
    """
    started = time.monotonic()
    proc = subprocess.run(argv, cwd=str(cwd), env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        tail = proc.stdout.decode("utf-8", "replace")[-2000:]
        raise Skip("%s exited %d after %.1f s:\n%s"
                   % (" ".join(argv), proc.returncode, elapsed, tail))
    return elapsed


def dead_clone_env(home):
    """cron's environment, not this shell's. An explicit dict, so nothing
    inherits: an inherited PATH with `uv` on it measures a different claim."""
    return {"HOME": str(home), "PATH": DEAD_CLONE_PATH, "LANG": "C"}


def in_a_dead_clone(target):
    """Clone HEAD into a temp dir with an empty HOME and time one `make`.

    A fresh clone per measurement, because "from a dead clone" includes
    building the venv and fetching uv — the second run of anything in the same
    clone is a different, warm number.

    The clone is of HEAD, which is what a client gets; uncommitted work is not
    measured and `--repeat` is not the place to find that out, so the report
    says so at the top when the tree is dirty.
    """
    def measure():
        with tempfile.TemporaryDirectory(prefix="timings-") as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            clone = root / "clone"
            subprocess.run(["git", "clone", "--quiet", "--depth", "1",
                            "file://" + str(REPO), str(clone)],
                           check=True, stdout=subprocess.DEVNULL)
            return timed(["make", target], clone, dead_clone_env(home))
    return measure


def warm_suite():
    python = REPO / ".venv" / "bin" / "python"
    if not python.is_file():
        raise Skip("no .venv — run `make setup` first; this row is the warm number")
    return timed([str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider"], REPO)


def named_file_splits():
    """Time each test file the README names, and the remainder.

    Driven by the README's own per-file claims rather than a hardcoded list, so
    the tool times whatever that piece chose to quote. Each named file is timed
    alone and the rest are timed with it ignored, which is what "the nine in
    test_make_targets.py ... take 31 seconds between them; the other 324 take
    42" asserts.
    """
    python = REPO / ".venv" / "bin" / "python"
    if not python.is_file():
        raise Skip("no .venv — run `make setup` first")
    named = sorted(set(re.findall(r"`(?:tests/)?(test_[a-z0-9_]+\.py)`",
                                  _selected_text("test-split"))))
    if not named:
        raise Skip("this README times no test file by name")
    base = [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    out = {}
    for name in named:
        out[name] = timed(base + ["tests/" + name], REPO)
    out["the rest"] = timed(
        base + ["--ignore=tests/" + n for n in named], REPO)
    return out


def _selected_text(key):
    """Every chunk this row selected, joined — so a measurement can read the
    same sentence the diff does instead of a second copy of the pattern."""
    text = README.read_text(encoding="utf-8")
    return " ".join(chunk for _, chunk, _ in claims(BY_KEY[key], text))


def warm_demo():
    """Re-record with the toolchain already here, into a scratch directory.

    `DEMO_OUT_DIR` keeps it off `demo/out/`, which is committed: the four clips
    are shipped assets and a timing run must not be able to move them. What it
    does touch is the piece's own output (`setup.sh --fresh` removes it so the
    recorded run is a first run) and the scene rewrites it — report_tree_state()
    prints anything that ends up differing from HEAD.

    Refuses rather than downloads: without the toolchain this is a 760 MB fetch
    wearing a 25-second row's name, and the first-run wall clock is the one
    number none of the four READMEs claims.
    """
    if not (REPO / "demo" / ".toolchain" / "browsers").is_dir():
        raise Skip("no demo/.toolchain/browsers — this row is the *warm* "
                   "re-record; run `make demo` once first")
    env = dict(os.environ)
    env["DEMO_OUT_DIR"] = "demo/.scratch/timings-out"
    return timed(["make", "demo"], REPO, env)


def megabytes(path):
    """`du -sm`, which is what the READMEs' MB figures were measured with."""
    if not path.exists():
        raise Skip("%s is not here" % path.relative_to(REPO))
    out = subprocess.run(["du", "-sm", str(path)], check=True,
                         stdout=subprocess.PIPE, text=True).stdout
    return float(out.split()[0])


def chromium_dir():
    browsers = REPO / "demo" / ".toolchain" / "browsers"
    found = sorted(browsers.glob("chromium-*")) if browsers.is_dir() else []
    if not found:
        raise Skip("no demo/.toolchain/browsers/chromium-* — run `make demo` once")
    return found[0]


def collected_tests():
    python = REPO / ".venv" / "bin" / "python"
    argv = [str(python) if python.is_file() else sys.executable,
            "-m", "pytest", "--collect-only", "-q", "-o", "addopts=",
            "-p", "no:cacheprovider"]
    proc = subprocess.run(argv, cwd=str(REPO), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    found = re.search(r"^(\d+) tests? collected", proc.stdout, re.MULTILINE)
    if proc.returncode != 0 or found is None:
        raise Skip("`pytest --collect-only` gave no count (exit %d):\n%s"
                   % (proc.returncode, proc.stdout[-1500:]))
    return float(found.group(1))


MEASURE = {
    "tests": collected_tests,
    "test-warm": warm_suite,
    "run-dead": in_a_dead_clone("run"),
    "test-dead": in_a_dead_clone("test"),
    "demo-warm": warm_demo,
    "toolchain-size": lambda: megabytes(REPO / "demo" / ".toolchain"),
    "chromium-size": lambda: megabytes(chromium_dir()),
    "venv-size": lambda: megabytes(REPO / ".venv"),
}

# Rows measured once however many repeats are asked for, because repeating them
# measures nothing new: a disk size does not move between two `du` calls, and a
# collection count is the number this tool exists to contrast with the ones that
# do move.
MEASURED_ONCE = {"tests", "toolchain-size", "chromium-size", "venv-size"}


# --- the report -------------------------------------------------------------


def verdict(row, measured, found):
    """(label, note). `found` is [(line, chunk, figures)] for this row."""
    if not found:
        if row.key in CLAIMED_AT_BIRTH.get(REPO.name, set()):
            return "MISSING", ("README.md stated this on 2026-09-23 and now "
                               "matches nothing — reworded, or deleted without "
                               "dropping it from CLAIMED_AT_BIRTH")
        return "n/a", "README.md states no figure for this, and never did"
    figures = [f for _, _, chunk_figures in found for f in chunk_figures]
    if row.key not in CLAIMED_AT_BIRTH.get(REPO.name, set()):
        return "NEW", ("a figure nobody declared: add %r to this repo's entry "
                       "in CLAIMED_AT_BIRTH so it is re-measured on purpose"
                       % row.key)
    if row.exact:
        if all(f == measured for f in figures):
            return "ok", ""
        return "STALE", "README says %s, measured %s" % (
            "/".join(fmt(f) for f in sorted(set(figures))), fmt(measured))
    low, high = min(figures), max(figures)
    if low <= measured <= high:
        return "ok", "inside the %s-%s %s the README quotes" % (
            fmt(low), fmt(high), row.unit)
    return "REVIEW", "measured %s %s, outside the %s-%s %s quoted" % (
        fmt(measured), row.unit, fmt(low), fmt(high), row.unit)


def fmt(value):
    return "%d" % value if float(value).is_integer() else "%.1f" % value


def report_tree_state():
    def git(*args):
        return subprocess.run(["git", "-C", str(REPO)] + list(args),
                              stdout=subprocess.PIPE, text=True).stdout.strip()
    head = git("rev-parse", "--short", "HEAD")
    dirty = git("status", "--porcelain")
    print("  HEAD %s  %s" % (head, "dirty working tree" if dirty else "clean tree"))
    if dirty:
        print("  the dead-clone rows clone HEAD, so they do NOT measure the")
        print("  changes below. Commit first if they touch what you are timing.")
        for line in dirty.splitlines():
            print("    " + line)
    return dirty


def run_row(row, repeat):
    """(measured, samples) or raise Skip."""
    once = row.key in MEASURED_ONCE
    samples = [MEASURE[row.key]() for _ in range(1 if once else repeat)]
    if isinstance(samples[0], dict):  # test-split: a value per named file
        return samples[0], samples
    return statistics.median(samples), samples


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Re-measure the README numbers no test can guard.")
    parser.add_argument("--repeat", type=int, default=3,
                        help="samples per moving row (default 3)")
    parser.add_argument("--only", default="",
                        help="comma-separated row keys; default is all of them")
    parser.add_argument("--list", action="store_true",
                        help="print the rows and their cost, measure nothing")
    args = parser.parse_args(argv)

    if args.list:
        for row in ROWS:
            claimed = row.key in CLAIMED_AT_BIRTH.get(REPO.name, set())
            print("  %-15s %-38s %-32s %s" % (
                row.key, row.title, row.cost,
                "claimed here" if claimed else "not claimed here"))
        return 0

    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    wanted = [k.strip() for k in args.only.split(",") if k.strip()] or list(BY_KEY)
    unknown = [k for k in wanted if k not in BY_KEY]
    if unknown:
        parser.error("unknown row(s): %s. Known: %s"
                     % (", ".join(unknown), ", ".join(BY_KEY)))
    if REPO.name not in CLAIMED_AT_BIRTH:
        print("timings.py: %s is not in CLAIMED_AT_BIRTH, so a missing claim "
              "cannot be told from a reworded one here. Add it." % REPO.name,
              file=sys.stderr)
        return 2
    for tool in ("git", "make", "du"):
        if shutil.which(tool) is None:
            print("timings.py: needs `%s` on PATH" % tool, file=sys.stderr)
            return 2

    print("tools/timings.py — %s, %d repeat(s)" % (REPO.name, args.repeat))
    report_tree_state()
    print()

    text = README.read_text(encoding="utf-8")
    needs_a_human = []
    for row in (BY_KEY[k] for k in wanted):
        found = claims(row, text)
        try:
            measured, samples = run_row(row, args.repeat)
        except Skip as exc:
            print("%-15s skipped: %s" % (row.key, exc))
            print()
            continue
        if isinstance(measured, dict):
            print("%-15s %s" % (row.key, row.title))
            for name, value in measured.items():
                print("  %-34s %8s s" % (name, fmt(value)))
            label, note = verdict(row, max(measured.values()), found)
        else:
            spread = "" if len(samples) < 2 else "   (%s)" % ", ".join(
                "%.1f" % s for s in samples)
            print("%-15s %-38s %8s %s%s" % (
                row.key, row.title, fmt(measured), row.unit, spread))
            label, note = verdict(row, measured, found)
        for line, chunk, figures in found:
            print("  README.md:%-4d %s" % (line, shorten(chunk)))
            print("  %-14s figures: %s" % ("", ", ".join(fmt(f) for f in figures)))
        print("  -> %-8s %s" % (label, note))
        print()
        if label in ("REVIEW", "STALE", "MISSING", "NEW"):
            needs_a_human.append(row.key)

    if needs_a_human:
        print("%d row(s) need a human: %s" % (len(needs_a_human),
                                              ", ".join(needs_a_human)))
        print("Nothing here is asserted by the suite. Edit README.md — and "
              "re-measure every other figure in the sentence you touch, not "
              "just the one this flagged — then run it again.")
        return 1
    print("Every figure this can reach matches README.md.")
    return 0


def shorten(chunk, width=96):
    one_line = " ".join(chunk.split())
    return one_line if len(one_line) <= width else one_line[:width - 1] + "…"


if __name__ == "__main__":
    sys.exit(main())
