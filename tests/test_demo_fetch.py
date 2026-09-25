"""Tests for demo/lib/fetch.sh, the shared download-with-retry helper.

Like test_demo_preview.py, this covers the demo layer rather than the shipped
tool. It is here because the thing fetch.sh exists to prevent — a two-minute
CDN blip turning `make demo` into a broken repo — is invisible until it
happens, and by then it happens in front of somebody else.

The shim is a `curl` on PATH that fails a scripted number of times and then
succeeds, so the retry ladder is exercised for real (bash, subshells, exit
codes) instead of being asserted about in a comment.

This file is byte-identical in all four portfolio repos, and since THE-274 the
maintainers' drift checker keeps it that way from its SHARED_ROOT list. That
checker is a rookery tool and is not in this repo, so there is nothing here to
run; before it existed this file was copied by hand and nothing watched it.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

FETCH_SH = Path(__file__).resolve().parents[1] / "demo" / "lib" / "fetch.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="fetch.sh is a bash library"
)


def make_curl(bin_dir: Path, *, fail_times: int, code: int = 22) -> Path:
    """A curl that fails `fail_times` times, then writes the output file.

    It records one line per invocation in `calls`, which is what lets a test
    assert on the number of attempts rather than only on the final result.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            # Find the -o destination the same way the real curl would.
            dest=""
            prev=""
            for arg in "$@"; do
              if [ "$prev" = "-o" ]; then dest="$arg"; fi
              prev="$arg"
            done
            echo call >>"{bin_dir}/calls"
            attempts=$(wc -l <"{bin_dir}/calls")
            if [ "$attempts" -le {fail_times} ]; then
              # A real failing curl -f leaves no usable file behind.
              exit {code}
            fi
            printf 'payload' >"$dest"
            """
        ),
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return curl


def run_fetch(tmp_path: Path, bin_dir: Path, dest: Path, *, attempts: int = 3) -> subprocess.CompletedProcess:
    """Source fetch.sh with the shim first on PATH and fetch one URL."""
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        . "{FETCH_SH}"
        FETCH_ATTEMPTS={attempts} FETCH_BACKOFF=0 \
          fetch_url "https://example.invalid/asset.tar.gz" "{dest}"
        """
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)},
    )


def calls(bin_dir: Path) -> int:
    log = bin_dir / "calls"
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


def test_succeeds_first_time_without_retrying(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    make_curl(bin_dir, fail_times=0)
    dest = tmp_path / "asset.tar.gz"

    result = run_fetch(tmp_path, bin_dir, dest)

    assert result.returncode == 0, result.stderr
    assert dest.read_text(encoding="utf-8") == "payload"
    assert calls(bin_dir) == 1
    # A clean fetch should be silent; retry chatter means the ladder misfired.
    assert "retrying" not in result.stderr


def test_retries_a_transient_failure_and_recovers(tmp_path: Path) -> None:
    """The 2026-09-11 case: HTTP 500 on one asset, fine moments later."""
    bin_dir = tmp_path / "bin"
    make_curl(bin_dir, fail_times=2, code=22)
    dest = tmp_path / "asset.tar.gz"

    result = run_fetch(tmp_path, bin_dir, dest, attempts=3)

    assert result.returncode == 0, result.stderr
    assert dest.read_text(encoding="utf-8") == "payload"
    assert calls(bin_dir) == 3
    assert result.stderr.count("retrying") == 2


def test_gives_up_non_zero_and_leaves_no_partial_file(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    make_curl(bin_dir, fail_times=99)
    dest = tmp_path / "asset.tar.gz"
    # A leftover from an earlier half-download must not survive as a "success".
    dest.write_text("truncated", encoding="utf-8")

    result = run_fetch(tmp_path, bin_dir, dest, attempts=3)

    assert result.returncode != 0
    assert calls(bin_dir) == 3
    assert not dest.exists()
    # The message has to tell the reader which of the two cases they are in,
    # because a 5xx and a 404 need different responses.
    assert "5xx" in result.stderr and "404" in result.stderr


def test_reports_the_real_curl_exit_code(tmp_path: Path) -> None:
    """Regression: `$?` after a plain `fi` is the if-statement's status, not
    curl's, so every failure printed as "curl 0" — discarding the one number
    that says whether re-running would help."""
    bin_dir = tmp_path / "bin"
    make_curl(bin_dir, fail_times=99, code=7)

    result = run_fetch(tmp_path, bin_dir, tmp_path / "asset.tar.gz", attempts=2)

    assert "curl 7" in result.stderr
    assert "curl 0" not in result.stderr


def test_attempts_is_a_count_not_a_retry_count(tmp_path: Path) -> None:
    """FETCH_ATTEMPTS=1 means try once, not try once then retry once."""
    bin_dir = tmp_path / "bin"
    make_curl(bin_dir, fail_times=99)

    result = run_fetch(tmp_path, bin_dir, tmp_path / "asset.tar.gz", attempts=1)

    assert result.returncode != 0
    assert calls(bin_dir) == 1
    assert "retrying" not in result.stderr


def test_reports_a_missing_curl_rather_than_crashing(tmp_path: Path) -> None:
    """uv.sh treats a failed fetch as a fallback, so this must return, not die."""
    empty_bin = tmp_path / "empty"
    empty_bin.mkdir()
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        . "{FETCH_SH}"
        if fetch_url "https://example.invalid/x" "{tmp_path}/x"; then
          echo UNEXPECTED_SUCCESS
        else
          echo HANDLED
        fi
        """
    )
    # bash by absolute path: PATH here holds no curl, and so no bash either.
    result = subprocess.run(
        [str(shutil.which("bash")), "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": str(empty_bin), "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    assert "HANDLED" in result.stdout
    assert "curl is not installed" in result.stderr
