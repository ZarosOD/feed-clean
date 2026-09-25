"""The README's clip-length claim, read back off the committed clip.

This file is byte-identical in all four portfolio repos, the same way
test_demo_fetch.py and test_demo_sheet.py are, because what it checks is the
same sentence in four READMEs. It imports nothing from the piece it runs
inside.

Why it exists: for twelve days inbox-filer's README said the clip was 21 s
when the committed `demo/out/demo.mp4` was 17.88 s, and nothing could see it,
because no test in any of the four repos opened README.md. `record.sh` does
guard the clip against the 35 s budget, by reading the encoded file — that is a
real guard, and it is a guard on the *file*. Nothing guarded the number the
README *claims* about that same file, so every figure in the four READMEs was
protected by a human remembering to re-measure it. That failed once (THE-263).

Scope, said out loud. This guards the clip length and the budget it is quoted
against. It deliberately does not guard the wall-clock timings or the toolchain
sizes in the same READMEs: those are machine-dependent, and asserting them here
would buy a flaky suite rather than a guard. The intended shape for those is a
by-hand re-measure target, not a test.

Why not ffprobe. The obvious reader is `ffprobe`, which is what `record.sh`
uses. But ffprobe arrives with `demo/.toolchain/`, which `make demo` downloads
and a dead clone does not have — so an ffprobe-based check would skip in the
one place this suite is most often run from, and a skipped guard scores as a
pass. The two readers below are stdlib and parse the containers directly. They
were checked against `ffprobe -show_entries format=duration` on all eight
committed clips (four gif, four mp4) at the commit that added this file, and
agreed to the last digit on every one; `test_the_readers_agree_with_ffprobe`
re-runs that cross-check whenever a toolchain happens to be present.

The maintainers' drift checker holds the four copies of this file identical,
from its SHARED_ROOT list (THE-274). It is a rookery tool and is not in this
repo, so there is nothing here to run. Unlike the demo/ half of that tool,
SHARED_ROOT is declared rather than discovered, so a new shared file beside
this one stays checked by nothing until somebody adds its path to it.
"""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
RECORD_SH = REPO / "demo" / "record.sh"
ENCODES = (REPO / "demo" / "out" / "demo.gif", REPO / "demo" / "out" / "demo.mp4")

# The sentence every one of the four READMEs carries, in the "Recording the
# demo" section. Kept narrow on purpose: it has to be unambiguous, and a
# reword that this stops matching fails loudly (test_the_readme_makes_exactly_
# one_clip_length_claim) rather than going quiet.
CLAIM = re.compile(r"[Tt]he clip is (\d+(?:\.\d+)?) s against a (\d+(?:\.\d+)?) s budget")

# demo/record.sh:  MAX_SECONDS="${MAX_SECONDS:-35}"
BUDGET_DEFAULT = re.compile(r'MAX_SECONDS="\$\{MAX_SECONDS:-(\d+)\}"')

# How far the README's number may sit from the file's, and where each half of
# it comes from. Do not widen either without a measurement to hang it on.
#
#   0.5   the claim's own precision. The READMEs write whole seconds ("18 s"),
#         so an honest claim is the duration rounded, and rounding alone moves
#         it by up to half a second.
#
#   0.2   re-record jitter, measured 2026-09-23 on this encoder: seven
#         recordings across catalog-watch, feed-clean and pdf-to-csv, each from
#         an unchanged commit with its output sent to a scratch directory, and
#         both encodes of each compared against the committed pair. Fourteen
#         comparisons; the largest move was 0.17 s (catalog-watch gif, 21.00 s
#         committed -> 21.17 s re-recorded), and the mp4 of the same piece
#         moved 0.16 s. catalog-watch/demo/README.md:271 records an eighth,
#         earlier sample at 0.04 s. Rounded up to 0.2 and no further. Not
#         sampled: inbox-filer, which has no toolchain on this machine — the
#         jitter is a property of the shared capture-and-encode pipeline, not
#         of a piece, but say that it is three pieces and not four. This half is
#         here because a duration sitting within jitter of a .5 boundary could
#         have rounded either way on the day the number was written, and the
#         README should not have to change when the encoder wobbles across it.
#
# 0.7 is loose enough that no honest claim fails and far too tight to have let
# the defect through: the claim this was written for was out by 3.12 s.
CLAIM_PRECISION_SECONDS = 0.5
RERECORD_JITTER_SECONDS = 0.2
TOLERANCE_SECONDS = CLAIM_PRECISION_SECONDS + RERECORD_JITTER_SECONDS


