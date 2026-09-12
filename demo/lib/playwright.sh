#!/usr/bin/env bash
# Recipe: Playwright. Records a real browser page to video. Generic: do not
# edit per project — the per-piece file is demo/scene.py.
#
# This is the browser-side sibling of demo/lib/vhs.sh. Use it when the thing
# worth showing is a page; use VHS when the thing worth showing is a terminal.
# demo/README.md has the full comparison.
#
# Playwright for *Python* on purpose, not Node: the wheel ships its own driver,
# so a machine with no Node and no npm can still regenerate the clip, and the
# venv lib/uv.sh already bootstraps is the only runtime involved.
#
# The browser goes into demo/.toolchain/browsers rather than ~/.cache, so
# `record.sh --clean` really does throw everything away, and nothing this
# script does leaves the repo.
#
# Contract with record.sh:
#   recipe_bootstrap        fetch whatever this recipe needs
#   recipe_record OUT_DIR   leave a clip in OUT_DIR and set RECIPE_CLIP

set -euo pipefail

TOOLCHAIN_DIR="${TOOLCHAIN_DIR:?playwright.sh needs TOOLCHAIN_DIR}"

# shellcheck source=ffmpeg.sh
. "$(dirname "${BASH_SOURCE[0]}")/ffmpeg.sh"
# shellcheck source=chromium-libs.sh
. "$(dirname "${BASH_SOURCE[0]}")/chromium-libs.sh"
# shellcheck source=uv.sh
. "$(dirname "${BASH_SOURCE[0]}")/uv.sh"

export PLAYWRIGHT_BROWSERS_PATH="$TOOLCHAIN_DIR/browsers"

# Scaled down from the capture size: a 30-second GIF at full resolution is tens
# of megabytes and no client waits for it to load in a README. The frame rate
# is low on purpose — a scene like this is a few long holds and a couple of
# cuts, so frames spent on "motion" are frames wasted. Raise GIF_FPS for a
# piece whose clip actually moves.
GIF_WIDTH="${GIF_WIDTH:-880}"
GIF_FPS="${GIF_FPS:-5}"

pw_log() { printf '  %s\n' "$*" >&2; }

pw_python() {
  local py="$REPO_ROOT/.venv/bin/python"
  [ -x "$py" ] || { echo "playwright.sh: no venv at $py; setup.sh should have made one" >&2; return 1; }
  printf '%s' "$py"
}

ensure_playwright_package() {
  local py
  py="$(pw_python)" || return 1
  if "$py" -c 'import playwright' 2>/dev/null; then
    return 0
  fi
  pw_log "installing the playwright package into .venv"
  local uv
  if uv="$(ensure_uv)"; then
    VIRTUAL_ENV="$REPO_ROOT/.venv" "$uv" pip install --quiet "$REPO_ROOT[demo]"
  else
    "$py" -m pip install --quiet "$REPO_ROOT[demo]"
  fi
  "$py" -c 'import playwright' 2>/dev/null
}

# Specifically *our* browser, under PLAYWRIGHT_BROWSERS_PATH. Not
# find_chromium from chromium-libs.sh, which happily returns the VHS recipe's
# Chromium in ~/.cache/rod — a different build with different library needs,
# and not the one Playwright is going to launch.
find_playwright_chromium() {
  local candidate
  for candidate in "$PLAYWRIGHT_BROWSERS_PATH"/chromium-*/chrome-linux/chrome; do
    [ -x "$candidate" ] && { printf '%s' "$candidate"; return 0; }
  done
  return 1
}

ensure_browser() {
  local py
  py="$(pw_python)" || return 1
  if find_playwright_chromium >/dev/null 2>&1; then
    return 0
  fi
  pw_log "downloading Chromium into demo/.toolchain/browsers (~170 MB, once)"
  # Deliberately not `install --with-deps`: that shells out to apt-get and
  # wants root. vendor_chromium_libs does the same job without it.
  "$py" -m playwright install chromium
  find_playwright_chromium >/dev/null || {
    echo "playwright.sh: the browser download did not leave a chrome binary in" >&2
    echo "  $PLAYWRIGHT_BROWSERS_PATH" >&2
    return 1
  }
}

recipe_bootstrap() {
  mkdir -p "$TOOLCHAIN_DIR/bin"
  ensure_ffmpeg
  ensure_playwright_package
  ensure_browser
  vendor_chromium_libs "$(find_playwright_chromium)" || true
}

# webm (what Playwright records) -> gif (what a README can embed) + mp4 (what
# you attach to a proposal).
#
# palettegen/paletteuse rather than letting ffmpeg pick 256 web-safe colours:
# a flat UI quantised naively gets visible banding across every card. dither is
# off for the same reason it is usually on — dithering a flat UI adds noise
# that costs a megabyte and buys nothing.
encode_clip() {
  local source="$1" out_dir="$2"
  local filters="fps=${GIF_FPS},scale=${GIF_WIDTH}:-2:flags=lanczos"

  pw_log "encoding gif"
  ffmpeg -nostdin -loglevel error -y -i "$source" \
    -vf "${filters},split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none" \
    -loop 0 "$out_dir/demo.gif"

  pw_log "encoding mp4"
  # libx264 refuses odd dimensions, hence the -2 in the scale filter above.
  ffmpeg -nostdin -loglevel error -y -i "$source" \
    -vf "scale=${GIF_WIDTH}:-2:flags=lanczos" \
    -c:v libx264 -pix_fmt yuv420p -crf 26 -preset veryfast \
    -movflags +faststart "$out_dir/demo.mp4"
}

recipe_record() {
  local out_dir="$1" raw="$1/raw" py scene
  scene="${SCENE:-$DEMO_DIR/scene.py}"
  [ -f "$scene" ] || { echo "playwright.sh: no scene at $scene" >&2; return 1; }
  py="$(pw_python)"

  mkdir -p "$raw"
  ( cd "$REPO_ROOT" && "$py" "$scene" --video-dir "$raw" )

  local source
  source="$(find "$raw" -name '*.webm' -type f | head -1)"
  if [ -z "$source" ]; then
    echo "playwright.sh: the scene produced no video" >&2
    return 1
  fi

  encode_clip "$source" "$out_dir"
  rm -rf "$raw"
  RECIPE_CLIP="$out_dir/demo.gif"
}
