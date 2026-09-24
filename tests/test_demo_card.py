"""The title card at the head of every clip: demo/lib/card.py, and the files
`make demo` leaves behind.

This file is byte-identical in all four portfolio repos, the same way
test_demo_sheet.py is, because the thing it tests is byte-identical in all
four. It reads its own repo's demo/out/, so one file is all four. It is
declared in SHARED_ROOT in tools/demo_lib_drift.py — that arm is a list and not
a walk, so a new shared test beside this one is checked by nothing until its
path is added there.

--- what is actually being claimed, and what each arm can see ---------------

Frame 0 of every clip used to be a spreadsheet on pale paper, which at
thumbnail size is a blank white rectangle: Freelancer derives a video's poster
from frame 0 and the README embeds the .gif, so the portfolio led with four
white rectangles (THE-285). The card is 0.8s of dark frame in front of both
encodes plus the same render exported as demo/out/poster.png.

The gate is on that claim and on nothing else. Not output bytes and not
duration equality: unchanged code has re-recorded 46%, 53% and 8% larger, and
this card's own control measured a body-only re-encode of one recording at
+60% against the committed file with no card involved at all. A byte or
duration gate here would fail on honest re-records and would still not notice
a white frame 0 (THE-267, Rook's standing rule).

  * the PNG and GIF arms are **stdlib**, so they run in a dead clone with no
    toolchain — which is where the suite is most often run, and the GIF is the
    file the README embeds, so it is the one a portfolio reader really sees.
    The GIF frame reader below is a small LZW decoder for that reason: it
    costs thirty lines and it buys the guard on the delivered file being real
    in the clone that has built nothing.
  * the MP4 frame arm needs ffmpeg, which arrives with demo/.toolchain/, so it
    **skips** in a dead clone. It is a cross-check on the encoder, not the
    guard: what makes the card's length a fact about the mp4 is that one
    constant in demo/lib/playwright.sh drives both encodes, and the GIF arm
    measures it end to end.
  * the font arm needs the vendored Chromium and the vendored face, so it
    skips too. It is the only arm that can see the reproducibility property,
    so when it runs it runs both ways — see test_the_card_font_is_jailed.
"""

from __future__ import annotations

import importlib.util
import os
import re
import struct
import sys
import subprocess
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "demo" / "lib"
OUT = REPO / "demo" / "out"
POSTER = OUT / "poster.png"
GIF = OUT / "demo.gif"
MP4 = OUT / "demo.mp4"
PLAYWRIGHT_SH = LIB / "playwright.sh"
FONTS_SH = LIB / "fonts.sh"

# A frame of the card against a frame of a spreadsheet. Measured on this
# repo's own outputs at the commit that introduced the card: the card lands
# near 92-95 and a paper frame near 221, so the line sits in the middle of a
# gap of more than a hundred rather than just above one of the two.
DARK_MAX = 150.0
PALE_MIN = 170.0


def _load_card():
    spec = importlib.util.spec_from_file_location("demo_card", LIB / "card.py")
    module = importlib.util.module_from_spec(spec)
    # Registered before it executes, the same way test_demo_sheet.py does it:
    # @dataclass looks its own module up in sys.modules while the class body is
    # still being built, and a module that is not there yet makes that lookup
    # fail with an unrelated AttributeError at import time.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


card = _load_card()


# --------------------------------------------------------------------------
# stdlib readers
# --------------------------------------------------------------------------


