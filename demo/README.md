# demo/ — the recording pipeline

One command regenerates a clip from scratch, headless, from a clean checkout:

```bash
./demo/record.sh              # this piece: VHS, a terminal session
./demo/record.sh --clean      # throw the toolchain away and re-fetch it first
```

No screen capture, no window manager, no display server, no root. Everything
the recording needs is fetched into `demo/.toolchain/` and nothing is installed
system-wide. `record.sh` fails loudly if the clip is missing, empty, or longer
than 35 seconds.

This is the **third** piece to use this pipeline. It wrote the three files a
piece is supposed to write — `recipe`, `setup.sh`, `demo.tape` — and it also
changed the shared half three times. All three are described below, and none
was forked into this piece: the rule is that editing `lib/` to make your own
piece work means the split is wrong, so you fix the split and say so.

- **`lib/fetch.sh` is new.** Mid-verification, GitHub's release CDN returned
  HTTP 500 for one asset (ttyd) for about two minutes while every other asset
  on the same host served fine. `make demo` died on a raw `curl: (22)`. A repo
  whose whole promise is "one command, from nothing" cannot have a two-minute
  CDN blip as a failure mode, so every download in `lib/` now goes through one
  retry helper. Nothing about that is specific to this piece.
- **`lib/preview.py` gained `--wrap`.** Documented under *Writing a tape*
  below. This piece is the first to put the helper on camera, which made it
  the cheapest moment to change it: with one caller a change costs nothing,
  with two it is a migration nobody wants to do.
- **`record.sh` now calls `setup.sh --fresh`.** This piece shipped with the
  output wipe inside `setup.sh` itself, which every `make` target depends on,
  so `make test` deleted the output of the last `make run` without a word.
  Wanting an empty repo is the *recording's* requirement, not setup's, so the
  flag is where that requirement now lives. Only `record.sh` passes it; what
  "fresh" means stays in `setup.sh`, because only the piece knows which
  directories it writes. A piece that has nothing to wipe can ignore the flag.
  `tests/test_make_targets.py` in the repo root holds the line.

`lib/python-venv.sh`, `lib/playwright.sh` and `lib/chromium-libs.sh` are
byte-identical to the previous piece's copies. `record.sh` differs by the one
line above, which is a change the previous pieces should take next time one of
them is opened — their `setup.sh` files ignore an unknown argument, so the new
`record.sh` works unchanged in both.

The history explains why the files are shaped the way they are:

- **Piece #1** had one recipe, VHS, wired straight into the orchestrator.
- **Piece #2** added the browser recipe, so the orchestrator now **picks** a
  recipe instead of being one. Two things moved *into* `lib/` at the same time,
  because they were about to be copy-pasted into a third piece: the
  venv/uv/ensurepip ladder (`lib/python-venv.sh`) and the CSV table renderer
  (`lib/preview.py`).
- **Piece #3** — this one — is the test of that. It is a terminal piece whose
  whole story is "dirty CSV in, clean CSV out", so it uses the VHS recipe and
  leans on `lib/preview.py` for three of its four beats. Nothing had to *move*
  this time: the two shared-half changes above are a new helper and a new
  option, not a per-piece file being promoted out of one. That is the split
  working — the pressure landed on `lib/`, which is where it belongs.

## Which recipe

| | **VHS** (`lib/vhs.sh`) | **Playwright** (`lib/playwright.sh`) |
| --- | --- | --- |
| Records | A terminal session | A real browser page |
| You write | `demo.tape` — a script of keystrokes and pauses | `scene.py` — Playwright code |
| Good at | Crisp text at small sizes; small files (this repo: 513 KB) | Anything with a UI, a page, or a before/after to point at |
| Bad at | Anything that is not text in a terminal | Files are several times bigger |
| Timing | Declarative `Sleep 4s` | `page.wait_for_timeout(4000)` — same idea, in Python |
| Output | GIF | GIF **and** MP4, from one recording |

