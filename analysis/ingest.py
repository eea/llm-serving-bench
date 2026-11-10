#!/usr/bin/env python3
"""Normalise every raw vLLM bench result file into one canonical table.

Reads   results/manifest.json + results/<run_id>/*.json
Writes  data/normalized.csv, data/normalized.jsonl

Raw files are treated as immutable: this script never rewrites them, and it
refuses to ingest a file whose internal numbers are inconsistent.

Two on-disk formats are supported and auto-detected:
  legacy  keys: elapsed_time, num_requests, total_num_tokens,
                requests_per_second, tokens_per_second
  modern  keys: duration, completed, failed, total_input_tokens,
                total_output_tokens, request_throughput, total_token_throughput,
                output_throughput, *_ttft_ms, *_tpot_ms, *_itl_ms
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
DATA = ROOT / "data"

COLUMNS = [
    "run_id", "model", "label", "date", "repeats", "src_format", "source_file",
    "in_len", "out_len", "prompts",
    "elapsed_s", "req_s", "total_tok_s", "out_tok_s", "out_tok_s_source",
    "ttft_mean_ms", "ttft_p50_ms", "ttft_p99_ms",
    "tpot_mean_ms", "tpot_p99_ms", "itl_mean_ms", "itl_p99_ms",
    # speculative decoding: None unless the server ran with a draft method
    "itl_median_ms", "spec_accept_len", "spec_accept_rate",
]

SCENARIO_RE = re.compile(r"in(\d+)_out(\d+)")


class IngestError(RuntimeError):
    pass


def load_manifest() -> dict:
    path = RESULTS / "manifest.json"
    if not path.exists():
        raise IngestError(f"missing {path}")
    return json.loads(path.read_text())


def detect_format(payload: dict) -> str:
    if "duration" in payload and "total_token_throughput" in payload:
        return "modern"
    if "elapsed_time" in payload and "tokens_per_second" in payload:
        return "legacy"
    raise IngestError(f"unrecognised result format, keys={sorted(payload)[:8]}")


def normalise(run: dict, path: Path, payload: dict) -> dict:
    m = SCENARIO_RE.search(path.name)
    if not m:
        raise IngestError(f"{path}: file name carries no in<N>_out<N> scenario")
    in_len, out_len = int(m.group(1)), int(m.group(2))
    fmt = detect_format(payload)

    if fmt == "modern":
        prompts = payload["completed"]
        elapsed = payload["duration"]
        total_tokens = payload["total_input_tokens"] + payload["total_output_tokens"]
        row = {
            "prompts": prompts,
            "elapsed_s": elapsed,
            "req_s": payload["request_throughput"],
            "total_tok_s": payload["total_token_throughput"],
            "out_tok_s": payload.get("output_throughput"),
            "ttft_mean_ms": payload.get("mean_ttft_ms"),
            "ttft_p50_ms": payload.get("median_ttft_ms"),
            "ttft_p99_ms": payload.get("p99_ttft_ms"),
            "tpot_mean_ms": payload.get("mean_tpot_ms"),
            "tpot_p99_ms": payload.get("p99_tpot_ms"),
            "itl_mean_ms": payload.get("mean_itl_ms"),
            "itl_p99_ms": payload.get("p99_itl_ms"),
            # median ITL is the honest per-step time; mean ITL is inflated by
            # chunked-prefill stalls (p99 ~660 ms in short-output runs).
            "itl_median_ms": payload.get("median_itl_ms"),
            # Speculative decoding changes what TPOT and ITL mean: one step emits
            # spec_accept_len tokens, so TPOT = ITL / spec_accept_len. A run with
            # spec decode is NOT comparable to one without it on either metric.
            # max_output_tokens_per_s is deliberately NOT ingested: it is broken
            # in the vLLM 0.32 output (below average output_throughput in 13 of
            # 16 files) - see docs/caveats.md.
            "spec_accept_len": payload.get("spec_decode_acceptance_length"),
            "spec_accept_rate": payload.get("spec_decode_acceptance_rate"),
        }
        if payload.get("failed"):
            raise IngestError(f"{path}: {payload['failed']} failed requests")
    else:
        prompts = payload["num_requests"]
        elapsed = payload["elapsed_time"]
        total_tokens = payload["total_num_tokens"]
        row = {
            "prompts": prompts,
            "elapsed_s": elapsed,
            "req_s": payload["requests_per_second"],
            "total_tok_s": payload["tokens_per_second"],
            "out_tok_s": None,
            "ttft_mean_ms": None, "ttft_p50_ms": None, "ttft_p99_ms": None,
            "tpot_mean_ms": None, "tpot_p99_ms": None,
            "itl_mean_ms": None, "itl_p99_ms": None,
            "itl_median_ms": None, "spec_accept_len": None, "spec_accept_rate": None,
        }

    # out_tok_s is exactly derivable when the legacy format omits it:
    #   total_tok_s = (in+out)*prompts/elapsed  and  out_tok_s = out*prompts/elapsed
    #   => out_tok_s = total_tok_s * out_len / (in_len + out_len)
    # Rankings within a scenario are identical either way (the factor is a
    # constant per scenario), so this makes decode speed comparable across
    # result formats. TTFT/TPOT, by contrast, are NOT derivable.
    if row["out_tok_s"] is None:
        row["out_tok_s"] = row["total_tok_s"] * out_len / (in_len + out_len)
        row["out_tok_s_source"] = "derived"
    else:
        row["out_tok_s_source"] = "reported"

    # --- integrity: the file must be internally consistent -------------------
    expected_tokens = prompts * (in_len + out_len)
    if total_tokens != expected_tokens:
        raise IngestError(
            f"{path}: total tokens {total_tokens} != prompts*(in+out) {expected_tokens} "
            f"- the requested lengths were not honoured, refusing to ingest")
    if abs(row["total_tok_s"] - total_tokens / elapsed) > 1e-6:
        raise IngestError(f"{path}: tokens_per_second inconsistent with elapsed_time")
    if abs(row["req_s"] - prompts / elapsed) > 1e-6:
        raise IngestError(f"{path}: requests_per_second inconsistent with elapsed_time")
    if row["out_tok_s_source"] == "reported":
        expected_out = row["total_tok_s"] * out_len / (in_len + out_len)
        if abs(row["out_tok_s"] - expected_out) > max(1e-6, expected_out * 1e-6):
            raise IngestError(f"{path}: output_throughput {row['out_tok_s']:.3f} does not "
                              f"match total throughput scaled by out/(in+out) "
                              f"({expected_out:.3f})")

    return {
        "run_id": run["run_id"], "model": run["model"], "label": run["label"],
        "date": run["date"], "repeats": run.get("repeats", 1), "src_format": fmt,
        "source_file": str(path.relative_to(ROOT)),
        "in_len": in_len, "out_len": out_len, **row,
    }


def ingest() -> list[dict]:
    manifest = load_manifest()
    excluded = {e["path"] for e in manifest.get("excluded", [])}
    rows, seen = [], set()

    for run in manifest["runs"]:
        run_dir = ROOT / run["dir"]
        if not run_dir.is_dir():
            raise IngestError(f"run {run['run_id']}: missing directory {run['dir']}")
        files = sorted(run_dir.glob("*.json"))
        if not files:
            raise IngestError(f"run {run['run_id']}: no result JSONs in {run['dir']}")
        for path in files:
            if path.name.startswith("_"):
                continue  # sidecar files (_env.txt etc.) are documentation, not data
            rel = str(path.relative_to(ROOT))
            if rel in excluded:
                continue
            row = normalise(run, path, json.loads(path.read_text()))
            key = (row["run_id"], row["in_len"], row["out_len"])
            if key in seen:
                raise IngestError(f"duplicate scenario in run {key}: {rel}")
            seen.add(key)
            rows.append(row)

        # every excluded path must actually exist (catches stale manifest entries)
        for entry in manifest.get("excluded", []):
            if not (ROOT / entry["path"]).exists():
                raise IngestError(f"manifest excludes missing file: {entry['path']}")

    rows.sort(key=lambda r: (r["model"], r["in_len"], r["out_len"], r["run_id"]))
    return rows


def write_outputs(rows: list[dict]) -> None:
    DATA.mkdir(exist_ok=True)
    with (DATA / "normalized.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in COLUMNS})
    with (DATA / "normalized.jsonl").open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> int:
    try:
        rows = ingest()
    except IngestError as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 1
    write_outputs(rows)
    models = sorted({r["model"] for r in rows})
    print(f"ingested {len(rows)} scenarios across {len(models)} models: {', '.join(models)}")
    missing = [c for c in ("ttft_mean_ms", "tpot_mean_ms")
               if any(r[c] is None for r in rows)]
    if missing:
        print(f"note: columns incomplete for some rows: {', '.join(missing)}")
    derived = sum(1 for r in rows if r["out_tok_s_source"] == "derived")
    if derived:
        print(f"note: out_tok_s derived (not reported) for {derived} legacy-format rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
