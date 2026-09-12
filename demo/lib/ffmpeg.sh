#!/usr/bin/env bash
# Pinned ffmpeg, fetched into the repo. Generic: do not edit per project.
#
# Both recipes need it — VHS to encode its frames, Playwright to turn the .webm
# it records into the .gif a README can embed — so it lives on its own rather
# than inside either one.
#
# Nothing runs at source time. Usage:
#
#   . "$DEMO_DIR/lib/ffmpeg.sh"
#   ensure_ffmpeg          # puts ffmpeg/ffprobe on PATH, or fails
#
# Needs TOOLCHAIN_DIR set by the caller.
#
# The version is pinned, the way vhs and ttyd are. What the clip looks like is a
# function of the encoder — palettegen and paletteuse defaults move between
# releases — and a clip `make demo` cannot reproduce is a clip nobody can re-cut.
# johnvansickle publishes the newest build under a "release" alias *and* under a
# versioned name; asking for the versioned one and checking it against a literal
# checksum means a swapped tarball fails loudly instead of quietly changing the
# recording. The checksum is a constant here rather than a sibling file fetched
# from the same origin, which is what makes it a pin and not just a corruption
# check.

FFMPEG_VERSION="7.0.2"
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-${FFMPEG_VERSION}-amd64-static.tar.xz"
FFMPEG_SHA256="abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67"

# shellcheck source=fetch.sh
. "$(dirname "${BASH_SOURCE[0]}")/fetch.sh"

ffmpeg_log() { printf '  %s\n' "$*" >&2; }

# An ffmpeg already on PATH is only worth using if it is the version we pinned.
# Anything else falls through to the download rather than silently recording a
# different-looking clip.
ffmpeg_version_matches() {
  local reported
  reported="$("$1" -version 2>/dev/null | head -1 | cut -d' ' -f3)" || return 1
  case "$reported" in "$FFMPEG_VERSION" | "$FFMPEG_VERSION"-*) return 0 ;; esac
  return 1
}

ffmpeg_verify_checksum() {
  local tarball="$1" actual
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$tarball" | cut -d' ' -f1)"
  elif command -v shasum >/dev/null 2>&1; then
    actual="$(shasum -a 256 "$tarball" | cut -d' ' -f1)"
  else
    ffmpeg_log "no sha256sum or shasum available; skipping checksum verification"
    return 0
  fi
  [ "$actual" = "$FFMPEG_SHA256" ]
}

ensure_ffmpeg() {
  local bin="${TOOLCHAIN_DIR:?ffmpeg.sh needs TOOLCHAIN_DIR}/bin"
  mkdir -p "$bin"
  # The build we vendored wins: once it is here, it is the one the committed
  # clip was cut with.
  if [ -x "$bin/ffmpeg" ] && [ -x "$bin/ffprobe" ]; then
    export PATH="$bin:$PATH"
    return 0
  fi
  if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1 &&
    ffmpeg_version_matches "$(command -v ffmpeg)"; then
    return 0
  fi

  ffmpeg_log "fetching ffmpeg $FFMPEG_VERSION (static build)"
  local work
  work="$(mktemp -d)"
  if ! fetch_url "$FFMPEG_URL" "$work/ffmpeg.tar.xz"; then
    rm -rf "$work"
    return 1
  fi
  if ! ffmpeg_verify_checksum "$work/ffmpeg.tar.xz"; then
    ffmpeg_log "checksum mismatch on the ffmpeg download; refusing to use it"
    rm -rf "$work"
    return 1
  fi
  tar xf "$work/ffmpeg.tar.xz" -C "$work"
  find "$work" -maxdepth 2 -name ffmpeg -type f -exec install -m 0755 {} "$bin/ffmpeg" \;
  find "$work" -maxdepth 2 -name ffprobe -type f -exec install -m 0755 {} "$bin/ffprobe" \;
  rm -rf "$work"

  export PATH="$bin:$PATH"
  [ -x "$bin/ffmpeg" ]
}