**Pick VHS when the deliverable is a command.** This piece qualifies: what the
client cares about is a table of dirty rows, a table of clean rows and a table
of rejected rows, and VHS renders text natively rather than photographing it.
Both recipes are live in the repo so the next piece can choose rather than
reinvent — this one simply has no `scene.py`, which is why `demo/recipe` says
`vhs`.

## Copying this into another piece

Copy the whole `demo/` folder. Then change **these files and nothing else**:

| File | What to change |
| --- | --- |
| `recipe` | One word: `playwright` or `vhs`. |
| `setup.sh` | Two lines in practice: the import names you pass `ensure_venv`, and whatever the piece needs regenerated before recording. A non-Python piece replaces the `ensure_venv` call with its own build. Anything it deletes belongs under `--fresh` unless the piece itself owns it — every `make` target runs this file, so a wipe outside that flag is a wipe of the user's work. |
| `demo.tape` | The VHS recipe's tape. Delete it if you chose Playwright. |
| `scene.py` | The Playwright recipe's script. Not present in this piece; copy it from the previous one if you want the browser recipe. |

Leave `record.sh` and everything in `lib/` alone. If you find yourself editing
one of those to make your piece work, the split is wrong — fix the split, do
not fork the file.

## Adding a recipe

A recipe is `demo/lib/<name>.sh` defining exactly two functions:

```bash
recipe_bootstrap          # fetch what it needs: no root, inside the repo
recipe_record OUT_DIR     # leave a clip in OUT_DIR; set RECIPE_CLIP to it
```

`record.sh` handles the rest: reading `demo/recipe`, running `setup.sh --fresh`,
wiping the clip directory it is about to write, and checking the clip exists, is
non-empty and is inside the time budget. `DEMO_RECIPE=<name> ./demo/record.sh` overrides the
choice for one run; `DEMO_OUT_DIR=...` sends the clip somewhere else.

## Writing a tape (VHS)

