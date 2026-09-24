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
# shellcheck source=fonts.sh
. "$(dirname "${BASH_SOURCE[0]}")/fonts.sh"
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
GIF_WIDTH="${GIF_WIDTH:-1000}"
GIF_FPS="${GIF_FPS:-6}"

# The mp4 is not the GIF and does not share its ceiling. GIF_WIDTH buys a
# README that loads; the mp4 is what you attach to a proposal, and at a couple
# of hundred kilobytes there is no size pressure on it to trade anything away
# for. So it keeps the capture size. Empty means exactly that — no resampling.
# Set MP4_WIDTH to a number for a piece that needs a smaller attachment.
MP4_WIDTH="${MP4_WIDTH:-}"

# What Playwright records at. Named rather than written into the filter string
# twice, because the card's frame count is CARD_SECONDS x this and the two
# have to be the same number.
MP4_FPS="${MP4_FPS:-25}"

# How long the title card holds at the head of both encodes. Frame 0 used to
# be the BEFORE frame, which in three of the four pieces is a spreadsheet on
# pale paper: at thumbnail size a viewer sees a white rectangle and does not
# press play, and Freelancer derives a video's poster from frame 0 (THE-285).
#
# The card is drawn by demo/lib/card.py out of the run's own frames and lands
# at $OUT_DIR/poster.png, beside demo.gif and demo.mp4 and with the same
# lifetime — record.sh wipes OUT_DIR at the start of a run and this is written
# during it, so it is regenerated, never orphaned.
#
# 0.8s is 20 frames on the mp4's 25fps. The GIF runs at GIF_FPS, so the same
# 0.8s is a handful of frames there; both are ffmpeg's rounding of the same
# number rather than two settings that could drift.
CARD_SECONDS="${CARD_SECONDS:-0.8}"

# Chromium records the page as lossy VP8, so a flat CSS colour does not arrive
# flat. Measured inside one 56px #cdd3e4 thumbnail: 6-9 distinct values, and the
# minority ones flip every few frames. That costs twice over. The flipped pixels
# straddle a palette boundary, so paletteuse splits a flat square across two
# entries and the thumbnails come out visibly striped; and because those pixels
# change every frame, the GIF's inter-frame transparency cannot drop them, so
# every frame re-sends them. Snapping each channel to a step of 8 puts the
# spread back on one value and both costs go away — same scene, ~30% smaller,
# and the squares are flat again. 8 is the knee: 4 recovers only a third of it,
# 12 starts to band. Set GIF_QUANT=1 to turn it off for a clip of real
# photography, where the noise floor is the picture.
GIF_QUANT="${GIF_QUANT:-8}"

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
  ensure_card_font
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
#
# stats_mode=full, not diff. diff weights the palette toward pixels that change
# between frames, which on a scene of long static holds means weighting it
# toward the VP8 noise GIF_QUANT exists to remove. full keeps the flat UI
# colours truer: measured against the source, the worst thumbnail lands 5 away
# under full and 8 under diff.
#
# The quantiser only goes in front of the GIF. x264 spends a few bits on the
# same noise and shrugs — measured 3% on the mp4, against 30% on the gif — so
# the mp4 keeps the untouched picture.
#
# --- the title card at the head of both ---------------------------------
#
# Both encodes take two inputs: the card as a still, looped for CARD_SECONDS,
# then the recording. They are joined with concat, which demands the two
# streams agree on size, pixel format and sample aspect — hence the setsar and
# format in each branch. The card is drawn at the capture size, so the scale
# that fits the recording fits it too and neither is resampled differently
# from the other.
#
# The scene writes the card to $out_dir/poster.png and it is also the shipped
# cover image, so the file the viewer can be handed separately and the first
# frame of the clip are the same render by construction, not by a copy step
# somebody has to remember.
#
# --- the lead-in at the head of the body --------------------------------
#
# The fourth argument is how many seconds of the recording are lead-in the
# scene never meant to ship, and it comes off the body before anything else
# touches it. Chromium's screencast starts at page creation, when the page is
# a blank white about:blank, so the recording's first frames are a race
# between that and the first beat's first paint — four of the five pieces lost
# it and opened on a white frame (THE-305). sheet.Scene holds its first beat
# that much longer and writes the number beside the video, so the seconds
# added and the seconds cut are one number rather than two that agree until
# somebody edits one.
#
# setpts=PTS-STARTPTS restamps what survives back to zero; without it concat
# holds the card on screen for the length of the trim. The trim sits in front
# of fps= so the resampling only ever sees frames that are being kept.
encode_clip() {
  local source="$1" out_dir="$2" card="$3" lead="${4:-0}"
  local gif_scale="scale=${GIF_WIDTH}:-2:flags=lanczos"
  local quant=""
  local trim=""

  if [ ! -s "$card" ]; then
    echo "playwright.sh: the scene left no title card at $card" >&2
    echo "  the scene must pass poster= to sheet.Scene and mark two panels" >&2
    return 1
  fi

  case "$lead" in
    *[!0-9.]*|''|*.*.*|.)
      echo "playwright.sh: lead-in '$lead' is not a number of seconds" >&2
      return 1 ;;
  esac
  case "$lead" in
    0|0.|0.0|.0|0.00) ;;
    *) trim="trim=start=${lead},setpts=PTS-STARTPTS," ;;
  esac

  if [ "$GIF_QUANT" -gt 1 ]; then
    local snap="trunc(val/${GIF_QUANT})*${GIF_QUANT}"
    quant="lutrgb=r=${snap}:g=${snap}:b=${snap},"
  fi

  pw_log "encoding gif"
  ffmpeg -nostdin -loglevel error -y \
    -loop 1 -t "$CARD_SECONDS" -framerate "$GIF_FPS" -i "$card" \
    -i "$source" \
    -filter_complex "\
      [0:v]${gif_scale},setsar=1,format=rgb24[card]; \
      [1:v]${trim}fps=${GIF_FPS},${gif_scale},setsar=1,format=rgb24[body]; \
      [card][body]concat=n=2:v=1[joined]; \
      [joined]${quant}split[a][b]; \
      [a]palettegen=max_colors=128:stats_mode=full[p]; \
      [b][p]paletteuse=dither=none" \
    -loop 0 "$out_dir/demo.gif"

  pw_log "encoding mp4"
  # libx264 refuses odd dimensions. Asked for a width, -2 derives an even
  # height; left at the capture size, trunc()*2 rounds a stray odd edge down
  # and resamples nothing.
  local mp4_scale="scale=trunc(iw/2)*2:trunc(ih/2)*2"
  if [ -n "$MP4_WIDTH" ]; then
    mp4_scale="scale=${MP4_WIDTH}:-2:flags=lanczos"
  fi
  # Playwright records at MP4_FPS already, so the fps filter is a no-op on the
  # body and is there for the card's sake: concat wants one timebase, and
  # 0.8s of still has to become a whole number of frames somewhere.
  ffmpeg -nostdin -loglevel error -y \
    -loop 1 -t "$CARD_SECONDS" -framerate "$MP4_FPS" -i "$card" \
    -i "$source" \
    -filter_complex "\
      [0:v]${mp4_scale},setsar=1,format=yuv420p[card]; \
      [1:v]${trim}fps=${MP4_FPS},${mp4_scale},setsar=1,format=yuv420p[body]; \
      [card][body]concat=n=2:v=1[v]" \
    -map "[v]" \
    -c:v libx264 -pix_fmt yuv420p -crf 26 -preset veryfast \
    -movflags +faststart "$out_dir/demo.mp4"

  check_endings "$source" "$out_dir"
}

