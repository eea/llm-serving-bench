#!/usr/bin/env python3
"""Audit gate for the repo. Exits non-zero on any inconsistency.

Checks, in order:
  1. every raw JSON under results/ is either ingested or explicitly excluded
  2. every raw JSON is internally consistent (ingest re-runs the arithmetic)
  3. data/normalized.csv + data/normalized.jsonl match a fresh ingest
  4. README.md generated blocks match a fresh render (no hand-edited numbers)
  5. data/leaderboard.json matches a fresh render
  6. manifest sanity: unique run ids, existing dirs, no stale exclusions
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import ingest  # noqa: E402
import report  # noqa: E402

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {label}{'' if ok else f': {detail}'}")
    if not ok:
        failures.append(label)


def main() -> int:
    manifest_path = ROOT / "results" / "manifest.json"
    if not manifest_path.exists():
        print("FAIL results/manifest.json missing")
        return 1
    manifest = json.loads(manifest_path.read_text())

    # 6. manifest sanity -----------------------------------------------------
    run_ids = [r["run_id"] for r in manifest["runs"]]
    check(len(run_ids) == len(set(run_ids)), "manifest run_ids unique")
    for run in manifest["runs"]:
        check((ROOT / run["dir"]).is_dir(), f"run dir exists: {run['dir']}")
        check(isinstance(run.get("gpus", 1), int) and run.get("gpus", 1) >= 1,
              f"run {run['run_id']}: gpus is a positive integer")
    for entry in manifest.get("excluded", []):
        check((ROOT / entry["path"]).exists(), f"excluded path exists: {entry['path']}")

    # 1 + 2. ingest re-runs every arithmetic check on every raw file --------
    try:
        fresh = ingest.ingest()
    except ingest.IngestError as exc:
        check(False, "raw result files pass integrity checks", str(exc))
        return 1
    check(True, f"raw result files pass integrity checks ({len(fresh)} scenarios)")

    # 1b. coverage: no orphan run directories, counts reconcile -------------
    listed = {(ROOT / r["dir"]).resolve() for r in manifest["runs"]}
    raw_files = [p for p in sorted((ROOT / "results").glob("*/*.json"))
                 if not p.name.startswith("_")]
    orphan_dirs = {str(p.parent.relative_to(ROOT)) for p in raw_files
                   if p.parent.resolve() not in listed}
    check(not orphan_dirs, "every results/ subdirectory is declared in the manifest",
          ", ".join(sorted(orphan_dirs)))

    excluded = {e["path"] for e in manifest.get("excluded", [])}
    ingested = [p for p in raw_files if str(p.relative_to(ROOT)) not in excluded]
    check(len(ingested) == len(fresh), "raw file count reconciles with ingested rows",
          f"{len(ingested)} files on disk vs {len(fresh)} ingested rows")

    # 3. committed data freshness -------------------------------------------
    for name in ("normalized.csv", "normalized.jsonl"):
        path = ROOT / "data" / name
        if not path.exists():
            check(False, f"data/{name} committed", "file missing - run `make ingest`")
    import csv as _csv
    rows = list(_csv.DictReader((ROOT / "data" / "normalized.csv").open()))
    check(len(rows) == len(fresh), "data/normalized.csv row count matches fresh ingest",
          f"committed {len(rows)} vs fresh {len(fresh)}")
    mismatch = [r["source_file"] for r, f in zip(rows, fresh)
                if r["source_file"] != f["source_file"]
                or abs(float(r["total_tok_s"]) - f["total_tok_s"]) > 1e-6]
    check(not mismatch, "data/normalized.csv values match fresh ingest",
          ", ".join(mismatch[:5]))

    # 4 + 5. README / leaderboard freshness ----------------------------------
    agg = report.aggregate(report.load_rows())
    rendered = report.render(agg, manifest)
    original = (ROOT / "README.md").read_text()
    try:
        updated = report.inject(original, rendered)
    except SystemExit as exc:
        check(False, "README.md generated blocks", str(exc.code))
        return 1
    check(updated == original, "README.md generated blocks match the data",
          "run `make report` and commit")

    expected_lb = json.dumps(report.leaderboard_json(
        agg, {r["model"]: r["label"] for r in manifest["runs"]}, manifest), indent=2) + "\n"
    lb_path = ROOT / "data" / "leaderboard.json"
    check(lb_path.exists() and lb_path.read_text() == expected_lb,
          "data/leaderboard.json matches the data", "run `make report` and commit")

    print(f"\n{len(failures)} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