def read_png(path: Path) -> tuple[int, int, list[tuple[int, int, int]]]:
    """A PNG as (width, height, RGB pixels). Truecolour, 8-bit, no interlace.

    Which is what Chromium screenshots and ffmpeg both write here; anything
    else raises rather than being guessed at, because a reader that quietly
    mis-decodes produces a luma number that looks like an answer.
    """
    blob = path.read_bytes()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    pos, idat, width, height, depth, colour = 8, bytearray(), 0, 0, 0, 0
    while pos < len(blob):
        length = struct.unpack(">I", blob[pos:pos + 4])[0]
        kind, data = blob[pos + 4:pos + 8], blob[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", data[:10])
            if data[12] != 0:
                raise ValueError(f"{path} is interlaced")
        elif kind == b"IDAT":
            idat += data
        pos += 12 + length
    if depth != 8 or colour not in (2, 6):
        raise ValueError(f"{path}: expected 8-bit truecolour, got depth={depth} "
                         f"colour-type={colour}")
    channels = 3 if colour == 2 else 4
    stride = width * channels
    raw, out, previous, at = zlib.decompress(bytes(idat)), bytearray(), bytearray(stride), 0
    for _ in range(height):
        filter_type, at = raw[at], at + 1
        line, at = bytearray(raw[at:at + stride]), at + stride
        for x in range(stride):
            left = line[x - channels] if x >= channels else 0
            up = previous[x]
            upleft = previous[x - channels] if x >= channels else 0
            if filter_type == 1:
                line[x] = (line[x] + left) & 255
            elif filter_type == 2:
                line[x] = (line[x] + up) & 255
            elif filter_type == 3:
                line[x] = (line[x] + (left + up) // 2) & 255
            elif filter_type == 4:
                guess = left + up - upleft
                da, db, dc = abs(guess - left), abs(guess - up), abs(guess - upleft)
                best = left if (da <= db and da <= dc) else (up if db <= dc else upleft)
                line[x] = (line[x] + best) & 255
        out += line
        previous = line
    pixels = [(out[o], out[o + 1], out[o + 2])
              for o in range(0, len(out), channels)]
    return width, height, pixels


def _lzw(data: bytes, min_code_size: int) -> bytes:
    """GIF's variable-width LZW, enough to decode one image's index stream."""
    clear, end = 1 << min_code_size, (1 << min_code_size) + 1
    code_size = min_code_size + 1
    table = {i: bytes([i]) for i in range(clear)}
    nxt, previous, out, bit = end + 1, None, bytearray(), 0
    limit = len(data) * 8
    while bit + code_size <= limit:
        byte = bit >> 3
        window = int.from_bytes(data[byte:byte + 3].ljust(3, b"\0"), "little")
        code = (window >> (bit & 7)) & ((1 << code_size) - 1)
        bit += code_size
        if code == clear:
            table = {i: bytes([i]) for i in range(clear)}
            nxt, code_size, previous = end + 1, min_code_size + 1, None
            continue
        if code == end:
            break
        entry = table[code] if code in table else previous + previous[:1]
        out += entry
        if previous is not None and nxt < 4096:
            table[nxt] = previous + entry[:1]
            nxt += 1
            if nxt == (1 << code_size) and code_size < 12:
                code_size += 1
        previous = entry
    return bytes(out)


def read_gif(path: Path) -> tuple[int, int, list[dict]]:
    """A GIF as (width, height, frames), parsed but not decoded.

    Each frame carries its delay, its box on the canvas, and everything
    `frame_pixels` needs to turn it into colours. Decoding is deferred because
    it is the expensive half and this file wants two frames out of a hundred
    and fifteen — a decode-everything reader would spend a minute of pure
    Python rebuilding pictures nothing looks at.

    Enough of the format to answer the questions the README's own image raises:
    how long the head of the clip holds, and what is on screen while it does.
    """
    blob = path.read_bytes()
    if blob[:6] not in (b"GIF89a", b"GIF87a"):
        raise ValueError(f"{path} is not a GIF")
    width, height, packed = struct.unpack("<HHB", blob[6:11])
    pos = 13
    palette: list[tuple[int, int, int]] = []
    if packed & 0x80:
        size = 2 << (packed & 7)
        palette = [tuple(blob[pos + 3 * i:pos + 3 * i + 3]) for i in range(size)]
        pos += 3 * size

    def skip_sub_blocks(at: int) -> tuple[bytes, int]:
        chunks = bytearray()
        while blob[at]:
            chunks += blob[at + 1:at + 1 + blob[at]]
            at += 1 + blob[at]
        return bytes(chunks), at + 1

    frames: list[dict] = []
    delay, transparent = 0.0, None
    while pos < len(blob):
        marker = blob[pos]
        if marker == 0x3B:                                   # trailer
            break
        if marker == 0x21:                                   # extension
            if blob[pos + 1] == 0xF9:                        # graphic control
                packed_gce = blob[pos + 3]
                delay = struct.unpack("<H", blob[pos + 4:pos + 6])[0] / 100.0
                transparent = blob[pos + 6] if packed_gce & 1 else None
            _, pos = skip_sub_blocks(pos + 2)
            continue
        if marker != 0x2C:
            raise ValueError(f"{path}: unexpected block 0x{marker:02x} at {pos}")
        left, top, fw, fh, local = struct.unpack("<HHHHB", blob[pos + 1:pos + 10])
        pos += 10
        colours = palette
        if local & 0x80:
            size = 2 << (local & 7)
            colours = [tuple(blob[pos + 3 * i:pos + 3 * i + 3]) for i in range(size)]
            pos += 3 * size
        if local & 0x40:
            raise ValueError(f"{path}: frame {len(frames)} is interlaced")
        min_code_size, pos = blob[pos], pos + 1
        data, pos = skip_sub_blocks(pos)
        frames.append({
            "delay_s": delay, "box": (left, top, fw, fh),
            "coverage": (fw * fh) / (width * height),
            "_data": data, "_min_code_size": min_code_size,
            "_colours": colours, "_transparent": transparent,
        })
    return width, height, frames


def frame_pixels(frame: dict) -> list[tuple[int, int, int]]:
    """One frame's own pixels: its sub-image, with transparent ones dropped.

    Not the composited canvas. A GIF frame after the first repaints only part
    of the picture and leaves the rest showing through, so rebuilding the
    canvas means replaying every frame from the start. What a repainted region
    holds is a real observation about the clip without any of that — the
    caller picks a frame whose region is most of the screen.
    """
    indexes = _lzw(frame["_data"], frame["_min_code_size"])
    _, _, fw, fh = frame["box"]
    colours, hidden = frame["_colours"], frame["_transparent"]
    return [colours[i] for i in indexes[:fw * fh] if i != hidden]


def luma(pixels) -> float:
    total = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels)
    return total / len(pixels)


def card_seconds() -> float:
    """CARD_SECONDS out of playwright.sh, so the test cannot drift from it."""
    found = re.search(r'^CARD_SECONDS="\$\{CARD_SECONDS:-([0-9.]+)\}"',
                      PLAYWRIGHT_SH.read_text(), re.M)
    assert found, "playwright.sh no longer defines CARD_SECONDS the way this reads it"
    return float(found.group(1))


def have_toolchain() -> str | None:
    binary = REPO / "demo" / ".toolchain" / "bin" / "ffmpeg"
    return str(binary) if binary.is_file() else None


# --------------------------------------------------------------------------
# the card as HTML: no browser, no files
# --------------------------------------------------------------------------


def panels() -> tuple[card.Panel, card.Panel]:
    dot = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea735a9c400"
        "00000049454e44ae426082"
    )
    return (card.Panel("before", "Messy supplier feed", "318 rows | 21 columns", dot),
            card.Panel("after", "Clean .xlsx", "every change logged", dot))