# Both encodes have to end on the held AFTER shot, and neither used to be
# checked: the defect that opened THE-295 was one frame out of 483, it survived
# the duration check, the file-size report and two reviews, and it was the
# frame a player holds after playback stops. demo/lib/lastframe.py says what
# "ends on a held shot" means in assertable terms.
#
# The capture size is asserted on the mp4 because MP4_WIDTH is empty by default
# and the mp4 is then supposed to be exactly what Playwright recorded; the GIF
# is deliberately resampled, so only its width is a stated number.
check_endings() {
  local source="$1" out_dir="$2" py capture_w capture_h
  py="$(pw_python)" || return 1

  capture_w="$(ffprobe -v error -select_streams v:0 -show_entries stream=width \
    -of csv=p=0 "$source")"
  capture_h="$(ffprobe -v error -select_streams v:0 -show_entries stream=height \
    -of csv=p=0 "$source")"

  pw_log "checking both encodes end on the held shot"
  local checker="$(dirname "${BASH_SOURCE[0]}")/lastframe.py"

  if [ -n "$MP4_WIDTH" ]; then
    "$py" "$checker" "$out_dir/demo.mp4" --width "$MP4_WIDTH"
  else
    "$py" "$checker" "$out_dir/demo.mp4" --width "$capture_w" --height "$capture_h"
  fi
  "$py" "$checker" "$out_dir/demo.gif" --width "$GIF_WIDTH"
}

recipe_record() {
  local out_dir="$1" raw="$1/raw" py scene card
  scene="${SCENE:-$DEMO_DIR/scene.py}"
  [ -f "$scene" ] || { echo "playwright.sh: no scene at $scene" >&2; return 1; }
  py="$(pw_python)"
  card="$out_dir/poster.png"

  mkdir -p "$raw"
  ( cd "$REPO_ROOT" && "$py" "$scene" --video-dir "$raw" --poster "$card" )

  local source
  source="$(find "$raw" -name '*.webm' -type f | head -1)"
  if [ -z "$source" ]; then
    echo "playwright.sh: the scene produced no video" >&2
    return 1
  fi

  # sheet.Scene leaves this beside the video; see encode_clip's lead-in note.
  # A scene that is not a sheet.Scene leaves none, and 0 is then the honest
  # answer — but say so, because a silently missing lead is the blank opening
  # frame coming back with nothing in the log to show it.
  local lead=0
  if [ -f "$raw/lead-seconds" ]; then
    lead="$(tr -d '[:space:]' < "$raw/lead-seconds")"
  else
    pw_log "no lead-seconds beside the video: nothing trimmed off the head"
  fi

  encode_clip "$source" "$out_dir" "$card" "$lead"
  rm -rf "$raw"
  RECIPE_CLIP="$out_dir/demo.gif"
}
