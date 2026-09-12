#!/usr/bin/env bash
# Project-specific preparation, run by demo/record.sh before the recipe.
# EDIT THIS FILE for a new portfolio piece — but only these few lines: the
# venv/uv/ensurepip ladder is generic and lives in lib/python-venv.sh.
#
# It must be safe to run repeatedly and must leave the repo ready to record.

set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEMO_DIR/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '  %s\n' "$*" >&2; }

# Generic: creates .venv however this machine allows, then proves the install
# by importing what this project actually needs. See lib/python-venv.sh, which
# fetches a pinned uv via lib/uv.sh when there is none. This tool has no
# runtime dependencies at all, so the import that proves the venv works is the
# test runner and the package itself.
# shellcheck source=lib/python-venv.sh
. "$DEMO_DIR/lib/python-venv.sh"
ensure_venv .venv "feed_clean pytest"

PY=".venv/bin/python"

# The dirty feed is committed, but regenerate it if the checkout lacks it.
if [ ! -f fixtures/supplier-feed.csv ] || [ ! -f tests/expected.json ]; then
  log "generating the synthetic supplier feed"
  "$PY" fixtures/generate_feed.py >/dev/null
fi

# Nothing from a previous run should appear in the recording: the scene starts
# with no output directory at all, so the first run really is a first run.
rm -rf demo/.scratch out