def test_both_captions_and_both_colours_are_in_the_card() -> None:
    left, right = panels()
    html = card.card_html(left, right, width=1280, height=720)
    for text in (left.label, left.detail, right.label, right.detail):
        assert text in html
    assert card.LABEL_BEFORE in html and card.LABEL_AFTER in html, (
        "the two halves must be told apart by colour: white before, green after"
    )


def test_the_panels_are_the_screenshots_handed_in() -> None:
    """Not a path, not a file read at draw time: the bytes the scene captured.

    The card's whole claim is that it is composed from the run's own frames. An
    <img src> pointing at a file would let the card and the clip come from two
    different runs without anything noticing.
    """
    left, right = panels()
    html = card.card_html(left, right, width=1280, height=720)
    assert html.count("data:image/png;base64,") == 2
    assert "src=\"/" not in html and "file://" not in html


def test_a_caption_cannot_inject_markup() -> None:
    nasty = '</style><script>alert(1)</script>'
    left, right = panels()
    html = card.card_html(
        card.Panel(left.tone, nasty, left.detail, left.png), right,
        width=1280, height=720,
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_both_halves_are_asked_to_auto_size() -> None:
    """Every label and every detail carries its own fit bounds.

    The fitting itself happens in the page — only the browser knows how wide a
    string is — so what is checkable here is that nothing was left out of the
    instruction, which is the way it would silently stop being auto-sized.
    """
    left, right = panels()
    html = card.card_html(left, right, width=1280, height=720)
    assert html.count("data-fit=") == 4
    assert f'data-fit="{card.LABEL_MAX},{card.LABEL_MIN}"' in html
    assert f'data-fit="{card.DETAIL_MAX},{card.DETAIL_MIN}"' in html
    assert "scrollWidth" in card._FIT_JS and "clientWidth" in card._FIT_JS

    # And the bounds are a fraction of the frame, not four constants that only
    # mean anything at one capture size.
    half_size = card.card_html(left, right, width=640, height=360)
    assert f'data-fit="{card.LABEL_MAX // 2},{card.LABEL_MIN // 2}"' in half_size


def test_the_card_refuses_to_draw_without_the_pinned_font(monkeypatch) -> None:
    """The reproducibility hole, closed loudly rather than by falling back.

    Drawing with whatever fontconfig returns would work on the box that
    recorded it and produce a different card everywhere else — the label is
    auto-sized, so the face's metrics decide the layout. A silent fallback is
    exactly the failure that cannot be seen from here.
    """
    monkeypatch.delenv("CARD_FONTCONFIG_FILE", raising=False)
    with pytest.raises(SystemExit) as raised:
        card._browser_env()
    assert "CARD_FONTCONFIG_FILE" in str(raised.value)


def test_fonts_sh_pins_a_version_and_a_checksum() -> None:
    text = FONTS_SH.read_text()
    assert re.search(r'^DEJAVU_SHA256="[0-9a-f]{64}"$', text, re.M), (
        "the pin is the checksum; a URL alone is not one"
    )
    assert "<dir>$dir</dir>" in text
    # Comment lines are excluded on purpose: the reason there must be no
    # <include> is written out in fonts.sh, and a check that cannot tell the
    # explanation from the thing it explains would have to be deleted the
    # moment anyone documented it.
    live = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in live if "<include" in line], (
        "the fontconfig must declare our directory and pull in no system "
        "config: an included /etc/fonts/conf.d adds the system directories "
        "back and the isolation goes quiet rather than failing"
    )