def mp4_duration(data: bytes) -> float:
    """Seconds, off the `mvhd` box: the movie header's duration / timescale.

    Walks the top-level box list and descends into `moov` only, so it finds
    the header whether the file is written `moov`-first or `mdat`-first. Every
    way of not finding a duration raises — a reader that answers 0.0 for a
    truncated file would turn this whole test file into one that passes on
    rubble.
    """
    def walk(start: int, end: int) -> tuple[int, int] | None:
        pos = start
        while pos + 8 <= end:
            size = struct.unpack_from(">I", data, pos)[0]
            kind = data[pos + 4 : pos + 8]
            head = 8
            if size == 1:  # 64-bit size, in the eight bytes after the type
                size = struct.unpack_from(">Q", data, pos + 8)[0]
                head = 16
            elif size == 0:  # "to the end of the file"
                size = end - pos
            if size < head or pos + size > end:
                raise ValueError(f"truncated {kind!r} box at offset {pos}")
            if kind == b"mvhd":
                version = data[pos + head]
                body = pos + head + 4  # past version(1) + flags(3)
                if version == 1:
                    # creation(8) modification(8) timescale(4) duration(8)
                    return struct.unpack_from(">IQ", data, body + 16)
                # creation(4) modification(4) timescale(4) duration(4)
                return struct.unpack_from(">II", data, body + 8)
            if kind == b"moov":
                found = walk(pos + head, pos + size)
                if found is not None:
                    return found
            pos += size
        return None

    found = walk(0, len(data))
    if found is None:
        raise ValueError("no mvhd box: this is not an mp4 with a movie header")
    timescale, duration = found
    if timescale == 0:
        raise ValueError("mvhd timescale is zero")
    return duration / timescale


def gif_duration(data: bytes) -> float:
    """Seconds, summed off every frame's Graphic Control Extension delay.

    Delays are in hundredths of a second, which is what ffprobe reports too.
    They are also the one place this can disagree with what a browser plays:
    browsers substitute 100 ms for a declared delay under 20 ms. These clips
    are encoded at GIF_FPS=6, so every frame declares 16 or 17, well clear of
    that floor — `test_no_frame_declares_a_delay_a_browser_would_override`
    keeps it that way.
    """
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ValueError("not a GIF: bad signature")
    return sum(_gif_frame_delays(data)) / 100.0


def _gif_frame_delays(data: bytes) -> list[int]:
    """Every Graphic Control Extension delay, in hundredths of a second."""
    pos = 6
    flags = data[10]
    pos = 13
    if flags & 0x80:  # global colour table
        pos += 3 * (2 ** ((flags & 0x07) + 1))

    def skip_sub_blocks(at: int) -> int:
        while True:
            length = data[at]
            at += 1
            if length == 0:
                return at
            at += length

    delays: list[int] = []
    while pos < len(data):
        block = data[pos]
        if block == 0x3B:  # trailer
            break
        if block == 0x21:  # extension
            label = data[pos + 1]
            pos += 2
            if label == 0xF9:  # graphic control
                size = data[pos]
                delays.append(struct.unpack_from("<H", data, pos + 2)[0])
                if size != 4:
                    raise ValueError(f"odd graphic control block size {size}")
            pos = skip_sub_blocks(pos)
        elif block == 0x2C:  # image descriptor
            local = data[pos + 9]
            pos += 10
            if local & 0x80:  # local colour table
                pos += 3 * (2 ** ((local & 0x07) + 1))
            pos += 1  # LZW minimum code size
            pos = skip_sub_blocks(pos)
        else:
            raise ValueError(f"unknown GIF block 0x{block:02x} at offset {pos}")
    if not delays:
        raise ValueError("no frames with a declared delay")
    return delays


def duration(path: Path) -> float:
    data = path.read_bytes()
    return mp4_duration(data) if path.suffix == ".mp4" else gif_duration(data)


