# The story: a supplier's weekly export arrives dirty, and one command turns it
# into a feed that will import — plus a rejects file naming every row it would
# not vouch for.
# EDIT THIS FILE for a new piece that records a terminal.
#
#   make demo        (or: ./demo/record.sh)
#
# There is no `Output` line on purpose: demo/record.sh passes `vhs -o` so the
# clip lands in whichever output directory it was asked for.
#
# Conventions that make a tape read well: set Height to the tallest *single*
# screen rather than the tallest total, clear between beats inside Hide blocks,
# hide the venv wiring, and sleep long enough after each Enter to actually read
# the output. The tallest screen here is a 7-row table: 10 lines of output, a
# comment and a command.

Set Shell bash
Set FontSize 15
Set Width 1400
Set Height 320
Set Padding 20
Set TypingSpeed 18ms
Set Theme "Catppuccin Mocha"

Hide
Type "export PS1='$ ' PATH=$PWD/.venv/bin:$PATH" Enter
Type "rm -rf out" Enter
Type "clear" Enter
Show

Type "# what the supplier sent" Enter
Sleep 700ms
Type `python demo/lib/preview.py fixtures/supplier-feed.csv "Variant SKU" Title Vendor "Variant Price" Weight "Stock Status" --rows 7` Enter
Sleep 4s

Hide
Type "clear" Enter
Show

Type "# one command: dedupe, normalise, validate, report" Enter
Sleep 700ms
Type "python clean.py fixtures/supplier-feed.csv --brief" Enter
Sleep 4s

Hide
Type "clear" Enter
Show

Type "# the same seven products, out of out/clean.csv" Enter
Sleep 700ms
Type "python demo/lib/preview.py out/clean.csv sku title vendor price weight_g stock_status --rows 7" Enter
Sleep 4s

Hide
Type "clear" Enter
Show

Type "# and what it refused to guess, in out/rejects.csv" Enter
Sleep 700ms
Type "python demo/lib/preview.py out/rejects.csv sku reject_rules reason --rows 5 --cell 96" Enter
Sleep 4s
