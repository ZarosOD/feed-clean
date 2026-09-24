#!/usr/bin/env bash
# Pinned typeface for the title card, fetched into the repo. Generic: do not
# edit this file per project.
#
# Nothing runs at source time. Usage:
#
#   . "$DEMO_DIR/lib/fonts.sh"
#   ensure_card_font       # vendors the face, exports CARD_FONTCONFIG_FILE
#
# Needs TOOLCHAIN_DIR set by the caller.
#
# --- why a font is part of the toolchain ------------------------------------
#
# demo/.toolchain/ vendors ffmpeg, uv and Chromium because what the clip looks
# like is a function of each of them. It vendored no font, and until the title
# card that was survivable: the grid frames name "Ubuntu", "DejaVu Sans" and
# then a stack of last resorts, so a box with a different font draws slightly
# different column widths and the frame still says what it says.
#
# The card is not survivable that way. Its label is auto-sized to fit its half
# of a 1280px frame, so the *metrics* decide the layout: the same HTML against
# a different face is a different card, and on a box with neither Ubuntu nor
# DejaVu it is a card with the label overhanging the divider. A clip whose
# first frame depends on what `fc-list` happens to return on the machine that
# recorded it is not reproducible by `make demo`, which is the whole claim.
#
# So: one pinned tarball, checked against a literal sha256 (a constant here,
# not a sibling file fetched from the same origin — that is what makes it a pin
# and not a corruption check), and a fontconfig file that points at the two
# faces we unpacked **and at nothing else**.
#
# --- the fontconfig file is the load-bearing part ---------------------------
#
# Vendoring a TTF next to a browser that can still see /usr/share/fonts buys
# nothing: "DejaVu Sans" would resolve to whichever DejaVu fontconfig prefers,
# and this box's is a different build from the tarball below (measured: the
# same string at the same size comes out 678.9px against the system copy and
# 683px against ours). CARD_FONTCONFIG_FILE is handed to the card's own
# Chromium as FONTCONFIG_FILE, and it declares exactly one <dir>. Every family
# name in the card's CSS — and every family name that is *not* in it — resolves
# to the vendored face, because there is no other face to resolve to.
#
# demo/lib/card.py proves that rather than asserting it: font_probe() renders
# one string under three family names, one of which cannot exist, and the three
# widths are equal under this config and unequal without it. tests/
# test_demo_card.py is the caller.
#
# This is deliberately *not* exported into the recording's Chromium. The scene
# frames are unchanged by this card and must stay that way, and they are drawn
# with the system stack sheet.py names.

DEJAVU_VERSION="2.37"
DEJAVU_URL="https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_${DEJAVU_VERSION//./_}/dejavu-fonts-ttf-${DEJAVU_VERSION}.tar.bz2"
DEJAVU_SHA256="fa9ca4d13871dd122f61258a80d01751d603b4d3ee14095d65453b4e846e17d7"

# The two faces the card draws with, and the licence that has to travel with
# them. DejaVu is Bitstream Vera-derived and its licence requires the notice to
# ship alongside; it lands in the toolchain, which is gitignored, so `make
# demo` puts it there on every clean checkout rather than the repo carrying it.
DEJAVU_FILES="ttf/DejaVuSans-Bold.ttf ttf/DejaVuSans.ttf LICENSE"

# shellcheck source=fetch.sh
. "$(dirname "${BASH_SOURCE[0]}")/fetch.sh"

fonts_log() { printf '  %s\n' "$*" >&2; }

fonts_verify_checksum() {
  local tarball="$1" actual
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$tarball" | cut -d' ' -f1)"
  elif command -v shasum >/dev/null 2>&1; then
    actual="$(shasum -a 256 "$tarball" | cut -d' ' -f1)"
  else
    fonts_log "no sha256sum or shasum available; skipping checksum verification"
    return 0
  fi
  [ "$actual" = "$DEJAVU_SHA256" ]
}

