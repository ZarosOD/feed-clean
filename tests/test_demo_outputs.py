"""Tests for the two output targets in demo/lib/vhs.sh.

Like test_demo_fetch.py, this covers the demo layer rather than the shipped
tool. It is here because of a specific failure mode: vhs has been seen to exit
0 having written no file, and it does that per output target. A run that
produced the GIF and silently skipped the MP4 would look like a success in
every way a human checks — green exit code, a clip on disk, a README that
still renders — and the missing file would only surface when somebody went to
upload a portfolio cover and found nothing there.

So the shim is a `vhs` on PATH that writes whichever `-o` targets a test tells
it to, and exits 0 regardless. That exercises the real bash: the flags that get
passed, the retry, and the per-target check.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VHS_SH = REPO_ROOT / "demo" / "lib" / "vhs.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="vhs.sh is a bash library"
)


def make_vhs(bin_dir: Path, *, writes: tuple[str, ...]) -> Path:
    """A vhs that writes only the named basenames, then exits 0.

    `writes=("demo.gif",)` is the silent-miss case: a real exit code of 0 with
    one of the two targets absent.

    The written files carry a byte of content on purpose. vhs.sh checks each
    target with `-s`, not `-e`, because the failure it guards against leaves a
    zero-length file behind as often as it leaves nothing at all.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    vhs = bin_dir / "vhs"
    wanted = " ".join(writes)
    vhs.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            # Record the arguments, one per line, so a test can count the -o
            # flags without a path that happens to contain "-o" inflating it.
            for arg in "$@"; do printf '%s\\n' "$arg" >> "$VHS_CALLS"; done
            printf -- '--- end of call\\n' >> "$VHS_CALLS"
            for arg in "$@"; do
                case "$prev" in
                    -o) for want in {wanted}; do
                            [ "$(basename "$arg")" = "$want" ] &&
                                printf 'clip\\n' > "$arg"
                        done ;;
                esac
                prev="$arg"
            done
            exit 0
            """
        )
    )
    vhs.chmod(0o755)
    return vhs


def run_recipe_record(tmp_path: Path, *, writes: tuple[str, ...]) -> tuple[int, str]:
    """Source vhs.sh and call recipe_record with a shimmed vhs on PATH."""
    bin_dir = tmp_path / "bin"
    make_vhs(bin_dir, writes=writes)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    tape = tmp_path / "demo.tape"
    tape.write_text("Type 'hello'\n")

    script = textwrap.dedent(
        f"""\
        export TOOLCHAIN_DIR={tmp_path / "toolchain"}
        export DEMO_DIR={REPO_ROOT / "demo"}
        export REPO_ROOT={REPO_ROOT}
        export TAPE={tape}
        export PATH={bin_dir}:$PATH
        . {VHS_SH}
        # Stub the one bootstrap helper recipe_record calls on the retry path,
        # so a failing first attempt does not try to vendor real libraries.
        vendor_chromium_libs() {{ :; }}
        recipe_record {out_dir}
        echo "RECIPE_CLIP=$RECIPE_CLIP"
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "VHS_CALLS": str(tmp_path / "calls")},
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_both_targets_are_requested_in_one_invocation(tmp_path: Path) -> None:
    """One vhs run, two -o flags: the GIF and the MP4 are the same recording.

    Two separate invocations would be two captures, and two captures of a
    typing animation are never identical. Asserting on a single call is what
    makes "same content as the GIF" a property of the code.
    """
    run_recipe_record(tmp_path, writes=("demo.gif", "demo.mp4"))
    args = (tmp_path / "calls").read_text().splitlines()
    assert args.count("--- end of call") == 1, f"expected one vhs run, got {args}"
    assert args.count("-o") == 2, f"expected two -o flags, got {args}"
    basenames = [Path(a).name for a in args]
    assert "demo.gif" in basenames and "demo.mp4" in basenames


def test_both_files_present_succeeds(tmp_path: Path) -> None:
    code, output = run_recipe_record(tmp_path, writes=("demo.gif", "demo.mp4"))
    assert code == 0, output
    assert "RECIPE_CLIP=" in output
    assert output.strip().endswith("demo.gif"), "the measured clip is still the GIF"


def test_missing_mp4_fails_even_though_vhs_exited_zero(tmp_path: Path) -> None:
    """The case the check exists for: a green exit code and no MP4."""
    code, output = run_recipe_record(tmp_path, writes=("demo.gif",))
    assert code != 0, "a missing MP4 must not pass as a successful recording"
    assert "demo.mp4" in output


def test_missing_gif_also_fails(tmp_path: Path) -> None:
    """The check is per target, not a special case for the new one."""
    code, output = run_recipe_record(tmp_path, writes=("demo.mp4",))
    assert code != 0
    assert "demo.gif" in output


def test_committed_clip_directory_holds_both_formats() -> None:
    """The deliverable itself, not the machinery that builds it.

    demo/out/ is committed on purpose, so this asserts the repo a client
    clones actually contains the portfolio cover.

    poster.png is here for the same reason the two clips are: it is the cover
    image a platform is handed when it will not take a video, and the
    Playwright recipe writes it during the run — after record.sh has wiped and
    recreated the directory — so it has exactly the lifetime the clips have.
    What is *in* it is tests/test_demo_card.py's business.
    """
    out_dir = REPO_ROOT / "demo" / "out"
    for name in ("demo.gif", "demo.mp4", "poster.png"):
        clip = out_dir / name
        assert clip.is_file(), f"{name} is missing from demo/out/"
        assert clip.stat().st_size > 0, f"{name} is empty"
