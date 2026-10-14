PY ?= python3

.PHONY: all ingest report figures verify check bench clean help

help:
	@echo "make ingest   # raw JSONs -> data/normalized.csv (integrity-checked)"
	@echo "make report   # data -> README tables + data/leaderboard.json"
	@echo "make figures  # data -> docs/figures/*.png (needs matplotlib)"
	@echo "make verify   # audit: data integrity + README freshness"
	@echo "make check    # CI entrypoint: fail if anything is stale"
	@echo "make bench MODEL=qwen3.6-27b-fp8 LABEL='Qwen 27B' URL=http://localhost:9000"

all: ingest report figures verify

ingest:
	$(PY) analysis/ingest.py

report: ingest
	$(PY) analysis/report.py

figures: report
	$(PY) analysis/figures.py

verify:
	$(PY) analysis/verify.py

# CI: regenerate in memory and fail if the committed files would change.
check:
	$(PY) analysis/ingest.py
	$(PY) analysis/report.py --check
	$(PY) analysis/verify.py

bench:
	@test -n "$(MODEL)" || { echo "usage: make bench MODEL=<key> LABEL='<display name>' URL=http://localhost:9000"; exit 2; }
	bench/run.sh --model "$(MODEL)" --label "$(LABEL)" --base-url "$(URL)" $(EXTRA)

clean:
	rm -rf analysis/__pycache__ .venv