`demo.tape` is [VHS tape syntax](https://github.com/charmbracelet/vhs#vhs-command-reference).

- **Set the height to fit the tallest *single* screen, not the tallest total.**
  Use `Hide` / `Type "clear"` / `Enter` / `Show` between beats. The tallest
  screen here is a seven-row table — ten lines of output, a comment and a
  command — so `Height 320`. A short frame is far more readable in a proposal
  thumbnail than a tall one full of dead space.
- **Set the width so the longest command does not wrap.** A wrapped command
  line costs a row of the frame and reads as a mistake. `Width 1400` here,
  because the "before" preview names six columns, two of them quoted.
- **Hide the setup.** Activating a venv or exporting variables goes in a `Hide`
  block so it never appears in the clip.
- **`Sleep` after each `Enter`**, long enough to read the output. 4 seconds is
  about right for a table.
- **No `Output` line.** `record.sh` passes `vhs -o` so the clip goes where it
  was asked to go.
- **Show a CSV with `lib/preview.py`, not `cat`.** Raw CSV wraps, and a wrapped
  line is unreadable at GIF sizes. The helper picks columns, caps rows,
  truncates cells with `…` and right-aligns numeric columns:

  ```bash
  python demo/lib/preview.py out/clean.csv sku title vendor price weight_g stock_status --rows 7
  ```

  It prints `... and 291 more rows (298 total)` under a capped table, on
  purpose: a clip that shows seven rows of a 298-row file should say so.
  Naming a column the file does not have is an error listing the ones it does,
  rather than a blank column that looks fine on camera. Tested in
  `tests/test_demo_preview.py`.
- **Wrap a prose column instead of truncating it: `--wrap COL`.** A rejects
  file's `reason` is a sentence, not a field, and a fixed-width cell cuts it
  exactly where it stops being boilerplate and starts being the explanation.
  This piece's last beat is the case for it:

  ```bash
  python demo/lib/preview.py out/rejects.csv line sku reject_rules reason \
      --rows 3 --cell 62 --wrap reason
  ```

  The wrapped column takes as many lines as it needs at `--cell` width, the
  other columns stay blank on the continuation lines, and `--rows` still counts
  *records* rather than screen lines — so the footer does not claim to have
  skipped rows it actually displayed. Budget roughly three screen lines per
  record when you set `Height`.
- **Two rows that differ in the file must not render as the same line.** The
  reason `--wrap` exists at all is that the two unresolved-duplicate rows came
  out byte-identical on screen while differing in the file — same class of lie
  as a capped table pretending to be the whole file. Adding the `line` column
  fixed the rest of it: it is what tells the tied rows apart, and it is what
  someone hand-fixing the feed actually needs.
- **Put the same rows on screen before and after.** Both preview beats here
  show `NW-1000` through `NW-1018` in the same column order, so the eye can
  compare cell to cell instead of taking the claim on trust. That is only
  possible because the tool preserves input order — worth knowing before you
  design the tape.
- **Lead with the specifics anyway.** The unresolved-duplicate message puts the
  two conflicting prices in its first eighty characters. `--wrap` means the
  whole sentence now reaches the screen, so this is no longer load-bearing —
  but a reject message is read in a hurry, in a terminal, by someone who is
  already annoyed, and front-loading the specifics is right whether or not the
  renderer would have cut them.
- **Synthetic data only.** Every product, vendor, sku and barcode in the clip
  is invented. Check every frame before shipping.

## Toolchain

Everything lands in `demo/.toolchain/` (gitignored). Nothing system-wide, no
root, versions pinned except where noted.

| File | Fetches | Pin | Why pinned |
| --- | --- | --- | --- |
| `lib/fetch.sh` | nothing itself | — | Every download below goes through it: a few attempts, a widening gap, and a message that separates "the host is having a moment" from "the URL is wrong". Failure is fatal for vhs (no recording without it) and a fallback for uv (there is still `python3 -m venv`). |
| `lib/uv.sh` | uv | 0.12.13 | Checksum-verified against the published `.sha256`. |
| `lib/python-venv.sh` | nothing directly | — | The venv ladder. Calls `lib/uv.sh` when the machine has no uv. |
| `lib/ffmpeg.sh` | ffmpeg, ffprobe | **current release, not pinned** | The static build publishes one URL for the newest version; there is no per-version URL to pin to. A system `ffmpeg` is used if present. |
| `lib/vhs.sh` | vhs, ttyd | 0.10.0, 1.7.7 | **vhs deliberately**: 0.12.x starts Chromium, captures every frame, then exits 0 having written no file at all on some Linux hosts. 0.10.0 encodes reliably. |
| `lib/playwright.sh` | the `playwright` wheel + Chromium | 1.47.0 | Unused by this piece; kept so the next one can choose it. |
| `lib/chromium-libs.sh` | the shared objects Chromium links against | — | See below. |

`lib/uv.sh` applies the pinning rule to the *project's* toolchain, because a
clean checkout is not a clean machine. Stock Ubuntu 24.04 has no `uv` and a
`python3` with no `ensurepip` (that lives in the separate `python3-venv`
package), so `setup.sh` would stop dead there and take `make test`, `make run`
and `make demo` with it. It fetches a pinned uv into `demo/.toolchain/bin`, and
uv then supplies the interpreter too, so the machine does not need a Python
3.12 of its own.

VHS drives a headless Chromium that it downloads itself into `~/.cache/rod`,
and on a server image that browser is missing the desktop libraries it links
against. `playwright install-deps` and `apt-get install` both want root, which
a demo script has no business asking for. So `lib/chromium-libs.sh` runs `ldd`,
works out exactly which `.so` files are missing, fetches those `.deb`s with
`apt-get download` (no root) and unpacks them into `demo/.toolchain/sysroot`.
It loops up to three times, because unpacking one library reveals the next one
down. On a non-Debian host it prints the library names and stops rather than
guessing.

## Known limits

- **x86_64 Linux.** The pinned ttyd and ffmpeg URLs are architecture-specific.
  macOS would need `brew install vhs ttyd ffmpeg` and a small edit.
- **The first run downloads a browser**, because that is how VHS renders a
  terminal. Measured numbers from a dead clone with an empty `HOME` and
  `PATH=/usr/bin:/bin` are in the top-level README.
- **The clip is a GIF.** The VHS recipe produces one file; the Playwright
  recipe is the one that also gives you an MP4 alongside it.