# --------------------------------------------------------------------------
# what `make demo` left behind
# --------------------------------------------------------------------------


def test_the_poster_is_committed_beside_the_clip() -> None:
    assert POSTER.is_file(), "demo/out/poster.png is missing"
    assert POSTER.stat().st_size > 0


def test_the_poster_is_the_capture_size_and_is_dark() -> None:
    width, height, pixels = read_png(POSTER)
    assert (width, height) == (1280, 720), (
        "the poster is the mp4's frame 0, so it is the capture size"
    )
    assert luma(pixels) < DARK_MAX, (
        f"the poster reads at {luma(pixels):.0f} luma — a pale poster is the "
        "blank-white-thumbnail defect this card was opened for"
    )


def test_the_poster_carries_the_green_after_label() -> None:
    """Both halves are labelled, and they are told apart by colour.

    Reading it off the rendered pixels rather than off the HTML is the point:
    this is the arm that would catch a card whose text did not render — the
    tofu case a font change produces, where the markup is perfect and the
    frame is empty.
    """
    _, _, pixels = read_png(POSTER)
    green = sum(1 for r, g, b in pixels if g > 150 and r < 140 and b < 180)
    white = sum(1 for r, g, b in pixels if r > 200 and g > 200 and b > 200)
    assert green > 500, f"only {green} green label pixels in the poster"
    assert white > 500, f"only {white} white label pixels in the poster"


