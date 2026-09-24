#!/usr/bin/env python3
"""The title card every clip opens on, built out of the run's own frames.

Shared by all four portfolio pieces and byte-identical in each — the per-piece
half is the two captions, which live in that repo's demo/scene.py because
"318 rows | 21 columns" is a fact about one piece and cannot sit inside a file
that has to match in four repos.

    with sheet.Scene(video_dir, poster=out / "poster.png") as scene:
        scene.show(before_html, sheet.HOLD_BEFORE)
        scene.panel("before", "Messy supplier feed", "318 rows | 21 columns")
        ...
        scene.show(after_html, sheet.HOLD_AFTER)
        scene.panel("after", "Clean .xlsx, flagged rejects", "every change logged")

`Scene` collects the panels and writes the poster on the way out;
demo/lib/playwright.sh prepends it to both encodes. Nothing here is called
directly by a scene.

--- why the card exists ------------------------------------------------------

Frame 0 of every clip used to be the BEFORE frame, which in three of the four
pieces is a spreadsheet on pale paper. Freelancer derives a video's poster from
frame 0 and a README shows the first frame of the .gif, so at thumbnail size
the portfolio was four near-white rectangles and nobody pressed play (THE-285,
Josue). The card is 0.8s of dark frame that says what the piece does before the
viewer has decided whether to watch.

--- composed from the run's own frames, not drawn ---------------------------

The two panels are screenshots taken by the recording browser, of the frames
that are on screen at that moment, of elements rendered from files the run had
just written. Nothing in here draws a spreadsheet, and there is no artwork to
go stale: change the fixture and the card follows it, the same way the clip
does. That is also why the card is generated rather than hand-made — a
hand-made card is correct once.

--- fonts, which are the reproducibility hole -------------------------------

The label is auto-sized to fit its half of the frame, so the face's metrics
decide the layout, not just its looks. Rendering that against whatever
fontconfig returns on the recording box means `make demo` on a clean checkout
of another machine produces a different card — a label two sizes down, or one
overhanging the divider.

So the card gets its own Chromium, launched with FONTCONFIG_FILE pointing at
demo/lib/fonts.sh's config, which declares the vendored directory and no other.
`font_probe` measures one string under three family names — one of them a
family that cannot exist anywhere — and under that config all three come back
equal, because there is exactly one face to resolve to. tests/test_demo_card.py
runs it both ways and fails if the three ever agree by accident.

The recording's own Chromium is untouched: the scene frames are drawn with the
system stack sheet.py names, this card is a prepend, and the demo bodies were
explicitly not in scope.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from html import escape
from pathlib import Path

# 0.80s at the mp4's 25fps is 20 frames, which is the length Josue's reference
# card ran for. Long enough to read two labels, short enough that nobody
# watching the clip feels held up.
SECONDS = 0.8

# What a grid/document frame's artifact is, inside the page sheet.py builds:
# the one child of <main>. Shooting that rather than the viewport drops the
# narration bar and the legend footer, which are about the beat rather than
# about the artifact, and leaves the file itself — titlebar, grid, sheet tabs.
# A piece whose frame is a whole served page passes selector=None instead.
ARTIFACT = "main > *"

BACKGROUND = "#0d1117"
BORDER = "#343a44"
LABEL_BEFORE = "#eaeef1"
LABEL_AFTER = "#6ee299"
DETAIL = "#9aa4b2"

# The family the CSS asks for. Under CARD_FONTCONFIG_FILE the name barely
# matters — see the module docstring — but naming the face we actually vendored
# means the card still renders recognisably if someone runs card.py by hand
# outside record.sh, and it makes the probe's "these three are equal" result
# mean something a reader can check.
FAMILY = '"DejaVu Sans"'

# Auto-sizing bounds, in px at REFERENCE_WIDTH and scaled with the frame. The
# label ceiling is where a six-word label lands; the floor is where a long one
# stops shrinking, because a size small enough to fit any string is a size
# nobody reads at thumbnail size — past the floor the caption is a defect and
# `render` says so rather than ellipsising it.
REFERENCE_WIDTH = 1280
LABEL_MAX, LABEL_MIN = 58, 26
DETAIL_MAX, DETAIL_MIN = 30, 15


@dataclass(frozen=True)
class Panel:
    """One half of the card. `png` is a screenshot taken by the recording."""

    tone: str       # "before" (white label) or "after" (green label)
    label: str
    detail: str
    png: bytes

    @property
    def colour(self) -> str:
        return LABEL_AFTER if self.tone == "after" else LABEL_BEFORE


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


# The fitter runs in the page rather than here because only the browser knows
# how wide a string is in a given face at a given size, and guessing from
# character counts is what "auto-sized" would mean if it were done in Python.
# It walks down one px at a time from the ceiling: a binary search would be
# fewer steps and the loop is at most 32 of them on a layout that is already
# laid out, so the clearer one wins.
_FIT_JS = """
() => {
  const fitted = {};
  for (const el of document.querySelectorAll('[data-fit]')) {
    const [max, min] = el.dataset.fit.split(',').map(Number);
    let size = max;
    el.style.fontSize = size + 'px';
    // scrollWidth is the unwrapped width; the box is white-space:nowrap, so
    // overflow is the only signal that it does not fit.
    while (size > min && el.scrollWidth > el.clientWidth) {
      size -= 1;
      el.style.fontSize = size + 'px';
    }
    fitted[el.id] = {size, over: el.scrollWidth > el.clientWidth,
                     text: el.textContent};
  }
  return fitted;
}
"""


def card_html(left: Panel, right: Panel, *, width: int, height: int) -> str:
    """The card as one self-contained page. Pure: no browser, no files."""
    pad = round(width * 0.022)          # 28px at 1280
    gap = round(width * 0.019)          # 24px at 1280
    # Every size on the card is a fraction of the frame, so a piece that ever
    # records at another capture size gets the same card rather than the same
    # numbers against a different picture.
    scale = width / REFERENCE_WIDTH
    label_fit = f"{round(LABEL_MAX * scale)},{round(LABEL_MIN * scale)}"
    detail_fit = f"{round(DETAIL_MAX * scale)},{round(DETAIL_MIN * scale)}"

    def half(panel: Panel, side: str) -> str:
        return f"""<section class="half {side}">
      <h1 id="label-{side}" data-fit="{label_fit}"
          style="color:{panel.colour}">{escape(panel.label)}</h1>
      <p id="detail-{side}" data-fit="{detail_fit}">{escape(panel.detail)}</p>
      <div class="frame"><img src="{_data_uri(panel.png)}" alt=""></div>
    </section>"""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>title card</title><style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    width: {width}px; height: {height}px; background: {BACKGROUND};
    font-family: {FAMILY}; color: {DETAIL};
    display: flex; align-items: stretch;
    padding: {pad}px; gap: {gap}px;
  }}
  /* The divider. A border on the left half rather than an element of its own,
     so it cannot be laid out anywhere except between the two halves. */
  .right {{ border-left: 1px solid {BORDER}; padding-left: {gap}px; }}

  .half {{
    flex: 1 1 0; min-width: 0;          /* 0-basis: each half is exactly half,
                                           whatever its panel's aspect is */
    display: flex; flex-direction: column;
  }}
  h1, p {{
    margin: 0; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; line-height: 1.12;
  }}
  h1 {{ font-weight: 700; letter-spacing: -0.5px; }}
  p {{ font-weight: 400; margin-top: {round(height * 0.014)}px; }}

  /* The panel box is the leftover height. The image is contained inside it and
     the border is on the image, not the box, so the line traces the artifact
     rather than boxing empty background beside it.

     Centred, not top-aligned. A frame is 16:9 and a half of one is 8:9, so the
     panel is always width-bound and never fills the box: top-aligning it left
     a third of the card as dead background under the artifact, which reads as
     a card that failed to finish rather than as a margin. */
  .frame {{
    flex: 1 1 auto; min-height: 0; margin-top: {round(height * 0.030)}px;
    display: flex; align-items: center; justify-content: center;
  }}
  .frame img {{
    max-width: 100%; max-height: 100%;
    border: 1px solid {BORDER}; display: block;
  }}
</style></head>
<body>
{half(left, "left")}
{half(right, "right")}
</body></html>
"""


