#!/usr/bin/env python3
"""Append a new benchmark run to results/manifest.json.

  python3 analysis/register.py \
      --dir results/2026-10-14_qwen3.6-27b-fp8_b \
      --model qwen3.6-27b-fp8 --label "Qwen 27B" \
      --variant "Qwen/Qwen3.6-27B-FP8" --repeats 3 \
      --notes "chunked prefill enabled"

The run directory must already contain the raw JSONs produced by bench/run.sh.
Raw files are never renamed - the manifest is what records which model they belong to.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "results" / "manifest.json"
SCENARIO_RE = re.compile(r"in(\d+)_out(\d+)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="run directory, relative to repo root")
    ap.add_argument("--model", required=True, help="stable model key, e.g. qwen3.6-27b-fp8")
    ap.add_argument("--label", required=True, help="display name used in tables")
    ap.add_argument("--date", help="YYYY-MM-DD; defaults to the run_id prefix")
    ap.add_argument("--variant", default="not recorded")
    ap.add_argument("--host", default="not recorded")
    ap.add_argument("--gpu", default="not recorded")
    ap.add_argument("--image", default="not recorded")
    ap.add_argument("--serve-config", default="not recorded")
    ap.add_argument("--bench-flags", default="vllm bench serve --dataset-name random")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--format", choices=["auto", "modern", "legacy"], default="auto")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    run_dir = ROOT / args.dir
    if not run_dir.is_dir():
        sys.exit(f"no such directory: {args.dir}")
    files = sorted(run_dir.glob("*.json"))
    if not files:
        sys.exit(f"{args.dir} contains no result JSONs")

    scenarios, bad = set(), []
    fmt = "modern" if "duration" in json.loads(files[0].read_text()) else "legacy"
    for path in files:
        if path.name.startswith("_"):
            continue  # sidecar capture files are not results
        m = SCENARIO_RE.search(path.name)
        if not m:
            bad.append(path.name)
        else:
            scenarios.add((int(m.group(1)), int(m.group(2))))
    if bad:
        sys.exit(f"file names without in<N>_out<N> cannot be ingested: {', '.join(bad)}\n"
                 f"add them to manifest 'excluded' by hand if they are intentional.")

    manifest = json.loads(MANIFEST.read_text())
    run_id = run_dir.name
    if any(r["run_id"] == run_id for r in manifest["runs"]):
        sys.exit(f"run_id {run_id} already in manifest")

    date = args.date or (run_id.split("_")[0] if re.match(r"\d{4}-\d{2}-\d{2}", run_id) else None)
    if not date:
        sys.exit("could not infer date from run_id; pass --date YYYY-MM-DD")

    entry = {
        "run_id": run_id,
        "model": args.model,
        "label": args.label,
        "variant": args.variant,
        "date": date,
        "host": args.host,
        "gpu": args.gpu,
        "vllm_image": args.image,
        "serve_config": args.serve_config,
        "bench_flags": args.bench_flags,
        "repeats": args.repeats,
        "result_format": args.format if args.format != "auto" else fmt,
        "notes": args.notes,
        "dir": args.dir,
    }
    manifest["runs"].append(entry)
    manifest["runs"].sort(key=lambda r: (r["date"], r["model"], r["run_id"]))
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"registered {run_id}: {len(scenarios)} scenarios, format={entry['result_format']}")
    print("next: make ingest report && git add results/manifest.json data/ README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