def test_the_gif_opens_on_the_card_and_the_body_is_still_the_demo() -> None:
    """The file the README embeds, read end to end without a toolchain.

    The GIF is the one a portfolio reader really sees — the README embeds it,
    not the mp4 — so this arm is stdlib on purpose and runs in a dead clone.

    The second half is what stops the first passing vacuously: "frame 0 is
    dark" is also true of a clip that is dark the whole way through, which
    would be a broken recording that read as a fixed one. It looks at a late
    frame that repaints most of the screen rather than at the composited
    canvas — see frame_pixels.
    """
    width, height, frames = read_gif(GIF)
    assert (width, height) == (1000, 562)
    first = luma(frame_pixels(frames[0]))
    assert first < DARK_MAX, f"the GIF opens at {first:.0f} luma, not on the card"

    # Chosen by how many pixels a frame really repaints, not by how big its
    # box is. Those are different numbers and the difference is the whole
    # point of inter-frame transparency: catalog-watch's last frame declares a
    # box covering 97% of the screen and paints 1,336 pixels inside it, all of
    # them dark UI text, which read as a dark clip and failed this.
    #
    # The cheap box figure still prefilters, so the expensive decode runs on
    # two or three frames rather than sixty.
    painted = int(0.2 * width * height)
    body = None
    for frame in reversed([f for f in frames[len(frames) // 2:]
                           if f["coverage"] >= 0.5]):
        pixels = frame_pixels(frame)
        if len(pixels) >= painted:
            body = luma(pixels)
            break
    assert body is not None, (
        f"no frame in the second half of the GIF repaints {painted:,} pixels, "
        "so there is nothing here to read the body off"
    )
    assert body > PALE_MIN, (
        f"the last big repaint in the GIF is {body:.0f} luma — the clip is "
        "meant to spend its body on a spreadsheet, and one that stayed dark "
        "throughout would pass the frame-0 half above without being a "
        "recording at all"
    )


def test_the_gif_holds_the_card_for_about_card_seconds() -> None:
    """Measured end to end off the delivered file, not read out of the source.

    A tolerant band, never equality: CARD_SECONDS x GIF_FPS is rarely a whole
    number and GIF delays are stored in hundredths, so the head of the clip
    lands on a frame boundary either side of 0.8s.
    """
    _, _, frames = read_gif(GIF)
    want = card_seconds()
    held, index = 0.0, 0
    # The leading run of frames is the card; the first frame of the body is
    # where the delay accounting stops. One GIF frame at GIF_FPS=6 is 0.17s,
    # so the run can be one frame short or long of the nominal hold.
    while index < len(frames) and held < want - 1e-9:
        held += frames[index]["delay_s"]
        index += 1
    assert abs(held - want) <= 0.25, (
        f"the GIF's opening hold is {held:.2f}s against CARD_SECONDS={want}"
    )


def test_the_mp4_frame_zero_is_the_poster() -> None:
    """The cross-check the stdlib arms cannot do: H.264 needs a decoder.

    Not byte equality — the mp4 is lossy at crf 26, so frame 0 is the poster
    plus quantisation noise. A mean absolute difference per channel is what
    separates "the same picture, re-encoded" from "a different frame".
    """
    binary = have_toolchain()
    if binary is None:
        pytest.skip("frame 0 of the mp4 needs ffmpeg from demo/.toolchain/")
    shot = subprocess.run(
        [binary, "-v", "error", "-y", "-i", str(MP4), "-frames:v", "1",
         "-f", "image2", "-c:v", "png", "/dev/stdout"],
        capture_output=True, check=True,
    )
    frame = Path(os.environ.get("PYTEST_TMP", "/tmp")) / f"mp4f0-{os.getpid()}.png"
    frame.write_bytes(shot.stdout)
    try:
        fw, fh, frame_px = read_png(frame)
        pw, ph, poster_px = read_png(POSTER)
        assert (fw, fh) == (pw, ph), "frame 0 and the poster are different sizes"
        diff = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
                   for a, b in zip(frame_px, poster_px)) / (3 * len(poster_px))
        assert diff < 8.0, (
            f"frame 0 of the mp4 differs from poster.png by {diff:.1f} per "
            "channel — they are meant to be one render"
        )
    finally:
        frame.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# the font proof
