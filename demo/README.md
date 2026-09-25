# demo/ — the recording pipeline

One command regenerates a clip from scratch, headless, from a clean checkout:

```bash
./demo/record.sh              # this piece: Playwright, a rendered page
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
byte-identical to the previous piece's copies, and `record.sh` now is too:
piece #2 (`catalog-watch`) took the `--fresh` line and taught its `setup.sh`
the flag, and piece #4 (`inbox-filer`) was started from this copy. `pdf-to-csv` was the
pre-split generation and carried seven declared exceptions; THE-255 moved it
onto this same lib so it could record a scene too, and deleted all seven.

That sync was a day late and nothing noticed, because the drift check read only
`demo/lib/` and `record.sh` sits one directory up. It reads all of `demo/` now,
so the next copy that stops at three of four is a failing check rather than a
diff somebody happens to run.

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

## The spreadsheet renderer, `lib/sheet.py`

All four pieces end their clip on the file the run just wrote, open in a
spreadsheet grid. That is one job, so it is one file — shared, byte-identical
everywhere, and policed like the rest of `lib/` by a drift checker that lives
in the maintainers' working tree and does not ship inside this repo.
What stays per-piece is `scene.py`: which files this piece opens, which of its
columns are worth showing, and what the narration says.

**It cannot render a table it was handed.** The only way in is
`read_table(path)` or `read_dir(path)`, both of which open something real and
raise if it is not there. `View` cannot be built without a `Table` and `Table`
cannot be built without a file on disk. That is deliberate: a terminal ASCII
table cannot be told apart from a mock-up, and a renderer that reads a fixture
reproduces exactly that flaw with better borders.

**A filtered view says it is filtered.** Showing six of twenty-one columns is
fine and is normal — nobody wants twenty-one on screen. So the columns keep the
letter they have in the source file (picking columns 1, 2, 4 and 9 renders as
A, B, D, I, which is what hiding columns in Excel looks like), rows keep their
real sheet row number so a filtered set reads 2, 3, 4, 287, 288 with the join
marked, and the footer says how many of each are on screen out of how many are
in the file.

**The number format is honoured.** A price cell holding 1299 with a `0.00`
format reads "1299.00" in Excel and "1299" if you only look at the value —
while the CSV beside it says "1299.00". Rendering the value alone would put a
difference on screen that does not exist in the file.

**The command and its output come from one call.** `run_command` runs the
argv, keeps the captured stdout with it, and `terminal_html` renders that one
object — so the line on screen cannot drift from the output underneath it. The
interpreter path is the one thing rewritten, to `python`, because
`/home/somebody/repo/.venv/bin/python3.12` is machine-specific noise and not
the thing being demonstrated.

Covered by `tests/test_demo_sheet.py`, which is byte-identical in all four
repos for the same reason the module is.

## The title card, `lib/card.py`

Every clip opens on 0.8 s of dark frame: this piece's before artifact on the
left under a white label, its after artifact on the right under a green one,
one line of specifics beneath each. The same render is exported beside the
clips as `demo/out/poster.png`, for a platform that wants a cover image rather
than a video.

It exists because frame 0 is a thumbnail. Freelancer derives a video's poster
from frame 0, and this README embeds the `.gif`, whose first frame is what a
reader sees before deciding whether to press play. Frame 0 used to be a
spreadsheet on pale paper, which at that size is a blank white rectangle
(THE-285).

**The two panels are the run's own frames.** `Scene.panel` screenshots whatever
is on screen at that beat, so there is no artwork to go stale: change the
fixture and the card follows it exactly the way the clip does. It is generated
for the same reason the clip is — a hand-made card is correct once.

**The generator is shared and the captions are not.** `lib/card.py` draws it
and is byte-identical in all four repos; the two labels and the two detail
lines are in `scene.py`, built out of tables the scene has already read, so no
number on the card is missing from the clip behind it. Each string is
auto-sized to fit its half, and one that still does not fit at the smallest
size allowed stops the recording rather than being ellipsised in front of a
client.

**The face is vendored, and the machine's own fonts are put out of reach.**
Auto-sizing makes the metrics load-bearing — the same HTML against a different
face is a different card, and on a box with neither Ubuntu nor DejaVu it is a
label overhanging the divider. So `lib/fonts.sh` fetches a pinned DejaVu,
checks it against a literal sha256, and writes a fontconfig declaring that one
directory and pulling in no system config; the card gets its own Chromium with
`FONTCONFIG_FILE` pointing at it. `card.font_probe` proves that rather than
asserting it: it measures one string under three family names, one of which is
a family that exists nowhere, and under that config all three come back the
same width because there is one face left to resolve to.
`tests/test_demo_card.py` runs it both ways, because without the control arm
the same check would pass on a machine with no fonts installed at all.

**That check does not run under a plain `make test`, and a green suite is not
it passing.** It needs three variables only `lib/playwright.sh` exports, so
under a bare pytest it skips — and on the summary line a skip and a pass are
the same word-shape. `./demo/record.sh` runs it by construction, and the skip
message names the exact command otherwise. Measured on 2026-09-24: jailed, the
three probe families come back `[683, 683, 683]`; with the jail lifted on the
same box, `[678.9, 563.7, 683]`. The other checks in that file — the card in
the GIF, the card in the mp4, the poster matching frame 0 — do run under `make
test`, and the GIF one needs nothing but the standard library.

The recording's own Chromium is untouched. The scene frames are drawn with the
system stack `lib/sheet.py` names and are unchanged by this: the card is a
prepend and an export, not a re-cut.

## Which recipe

**All four pieces use Playwright today**, and the reason is the grid
above: a spreadsheet frame is a rendered page, and the terminal recipe
cannot draw one. This piece records a browser because its deliverable is a
spreadsheet: the clip closes on `out/clean.xlsx`, the Clean sheet and then the
Rejects sheet. The VHS sibling is still live in every
repo — `make demo-terminal` — because the choice is the point of
`demo/recipe`, and a recipe nobody can run is a recipe that has rotted.

| | **VHS** (`lib/vhs.sh`) | **Playwright** (`lib/playwright.sh`) |
| --- | --- | --- |
| Records | A terminal session | A real browser page |
| You write | `demo.tape` — a script of keystrokes and pauses | `scene.py` — Playwright code |
| Good at | Crisp text at small sizes; smaller files | Anything with a UI, a page, or a before/after to point at |
| Bad at | Anything that is not text in a terminal | Files are several times bigger |
| Timing | Declarative `Sleep 4s` | `page.wait_for_timeout(4000)` — same idea, in Python |
| Output | GIF **and** MP4, from one recording | GIF **and** MP4, from one recording |

Both recipes write both formats because the two are for different places. The
**GIF** is the README thumbnail: it animates inline on GitHub and needs no
player. The **MP4** is the portfolio cover, because Upwork's gallery renders an
uploaded GIF as a single static first frame — a GIF there is a screenshot with
extra bytes. Neither is generated from the other; they are two encodes of the
same captured frames, so they cannot drift apart.

## Copying this into another piece

Copy the whole `demo/` folder. Then change **these files and nothing else**:

| File | What to change |
| --- | --- |
| `recipe` | One word: `playwright` or `vhs`. |
| `setup.sh` | Two lines in practice: the import names you pass `ensure_venv`, and whatever the piece needs regenerated before recording. A non-Python piece replaces the `ensure_venv` call with its own build. Anything it deletes belongs under `--fresh` unless the piece itself owns it — every `make` target runs this file, so a wipe outside that flag is a wipe of the user's work. |
| `demo.tape` | The VHS recipe's tape. Delete it if you only want the browser one. |
| `scene.py` | The Playwright recipe's script: which files to open, which columns to show, what the narration says, and the two labels and two detail lines of the title card. The rendering is `lib/sheet.py` and `lib/card.py` and is not yours to edit. |

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
| `lib/ffmpeg.sh` | ffmpeg, ffprobe | 7.0.2 | Checksum-verified against a constant in the file, so a swapped tarball fails instead of quietly changing what the clip looks like. A system `ffmpeg` is used only if it reports the same version. |
| `lib/vhs.sh` | vhs, ttyd | 0.10.0, 1.7.7 | **vhs deliberately**: 0.12.x starts Chromium, captures every frame, then exits 0 having written no file at all on some Linux hosts. 0.10.0 encodes reliably. |
| `lib/playwright.sh` | the `playwright` wheel + Chromium | 1.47.0 | The recipe this piece records with. Playwright for *Python*, not Node: the wheel ships its own driver, so a machine with no Node can still regenerate the clip. |
| `lib/chromium-libs.sh` | the shared objects Chromium links against | — | See below. |
| `lib/fonts.sh` | DejaVu Sans, Book and Bold | 2.37 | The title card's face. Checksum-verified against a constant in the file, and the fontconfig it writes declares only the directory it unpacked into. The card auto-sizes its labels, so the face's metrics decide the layout — "whatever `fc-list` returns on this box" is not something `make demo` can reproduce elsewhere. |

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