def parse_claim(text: str) -> tuple[float, float]:
    """(clip seconds, budget seconds) from the one sentence that states them.

    Anything other than exactly one match raises. Zero means the sentence was
    reworded or dropped and this file is now guarding nothing; more than one
    means the README states it twice and a reader cannot tell which is the
    live number.
    """
    found = CLAIM.findall(text)
    if len(found) != 1:
        raise ValueError(
            f"README.md must state the clip length exactly once in the form "
            f"'The clip is N s against a M s budget'; found {len(found)}"
        )
    clip, budget = found[0]
    return float(clip), float(budget)


# --- the guard itself -------------------------------------------------------


def test_the_readme_makes_exactly_one_clip_length_claim() -> None:
    clip, budget = parse_claim(README.read_text(encoding="utf-8"))
    assert clip > 0
    assert budget > 0


@pytest.mark.parametrize("path", ENCODES, ids=lambda p: p.name)
def test_the_claimed_clip_length_matches_the_committed_encode(path: Path) -> None:
    """Both encodes, not just the mp4.

    The README embeds `demo/out/demo.gif` — that is the file a client actually
    watches — while the mp4 is what gets attached to a proposal. They are two
    encodes of one capture and their durations are close but not equal (up to
    0.08 s apart across the four pieces), so "the clip is N s" is a claim about
    both and is checked against both.
    """
    assert path.is_file(), f"{path.name} is committed and must be on disk"
    claimed, _ = parse_claim(README.read_text(encoding="utf-8"))
    actual = duration(path)
    assert abs(claimed - actual) <= TOLERANCE_SECONDS, (
        f"README says the clip is {claimed:g} s; {path.name} is {actual:.2f} s. "
        f"Re-measure the sentence in README.md, do not widen the tolerance."
    )


def test_the_claimed_budget_is_the_one_record_sh_enforces() -> None:
    """The same sentence names 35 s as a budget `record.sh` enforces. It can
    drift from record.sh exactly the way the clip length drifted from the
    clip, and it is the half of the sentence that makes the number mean
    anything."""
    _, claimed = parse_claim(README.read_text(encoding="utf-8"))
    found = BUDGET_DEFAULT.findall(RECORD_SH.read_text(encoding="utf-8"))
    assert len(found) == 1, "demo/record.sh must set MAX_SECONDS exactly once"
    assert claimed == float(found[0])


@pytest.mark.parametrize("path", ENCODES, ids=lambda p: p.name)
def test_the_committed_encode_is_inside_the_budget(path: Path) -> None:
    """record.sh checks this at record time, on the recipe's own clip, which
    is the gif. What shipped is both files, and this is the check on what
    shipped."""
    _, budget = parse_claim(README.read_text(encoding="utf-8"))
    assert duration(path) <= budget


def test_no_frame_declares_a_delay_a_browser_would_override() -> None:
    gif = REPO / "demo" / "out" / "demo.gif"
    delays = _gif_frame_delays(gif.read_bytes())
    assert min(delays) >= 2, (
        "a frame declares under 20 ms, so browsers will play the gif slower "
        "than gif_duration() and ffprobe both say it is"
    )


# --- the parse and the readers, proved without touching the real files ------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "The clip is short.",
        "The clip is 18 seconds against a 35 second budget.",  # reworded
        "the clip is 18s against a 35s budget",  # no space before the unit
    ],
)
def test_parse_claim_refuses_a_readme_that_does_not_state_it(text: str) -> None:
    with pytest.raises(ValueError, match="exactly once"):
        parse_claim(text)


def test_parse_claim_refuses_two_claims() -> None:
    text = "The clip is 18 s against a 35 s budget. The clip is 21 s against a 35 s budget."
    with pytest.raises(ValueError, match="exactly once"):
        parse_claim(text)


def test_parse_claim_reads_both_numbers() -> None:
    assert parse_claim("x The clip is 18 s against a 35 s budget, so y") == (18.0, 35.0)
    assert parse_claim("The clip is 17.9 s against a 35 s budget") == (17.9, 35.0)


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _mvhd(version: int, timescale: int, duration_units: int) -> bytes:
    if version == 1:
        body = struct.pack(">BBBB", 1, 0, 0, 0) + b"\0" * 16
        body += struct.pack(">IQ", timescale, duration_units)
    else:
        body = struct.pack(">BBBB", 0, 0, 0, 0) + b"\0" * 8
        body += struct.pack(">II", timescale, duration_units)
    return _box(b"mvhd", body)


