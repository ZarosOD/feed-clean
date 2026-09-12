#!/usr/bin/env bash
# Project-specific preparation, run by every `make` target and by
# demo/record.sh before the recipe.
# EDIT THIS FILE for a new portfolio piece — but only these few lines: the
# venv/uv/ensurepip ladder is generic and lives in lib/python-venv.sh.
#
# It must be safe to run repeatedly and must leave the repo ready to record.
#
#   ./demo/setup.sh            prepare, and delete nothing a run produced
#   ./demo/setup.sh --fresh    also remove out/, for the recording only
#
# Every `make` target that needs a venv depends on `setup`, so plain setup.sh
# runs before `make run`, `make test`, `make strict` and `make fixtures`. It
# must therefore leave out/ alone: deleting the last run's output as a side
# effect of running the tests is exactly the silent, unlogged change this
# project exists to argue against. Only record.sh passes --fresh.

set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEMO_DIR/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '  %s\n' "$*" >&2; }

FRESH=0
for arg in "$@"; do
  case "$arg" in
    --fresh) FRESH=1 ;;
    *)
      echo "setup.sh: unknown argument '$arg' (the only option is --fresh)" >&2
      exit 2
      ;;
  esac
done

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

# demo/.scratch is this demo's own workspace, so it goes on every run: nobody
# else writes there and nothing in it is anyone's output.
rm -rf demo/.scratch

# out/ belongs to whoever last ran the tool, and --fresh is the recording
# saying "this scene must open on an empty repo", not a general-purpose clean.
# `make clean` is the one the reader can ask for by name.
if [ "$FRESH" = 1 ]; then
  log "removing out/ so the recorded first run really is a first run"
  rm -rf out
fi
