#!/usr/bin/env python3
"""Does this clip end on the frame it is supposed to end on?

Generic: do not edit per project. Run by demo/lib/playwright.sh on each encode
it produces, so a clip that ends wrong fails the recording instead of shipping.

    python3 lastframe.py demo/out/demo.mp4 --ffmpeg ffmpeg --width 1280

Why this exists (THE-295). Every demo here has to end on the real output file
open in a grid, and the last frame is the one that matters most: it is the
image a player holds after playback stops, so it is what stays on screen. Two
things used to break that quietly.

* Chromium's element-screenshot path resizes the capture surface, and the
  screencast behind Playwright's `record_video_dir` emitted the bare element
  pinned to the top-left of the video canvas with flat grey filling the rest.
  `sheet.Scene` no longer screenshots during a take, which is the actual fix --
  this is the check that says so at recording time.
* Nothing downstream would have noticed. The encode succeeds, the duration is
  inside budget, the file sizes look right, and the defect is one frame out of
  483. It was found by eye, three reviews in.

What it asserts, and why in these terms rather than on bytes: re-recording is
not reproducible to the byte -- OCR timing, VP8, x264 -- so a byte or checksum
gate would be a gate that has to be switched off. The house rule is that a
clip ends on a *held* shot of the artifact, 8-10 seconds of it. So:

    every frame in the last --hold seconds is the same picture as the frame
    just before that window opens

which is the rule restated as an assertion. A junk frame anywhere in the tail
breaks it whether there is one of them or five, whether it is last or third
from last -- the counts differed per piece (0, 1, 2 and 5 were all observed),
so a check that dropped "the last frame" would have been right about one piece
and wrong about the others.

Measured separation on the five pieces as they stood when this was written,
mean absolute luma difference on a 160x90 decode, 0-255:

    clean       catalog-watch mp4 0.83  gif 1.28   pdf-to-csv mp4 0.00  gif 0.18
                inbox-filer gif 0.24    ocr-scan-to-csv gif 0.28
    defective   feed-clean mp4 52.67  gif 53.84    inbox-filer mp4 68.87
                ocr-scan-to-csv mp4 52.79

TOLERANCE is 6.0: 4.7x the worst clean reading and 8.8x below the mildest
defective one. It is a wide gap on purpose -- the thing being caught is a
completely different picture, not a slightly different one, and a tight
threshold here would fail on lossy noise and teach whoever hits it to raise it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from fractions import Fraction

# Decode size for the comparison. Small on purpose: this is asking "is it the
# same picture", not "is it the same pixels", and a 160x90 gray frame is 14 kB,
# so a whole clip decodes into a few megabytes and a second.
PROBE_WIDTH = 160
PROBE_HEIGHT = 90

# Mean absolute difference, 0-255, above which two frames are different
# pictures. See the module docstring for the measurements behind the number.
TOLERANCE = 6.0

# How much of the tail has to be one held picture.
HOLD_SECONDS = 1.0


def probe(ffprobe: str, path: str) -> tuple[int, int, float]:
    """Width, height and frame rate, straight from the container."""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate", "-of", "csv=p=0", path],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    width, height, rate = out.split(",")[:3]
    return int(width), int(height), float(Fraction(rate))


def frames(ffmpeg: str, path: str) -> list[bytes]:
    """Every frame, decoded from the start.

    Deliberately not a seek. `-sseof` reproduces the defect this file exists to
    catch, but a seek into a long-GOP encode can also manufacture one, and a
    check that cannot tell its own artifacts from the file's is not a check.
    A full decode costs about a second here and is not ambiguous.
    """
    raw = subprocess.run(
        [ffmpeg, "-nostdin", "-loglevel", "error", "-i", path,
         "-vf", f"scale={PROBE_WIDTH}:{PROBE_HEIGHT}:flags=area,format=gray",
         "-f", "rawvideo", "-"],
        check=True, capture_output=True,
    ).stdout
    size = PROBE_WIDTH * PROBE_HEIGHT
    return [raw[i:i + size] for i in range(0, len(raw) - size + 1, size)]


def difference(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def check(path: str, *, ffmpeg: str, ffprobe: str,
          width: int | None, height: int | None,
          hold: float = HOLD_SECONDS) -> list[str]:
    """Everything wrong with how this clip ends, as printable lines."""
    faults: list[str] = []
    got_width, got_height, fps = probe(ffprobe, path)

    if width is not None and got_width != width:
        faults.append(f"width is {got_width}, expected {width}")
    if height is not None and got_height != height:
        faults.append(f"height is {got_height}, expected {height}")

    decoded = frames(ffmpeg, path)
    window = max(1, round(fps * hold))
    if len(decoded) <= window:
        faults.append(
            f"only {len(decoded)} frames at {fps:g}fps, which is shorter than "
            f"the {hold:g}s hold this checks"
        )
        return faults

    # The reference is the frame just before the window: inside the AFTER hold
    # by construction, and not itself part of what is being judged.
    reference = decoded[-window - 1]
    worst, worst_at = 0.0, 0
    for offset, frame in enumerate(decoded[-window:], start=len(decoded) - window):
        seen = difference(reference, frame)
        if seen > worst:
            worst, worst_at = seen, offset + 1   # 1-based, as ffmpeg counts

    if worst > TOLERANCE:
        faults.append(
            f"frame {worst_at} of {len(decoded)} differs from the held shot by "
            f"{worst:.2f} (tolerance {TOLERANCE}); the last {hold:g}s should be "
            f"one picture. A leaked capture frame measures ~50-70 here"
        )
    return faults


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--width", type=int, help="fail unless the clip is this wide")
    parser.add_argument("--height", type=int, help="fail unless the clip is this tall")
    parser.add_argument("--hold", type=float, default=HOLD_SECONDS)
    args = parser.parse_args(argv)

    faults = check(args.video, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe,
                   width=args.width, height=args.height, hold=args.hold)
    if not faults:
        return 0
    print(f"lastframe.py: {args.video} does not end on a held shot:",
          file=sys.stderr)
    for fault in faults:
        print(f"  {fault}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