def _browser_env() -> dict:
    """The environment the card's Chromium gets: ours, plus the font jail.

    Merged onto os.environ rather than replacing it, because the vendored
    Chromium needs the LD_LIBRARY_PATH chromium-libs.sh exported and a bare
    env dies at `libnss3.so: cannot open shared object file`.
    """
    env = dict(os.environ)
    conf = env.get("CARD_FONTCONFIG_FILE")
    if not conf or not Path(conf).is_file():
        raise SystemExit(
            "card.py: CARD_FONTCONFIG_FILE is unset or missing, so the card "
            "would be drawn with whatever fonts this box happens to have and "
            "would not reproduce elsewhere. demo/lib/fonts.sh sets it; run the "
            "card through ./demo/record.sh, or source fonts.sh and call "
            "ensure_card_font first."
        )
    env["FONTCONFIG_FILE"] = conf
    # FONTCONFIG_PATH is where fontconfig looks for fonts.dtd and for a
    # fonts.conf when FONTCONFIG_FILE is unset. Pointing it at our directory
    # too keeps a system /etc/fonts out of the picture entirely.
    env["FONTCONFIG_PATH"] = str(Path(conf).parent)
    return env


def render(left: Panel, right: Panel, *, viewport: dict) -> bytes:
    """The card as PNG bytes, drawn in the pinned browser with pinned fonts."""
    from playwright.sync_api import sync_playwright

    html = card_html(left, right, width=viewport["width"], height=viewport["height"])
    with sync_playwright() as play:
        browser = play.chromium.launch(env=_browser_env())
        try:
            page = browser.new_page(viewport=viewport, device_scale_factor=1)
            page.set_content(html, wait_until="load")
            fitted = page.evaluate(_FIT_JS)
            # A string that still overflows at the floor gets ellipsised by the
            # CSS, and an ellipsised caption is a sentence that stops mid-word
            # on the first thing a client sees. Raising here puts that in front
            # of whoever is running `make demo` and has the text in hand,
            # rather than leaving it to be noticed in a proposal. The fix is
            # always shorter words: shrinking further is how the label becomes
            # unreadable at the size it exists to be read at.
            spilled = [f"{name}: {info['text']!r}"
                       for name, info in sorted(fitted.items()) if info["over"]]
            if spilled:
                raise SystemExit(
                    "card.py: this caption does not fit its half of the frame "
                    f"even at the smallest size allowed — {'; '.join(spilled)}"
                )
            return page.screenshot(type="png")
        finally:
            browser.close()