@pytest.mark.parametrize("version", [0, 1])
def test_mp4_duration_reads_a_hand_built_header(version: int) -> None:
    data = _box(b"ftyp", b"isom" + b"\0" * 8) + _box(b"moov", _mvhd(version, 1000, 17880))
    assert mp4_duration(data) == pytest.approx(17.88)


def test_mp4_duration_finds_mvhd_after_the_media_data() -> None:
    """ffmpeg writes `moov` last unless told to move it, so a reader that only
    looks at the front of the file reads nothing."""
    data = _box(b"mdat", b"\0" * 64) + _box(b"moov", _mvhd(0, 600, 12624))
    assert mp4_duration(data) == pytest.approx(21.04)


def test_mp4_duration_refuses_a_file_with_no_movie_header() -> None:
    with pytest.raises(ValueError, match="no mvhd"):
        mp4_duration(_box(b"ftyp", b"isom") + _box(b"mdat", b"\0" * 16))


def test_mp4_duration_refuses_a_truncated_box() -> None:
    data = _box(b"moov", _mvhd(0, 1000, 17880))
    with pytest.raises(ValueError, match="truncated"):
        mp4_duration(data[:-20])


def test_mp4_duration_refuses_a_zero_timescale() -> None:
    with pytest.raises(ValueError, match="timescale is zero"):
        mp4_duration(_box(b"moov", _mvhd(0, 0, 17880)))


def _gif(delays: list[int]) -> bytes:
    out = b"GIF89a" + struct.pack("<HHBBB", 4, 4, 0x00, 0, 0)
    for delay in delays:
        # 0x21 0xF9, body size 4, then flags/delay/transparent-index, then the
        # sub-block terminator.
        out += b"\x21\xf9\x04" + struct.pack("<BHB", 0, delay, 0) + b"\x00"
        out += b"\x2c" + struct.pack("<HHHHB", 0, 0, 4, 4, 0x00)
        out += b"\x02\x01\x00\x00"  # LZW min code size, one sub-block, terminator
    return out + b"\x3b"


def test_gif_duration_sums_the_frame_delays() -> None:
    assert gif_duration(_gif([17, 17, 16])) == pytest.approx(0.50)
    assert gif_duration(_gif([17] * 72 + [16] * 35)) == pytest.approx(17.84)


def test_gif_duration_reads_past_a_global_colour_table() -> None:
    body = _gif([17, 17])
    with_table = b"GIF89a" + struct.pack("<HHBBB", 4, 4, 0x80, 0, 0) + b"\0" * 6 + body[13:]
    assert gif_duration(with_table) == pytest.approx(0.34)


def test_gif_duration_refuses_a_file_that_is_not_a_gif() -> None:
    with pytest.raises(ValueError, match="bad signature"):
        gif_duration(b"\x00\x00\x00\x20ftypisom")


def test_gif_duration_refuses_a_gif_with_no_declared_delays() -> None:
    with pytest.raises(ValueError, match="no frames"):
        gif_duration(_gif([]))


# --- the cross-check, when a toolchain happens to be here -------------------


@pytest.mark.parametrize("path", ENCODES, ids=lambda p: p.name)
def test_the_readers_agree_with_ffprobe(path: Path) -> None:
    """A cross-check, not the guard. It needs `demo/.toolchain/`, which only a
    `make demo` puts here, so it skips in a dead clone — which is why the
    readers above are also pinned against hand-built headers that never skip.
    Run at the commit that added this file, with the toolchain present: all
    eight clips agreed to the last digit."""
    ffprobe = REPO / "demo" / ".toolchain" / "bin" / "ffprobe"
    if not ffprobe.is_file():
        found = shutil.which("ffprobe")
        if found is None:
            pytest.skip("no ffprobe: this is the cross-check, not the guard")
        ffprobe = Path(found)
    reported = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert duration(path) == pytest.approx(float(reported), abs=0.005)