# A fontconfig that can see the vendored directory and nothing else.
#
# <cachedir> is inside the toolchain for the same reason the browser is: a
# recording must not write outside the repo, and a cache under ~/.cache would
# survive `record.sh --clean` and could hold entries for fonts this config is
# supposed to be unable to see.
#
# No <include> of /etc/fonts/conf.d, on purpose. Those snippets add system
# directories back, and one of them re-aliasing "sans-serif" to a system face
# would undo the isolation silently — the card would still render, just not
# with the face we pinned.
_write_fontconfig() {
  local dir="$1" conf="$2"
  mkdir -p "$dir/cache"
  cat >"$conf" <<XML
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<!-- Written by demo/lib/fonts.sh. One directory, no includes: see the comment
     there for why pulling in the system conf.d would undo this. -->
<fontconfig>
  <dir>$dir</dir>
  <cachedir>$dir/cache</cachedir>
</fontconfig>
XML
}

# Puts the pinned faces in $TOOLCHAIN_DIR/fonts and exports:
#
#   CARD_FONT_DIR          where the .ttf files are
#   CARD_FONTCONFIG_FILE   the config that can see only that directory
#
# Both are read by demo/lib/card.py. A failure here is fatal to the recording
# rather than a fallback, unlike uv.sh: falling back to the system stack is
# exactly the unreproducible card this exists to prevent, and it would fail
# silently and look fine on the box that recorded it.
ensure_card_font() {
  local root="${TOOLCHAIN_DIR:?fonts.sh needs TOOLCHAIN_DIR}/fonts"
  local conf="$root/fonts.conf"
  local bold="$root/DejaVuSans-Bold.ttf"

  export CARD_FONT_DIR="$root"
  export CARD_FONTCONFIG_FILE="$conf"

  if [ -s "$bold" ] && [ -s "$root/DejaVuSans.ttf" ]; then
    # The config is rewritten even when the faces are already here: it carries
    # an absolute path, and a repo that moved directories would otherwise keep
    # pointing a browser at somewhere that no longer exists.
    _write_fontconfig "$root" "$conf"
    return 0
  fi

  mkdir -p "$root"
  local tarball="$root/.dejavu.tar.bz2"
  fonts_log "downloading DejaVu $DEJAVU_VERSION into demo/.toolchain/fonts (~5 MB, once)"
  fetch_url "$DEJAVU_URL" "$tarball" || {
    fonts_log "the title card needs a pinned face and could not fetch one"
    return 1
  }

  if ! fonts_verify_checksum "$tarball"; then
    fonts_log "sha256 mismatch on $(basename "$tarball") — refusing to unpack it"
    fonts_log "  expected $DEJAVU_SHA256"
    rm -f "$tarball"
    return 1
  fi

  # --strip-components=1 drops the dejavu-fonts-ttf-2.37/ prefix; the ttf/ one
  # below it is dropped by moving the two files up, so CARD_FONT_DIR is flat
  # and the <dir> above needs no recursion to reason about.
  #
  # Built as an array rather than with one printf over the whole list: printf
  # recycles its format string across the arguments, so a single call pairs
  # the version with the first path and then the second path with the third.
  local members=() member
  for member in $DEJAVU_FILES; do
    members+=("dejavu-fonts-ttf-${DEJAVU_VERSION}/${member}")
  done
  tar xjf "$tarball" --strip-components=1 -C "$root" "${members[@]}" || {
    fonts_log "could not unpack $(basename "$tarball")"
    rm -f "$tarball"
    return 1
  }
  mv -f "$root/ttf/DejaVuSans-Bold.ttf" "$root/ttf/DejaVuSans.ttf" "$root/" 2>/dev/null || true
  rmdir "$root/ttf" 2>/dev/null || true
  rm -f "$tarball"

  [ -s "$bold" ] || { fonts_log "the tarball left no DejaVuSans-Bold.ttf in $root"; return 1; }
  _write_fontconfig "$root" "$conf"
}
