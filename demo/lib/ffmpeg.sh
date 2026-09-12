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

FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"

# shellcheck source=fetch.sh
. "$(dirname "${BASH_SOURCE[0]}")/fetch.sh"

ffmpeg_log() { printf '  %s\n' "$*" >&2; }

ensure_ffmpeg() {
  local bin="${TOOLCHAIN_DIR:?ffmpeg.sh needs TOOLCHAIN_DIR}/bin"
  mkdir -p "$bin"
  if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    return 0
  fi
  if [ -x "$bin/ffmpeg" ] && [ -x "$bin/ffprobe" ]; then
    export PATH="$bin:$PATH"
    return 0
  fi

  ffmpeg_log "fetching ffmpeg (static build)"
  local work
  work="$(mktemp -d)"
  if ! fetch_url "$FFMPEG_URL" "$work/ffmpeg.tar.xz"; then
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
