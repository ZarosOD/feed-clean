"""What the `make` targets are allowed to do to `out/`.

The bug this exists to prevent: `demo/setup.sh` ended with `rm -rf demo/.scratch
out`, and the Makefile makes `setup` a prerequisite of `run`, `test`, `strict`
and `fixtures`. So `make run` wrote four files and `make test` silently deleted
them — while the README prints those two commands on adjacent lines.

Nothing in the unit suite could see it, because the deletion happened in the
prerequisite, before pytest started. These tests drive `make` itself in a copy
of the repo, which is the only level the bug was ever visible from.

The copy is what makes them safe to run: `--fresh` really does `rm -rf out`, so
pointing it at the developer's own checkout would destroy the output they were
looking at. The copy symlinks `.venv` back to the real one rather than building
its own, which keeps each test well under a second and needs no network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OUTPUT_FILES = ("clean.csv", "rejects.csv", "changes.csv", "summary.txt")

# Everything the copy either cannot use or should not inherit: the venv is
# symlinked in afterwards, and out/ has to start absent so its reappearance
# means `make run` created it.
SKIP = shutil.ignore_patterns(
    ".venv", ".git", "out", "__pycache__", ".pytest_cache", "*.egg-info", ".toolchain"
)

pytestmark = [
    pytest.mark.skipif(shutil.which("make") is None, reason="these tests drive make"),
    pytest.mark.skipif(
        not (REPO / ".venv" / "bin" / "python").exists(),
        reason="no .venv to lend the copy (setup.sh builds one before pytest runs)",
    ),
]


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A throwaway copy of the repo with no out/ and a borrowed venv."""
    root = tmp_path / "feed-clean"
    shutil.copytree(REPO, root, ignore=SKIP, symlinks=True)
    (root / ".venv").symlink_to(REPO / ".venv")
    assert not (root / "out").exists()
    return root


def make(checkout: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # pytest may itself have been started by `make test`; handing its jobserver
    # down to a nested make produces warnings and, worse, a shared job slot.
    env.pop("MAKEFLAGS", None)
    env.pop("MAKELEVEL", None)
    # `make test` in the copy would otherwise re-run this file, which would copy
    # the repo again, and so on. Collection still loads conftest and every test
    # module, and still runs the `setup` prerequisite — which is where the bug
    # lived — so the target is exercised where it matters.
    env["PYTEST_ADDOPTS"] = "--collect-only -q"
    return subprocess.run(
        ["make", *args], cwd=checkout, capture_output=True, text=True, env=env
    )


def setup_sh(checkout: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["./demo/setup.sh", *args], cwd=checkout, capture_output=True, text=True
    )


def out_files(checkout: Path) -> set[str]:
    out = checkout / "out"
    return {p.name for p in out.iterdir()} if out.is_dir() else set()


def test_run_writes_the_output_files(checkout: Path) -> None:
    result = make(checkout, "run")

    assert result.returncode == 0, result.stderr
    assert out_files(checkout) >= set(OUTPUT_FILES)


# `make strict` exits 2 by design on this feed: 15 rows are rejected. That is
# the target doing its job, not a failure, and it must not change the answer to
# "is the output still there".
@pytest.mark.parametrize(
    ("target", "exit_code"), [("test", 0), ("strict", 2), ("fixtures", 0)]
)
def test_other_targets_leave_the_output_alone(
    checkout: Path, target: str, exit_code: int
) -> None:
    assert make(checkout, "run").returncode == 0
    before = out_files(checkout)
    assert before >= set(OUTPUT_FILES)
    # A file nothing regenerates: if out/ is removed and rebuilt rather than
    # left alone, the four real files come back and this one does not.
    (checkout / "out" / "sentinel.txt").write_text("mine", encoding="utf-8")

    result = make(checkout, target)

    assert result.returncode == exit_code, result.stdout + result.stderr
    assert out_files(checkout) >= before | {"sentinel.txt"}
    assert (checkout / "out" / "sentinel.txt").read_text(encoding="utf-8") == "mine"


def test_setup_run_directly_leaves_the_output_alone(checkout: Path) -> None:
    """The second way the bug reproduced: no make involved at all."""
    assert make(checkout, "run").returncode == 0
    before = out_files(checkout)

    result = setup_sh(checkout)

    assert result.returncode == 0, result.stderr
    assert out_files(checkout) == before


def test_setup_fresh_removes_the_output(checkout: Path) -> None:
    """The recording path still gets its empty repo — record.sh passes --fresh."""
    assert make(checkout, "run").returncode == 0
    assert (checkout / "out").is_dir()

    result = setup_sh(checkout, "--fresh")

    assert result.returncode == 0, result.stderr
    assert not (checkout / "out").exists()


def test_setup_clears_its_own_scratch_either_way(checkout: Path) -> None:
    """demo/.scratch is the demo's workspace, not output, so it always goes."""
    scratch = checkout / "demo" / ".scratch"
    scratch.mkdir(parents=True)
    (scratch / "leftover").write_text("x", encoding="utf-8")

    assert setup_sh(checkout).returncode == 0

    assert not scratch.exists()


def test_setup_rejects_an_unknown_argument(checkout: Path) -> None:
    """A typo'd flag must not read as "no flag" and quietly skip the wipe."""
    result = setup_sh(checkout, "--clean")

    assert result.returncode == 2
    assert "--fresh" in result.stderr


def test_record_sh_asks_setup_for_a_fresh_start() -> None:
    """The wiring the two setup.sh tests above cannot reach.

    Running record.sh for real means downloading vhs, ttyd, ffmpeg and a
    headless Chromium, which is `make demo`'s job and not a unit test's. What
    is checkable here is that the one caller entitled to the wipe still asks
    for it, so the recording does not quietly start on stale output.
    """
    line = next(
        line
        for line in (REPO / "demo" / "record.sh").read_text(encoding="utf-8").splitlines()
        if "setup.sh" in line and not line.lstrip().startswith("#")
    )

    assert line.strip() == '"$DEMO_DIR/setup.sh" --fresh'