def write(left: Panel, right: Panel, path: str | Path, *, viewport: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render(left, right, viewport=viewport))
    return path


# --------------------------------------------------------------------------
# the font proof
# --------------------------------------------------------------------------

# Three names, one of which is not a font anywhere: with the jail on, all three
# resolve to the one vendored face and measure the same; with it off they
# resolve to three different things on any box with fonts installed. The
# nonsense name is in there so the check cannot be satisfied by a box that
# merely happens to ship the same two families.
PROBE_FAMILIES = ('"DejaVu Sans"', '"Ubuntu"', '"NoSuchFaceXYZ"')
PROBE_TEXT = "Messy supplier feed"
PROBE_SIZE = 60


def font_probe(*, jailed: bool = True) -> dict[str, float]:
    """Measured widths of one string under PROBE_FAMILIES. Family -> px.

    `jailed=False` is the control: it is what the same render would do with the
    system fonts in reach, and it is the arm that makes a passing jailed result
    mean something. A test that only ever ran the jailed arm would pass on a
    box with no fonts at all, which is the opposite of the property wanted.
    """
    from playwright.sync_api import sync_playwright

    # The families go in a <style> block, not in a style="" attribute: a family
    # name carries its own double quotes, which close the attribute early and
    # leave every span at the default 16px — three identical widths that look
    # exactly like a passing jailed result. The control arm of
    # test_the_card_font_is_jailed is what caught that.
    rules = "".join(
        f"#f{n}{{font:700 {PROBE_SIZE}px {family}}}"
        for n, family in enumerate(PROBE_FAMILIES)
    )
    spans = "".join(
        f'<span id="f{n}">{escape(PROBE_TEXT)}</span><br>'
        for n in range(len(PROBE_FAMILIES))
    )
    html = (
        "<!doctype html><meta charset=utf-8><style>"
        "span{display:inline-block;white-space:nowrap}" + rules + "</style>" + spans
    )
    env = _browser_env() if jailed else dict(os.environ)
    if not jailed:
        env.pop("FONTCONFIG_FILE", None)
        env.pop("FONTCONFIG_PATH", None)

    with sync_playwright() as play:
        browser = play.chromium.launch(env=env)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 400})
            page.set_content(html, wait_until="load")
            widths = page.evaluate(
                "n => Array.from({length:n}, (_, i) =>"
                " document.getElementById('f'+i).getBoundingClientRect().width)",
                len(PROBE_FAMILIES),
            )
        finally:
            browser.close()
    return dict(zip(PROBE_FAMILIES, widths))
