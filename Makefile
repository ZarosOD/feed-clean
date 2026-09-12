PY := .venv/bin/python
FEED := fixtures/supplier-feed.csv

.PHONY: help setup run strict test fixtures demo clean

help:
	@echo "make run       clean the bundled dirty feed and print the summary"
	@echo "make strict    the same run, but exit non-zero if anything was rejected"
	@echo "make test      run the test suite"
	@echo "make fixtures  regenerate the synthetic feed and its ground truth"
	@echo "make demo      regenerate demo/out/demo.gif with VHS, headless"

setup:
	@./demo/setup.sh

# The headline: one dirty file in, four files out, and a screen that says what
# happened to every row.
run: setup
	@$(PY) clean.py $(FEED) --report --quiet

# What a scheduled import would run. Exit 2 means "rows were rejected, do not
# upload this yet"; exit 1 (with --fail-on-review) means "somebody should look".
strict: setup
	@$(PY) clean.py $(FEED) --report --quiet --fail-on-reject

test: setup
	@$(PY) -m pytest -q

fixtures: setup
	@$(PY) fixtures/generate_feed.py

demo:
	@./demo/record.sh

clean:
	rm -rf out demo/out demo/.toolchain demo/.scratch .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
