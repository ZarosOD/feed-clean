#!/usr/bin/env bash
# Shared libraries for a headless Chromium, without root. Generic: do not edit
# per project.
#
# Both recipes end up driving a Chromium — VHS downloads one into ~/.cache/rod,
# Playwright downloads one into ~/.cache/ms-playwright — and on a server image
# neither has the desktop libraries it links against. `playwright install-deps`
# and `apt-get install` both want root, which a demo script has no business
# asking for.
#
# So: work out exactly which .so files are missing, fetch those .deb packages
# with `apt-get download` (no root), and unpack them into the toolchain.
#
# Nothing runs at source time. Usage:
#
#   . "$DEMO_DIR/lib/chromium-libs.sh"
#   vendor_chromium_libs                 # looks for any browser it knows about
#   vendor_chromium_libs /path/to/chrome # or a specific one
#
# Needs TOOLCHAIN_DIR set by the caller. Exports LD_LIBRARY_PATH additions.

# soname -> candidate package names, most likely first. Ubuntu's t64 transition
# renamed several of these, so each entry lists both spellings.
declare -A CHROMIUM_LIB_PACKAGES=(
  [libnss3.so]="libnss3"
  [libnssutil3.so]="libnss3"
  [libsmime3.so]="libnss3"
  [libnspr4.so]="libnspr4"
  [libplds4.so]="libnspr4"
  [libplc4.so]="libnspr4"
  [libasound.so.2]="libasound2t64 libasound2"
  [libatk-1.0.so.0]="libatk1.0-0t64 libatk1.0-0"
  [libatk-bridge-2.0.so.0]="libatk-bridge2.0-0t64 libatk-bridge2.0-0"
  [libatspi.so.0]="libatspi2.0-0t64 libatspi2.0-0"
  [libcups.so.2]="libcups2t64 libcups2"
  [libdbus-1.so.3]="libdbus-1-3"
  [libdrm.so.2]="libdrm2"
  [libgbm.so.1]="libgbm1"
  [libxkbcommon.so.0]="libxkbcommon0"
  [libpango-1.0.so.0]="libpango-1.0-0"
  [libpangocairo-1.0.so.0]="libpango-1.0-0"
  [libcairo.so.2]="libcairo2"
  [libX11.so.6]="libx11-6"
  [libXcomposite.so.1]="libxcomposite1"
  [libXdamage.so.1]="libxdamage1"
  [libXext.so.6]="libxext6"
  [libXfixes.so.3]="libxfixes3"
  [libXrandr.so.2]="libxrandr2"
  [libXrender.so.1]="libxrender1"
  [libXi.so.6]="libxi6"
  [libXtst.so.6]="libxtst6"
  [libxcb.so.1]="libxcb1"
  [libexpat.so.1]="libexpat1"
  [libgio-2.0.so.0]="libglib2.0-0t64 libglib2.0-0"
  [libglib-2.0.so.0]="libglib2.0-0t64 libglib2.0-0"
  [libgobject-2.0.so.0]="libglib2.0-0t64 libglib2.0-0"
  [libudev.so.1]="libudev1"
)

libs_log() { printf '  %s\n' "$*" >&2; }

# Where the two recipes' browsers land. Built at call time, not at source time,
# because the Playwright recipe points PLAYWRIGHT_BROWSERS_PATH into the
# toolchain after this file is sourced.
find_chromium() {
  local pattern candidate
  local -a globs=(
    "$HOME/.cache/rod/browser/*/chrome"
    "${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}/chromium-*/chrome-linux/chrome"
    "${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}/chromium_headless_shell-*/chrome-linux/headless_shell"
  )
  for pattern in "${globs[@]}"; do
    for candidate in $pattern; do
      [ -x "$candidate" ] && { printf '%s' "$candidate"; return 0; }
    done
  done
  return 1
}

missing_libraries() {
  LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}" ldd "$1" 2>/dev/null \
    | awk '/not found/ { print $1 }' | sort -u
}

# Add every directory holding a .so we unpacked to LD_LIBRARY_PATH.
_export_sysroot_path() {
  local sysroot="$1" extra
  extra="$(find "$sysroot" -name '*.so*' -printf '%h\n' 2>/dev/null | sort -u | tr '\n' ':')"
  [ -n "$extra" ] && export LD_LIBRARY_PATH="${extra}${LD_LIBRARY_PATH:-}"
}

vendor_chromium_libs() {
  local chrome="${1:-}" sysroot="${TOOLCHAIN_DIR:?chromium-libs.sh needs TOOLCHAIN_DIR}/sysroot"
  if [ -z "$chrome" ]; then
    chrome="$(find_chromium)" || return 0   # not downloaded yet; nothing to check
  fi

  # Pick up anything vendored on an earlier pass before deciding what is missing.
  [ -d "$sysroot" ] && _export_sysroot_path "$sysroot"

  local pass missing packages package unmapped
  # Unpacking one library can reveal the next one down, so go round a few times.
  for pass in 1 2 3; do
    missing="$(missing_libraries "$chrome")"
    [ -z "$missing" ] && return 0

    if ! command -v apt-get >/dev/null 2>&1 || ! command -v dpkg-deb >/dev/null 2>&1; then
      libs_log "headless Chromium is missing: $(echo "$missing" | tr '\n' ' ')"
      libs_log "install the matching packages for your distro, then re-run"
      return 0
    fi

    packages=""
    unmapped=""
    while read -r lib; do
      [ -z "$lib" ] && continue
      if [ -n "${CHROMIUM_LIB_PACKAGES[$lib]:-}" ]; then
        packages="$packages ${CHROMIUM_LIB_PACKAGES[$lib]}"
      else
        unmapped="$unmapped $lib"
      fi
    done <<<"$missing"

    if [ -n "$unmapped" ]; then
      libs_log "no package mapping for:$unmapped"
      libs_log "add it to CHROMIUM_LIB_PACKAGES in demo/lib/chromium-libs.sh"
    fi
    [ -z "${packages// /}" ] && return 0

    libs_log "vendoring Chromium libraries (pass $pass):$(echo $packages | tr ' ' '\n' | sort -u | tr '\n' ' ')"
    mkdir -p "$sysroot" "$TOOLCHAIN_DIR/debs"
    ( cd "$TOOLCHAIN_DIR/debs"
      for package in $(echo $packages | tr ' ' '\n' | sort -u); do
        # Candidates are tried in turn; names moved in the t64 transition.
        apt-get download "$package" >/dev/null 2>&1 || true
      done )
    for package in "$TOOLCHAIN_DIR/debs"/*.deb; do
      [ -e "$package" ] || continue
      dpkg-deb -x "$package" "$sysroot" 2>/dev/null || true
    done
    _export_sysroot_path "$sysroot"
  done

  missing="$(missing_libraries "$chrome")"
  if [ -n "$missing" ]; then
    libs_log "still missing after 3 passes: $(echo "$missing" | tr '\n' ' ')"
    return 1
  fi
}