# --------------------------------------------------------------------------


def test_the_card_font_is_jailed() -> None:
    """Both arms, because only the pair proves anything.

    Jailed, the three probe families — two real, one that exists nowhere —
    resolve to the single vendored face and measure the same width. Unjailed,
    they resolve to three different things. A test that only ran the jailed arm
    would also pass on a box with no fonts installed at all, where every family
    is equally unavailable, which is the opposite of the property wanted.
    """
    if have_toolchain() is None or not os.environ.get("CARD_FONTCONFIG_FILE"):
        # This arm does not run under a plain `make test`, and that is its own
        # hazard: the suite goes green with the one check that can see the
        # reproducibility property sitting dormant, which on the summary line
        # is indistinguishable from a check that ran (THE-285).
        #
        # It needs three things the recipe exports and a bare pytest does not:
        # CARD_FONTCONFIG_FILE, PLAYWRIGHT_BROWSERS_PATH, and an LD_LIBRARY_PATH
        # holding the vendored Chromium's own .so files. Setting only the first
        # gets "Executable doesn't exist at ~/.cache/ms-playwright/..."; setting
        # the first two gets "libnss3.so: cannot open shared object file". The
        # old message here said to source fonts.sh and call ensure_card_font,
        # which is the first of the three and therefore does not work -- it was
        # written from reading fonts.sh rather than from running it.
        #
        # Rebuilding all three in Python would be a second copy of demo/lib/*.sh
        # that can drift from the one the recording really uses, so this names
        # the shell that already builds the environment instead:
        #
        #   cd demo && DEMO_DIR=$PWD TOOLCHAIN_DIR=$PWD/.toolchain \
        #     REPO_ROOT=$PWD/.. bash -c '. lib/playwright.sh; ensure_card_font
        #     vendor_chromium_libs "$(find_playwright_chromium)"
        #     cd "$REPO_ROOT"; .venv/bin/python -m pytest \
        #     tests/test_demo_card.py -k jailed'
        pytest.skip(
            "needs the vendored Chromium and the vendored face, which only "
            "demo/lib/playwright.sh exports -- sourcing fonts.sh alone is NOT "
            "enough. Run ./demo/record.sh, or the command in the comment above "
            "this skip. A green `make test` has not proved the font is jailed."
        )
    jailed = list(card.font_probe(jailed=True).values())
    assert len(set(jailed)) == 1, (
        f"the probe families measured {jailed} under the vendored fontconfig; "
        "one face means one width, so something else is still reachable"
    )
    assert jailed[0] > 0, "the jailed render measured nothing at all"

    loose = list(card.font_probe(jailed=False).values())
    assert len(set(loose)) > 1, (
        f"the control measured {loose}: this box has no distinguishable system "
        "fonts, so the jailed arm above proves nothing here"
    )
