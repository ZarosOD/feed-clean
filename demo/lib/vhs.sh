#!/usr/bin/env bash
# Recipe: VHS. Records a terminal session from a tape file. Generic: do not
# edit per project — the per-piece file is demo/demo.tape.
#
# This was demo/lib/bootstrap.sh in the first portfolio piece, when VHS was the
# only recipe. It keeps the toolchain bootstrap and gains the two functions
# demo/record.sh calls; ffmpeg and the Chromium libraries moved to their own
# files because the Playwright recipe needs them too.
#
# Contract with record.sh:
#   recipe_bootstrap        fetch whatever this recipe needs
#   recipe_record OUT_DIR   leave a clip in OUT_DIR

set -euo pipefail

# vhs 0.12.x starts Chromium, captures frames, then silently writes no file on
# some Linux boxes (the frame-encoding step exits 0 having done nothing).
# 0.10.0 is the newest release that encodes reliably headless, so it is pinned
# rather than tracking latest.
VHS_VERSION="0.10.0"
TTYD_VERSION="1.7.7"

TOOLCHAIN_DIR="${TOOLCHAIN_DIR:?vhs.sh needs TOOLCHAIN_DIR}"
TOOLCHAIN_BIN="$TOOLCHAIN_DIR/bin"

# shellcheck source=fetch.sh
. "$(dirname "${BASH_SOURCE[0]}")/fetch.sh"
# shellcheck source=ffmpeg.sh
. "$(dirname "${BASH_SOURCE[0]}")/ffmpeg.sh"
# shellcheck source=chromium-libs.sh
. "$(dirname "${BASH_SOURCE[0]}")/chromium-libs.sh"

vhs_log() { printf '  %s\n' "$*" >&2; }

ensure_vhs() {
  [ -x "$TOOLCHAIN_BIN/vhs" ] && return 0
  vhs_log "fetching vhs $VHS_VERSION"
  local url="https://github.com/charmbracelet/vhs/releases/download/v${VHS_VERSION}/vhs_${VHS_VERSION}_Linux_x86_64.tar.gz"
  local work
  work="$(mktemp -d)"
  # Fatal, not a fallback: there is no recording without vhs. fetch_url has
  # already retried and explained itself, so just stop.
  if ! fetch_url "$url" "$work/vhs.tar.gz"; then
    rm -rf "$work"
    return 1
  fi
  tar xzf "$work/vhs.tar.gz" -C "$work"
  find "$work" -name vhs -type f -exec install -m 0755 {} "$TOOLCHAIN_BIN/vhs" \;
  rm -rf "$work"
}

ensure_ttyd() {
  command -v ttyd >/dev/null 2>&1 && return 0
  [ -x "$TOOLCHAIN_BIN/ttyd" ] && return 0
  vhs_log "fetching ttyd $TTYD_VERSION"
  # This is the asset whose CDN returned 500 for a couple of minutes on
  # 2026-09-11 and took `make demo` down with it. See lib/fetch.sh.
  fetch_url \
    "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" \
    "$TOOLCHAIN_BIN/ttyd" || return 1
  chmod 0755 "$TOOLCHAIN_BIN/ttyd"
}

recipe_bootstrap() {
  mkdir -p "$TOOLCHAIN_BIN"
  ensure_vhs
  ensure_ttyd
  ensure_ffmpeg
  export PATH="$TOOLCHAIN_BIN:$PATH"
  vendor_chromium_libs || true
}

recipe_record() {
  local out_dir="$1"
  local tape="${TAPE:-$DEMO_DIR/demo.tape}"
  [ -f "$tape" ] || { echo "vhs.sh: no tape at $tape" >&2; return 1; }

  # -o rather than a fixed `Output` line in the tape, so record.sh decides
  # where the clip goes and a repo can hold clips from both recipes at once.
  play() ( cd "$REPO_ROOT" && vhs -o "$out_dir/demo.gif" "$tape" )

  # The first run on a fresh machine is also what downloads headless Chromium.
  # If that run fails, vendor whatever libraries it turned out to need and
  # retry exactly once.
  if ! play; then
    vhs_log "first attempt failed; checking headless Chromium libraries"
    vendor_chromium_libs || true
    play
  fi
  RECIPE_CLIP="$out_dir/demo.gif"
}
