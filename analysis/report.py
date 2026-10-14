#!/usr/bin/env python3
"""Render every table in README.md from data/normalized.csv.

The README is a template: hand-written prose lives outside the generated
markers, all numbers live inside them. Regenerating is idempotent, and CI
fails if the committed README is stale.

    python3 analysis/report.py            # rewrite README.md + data/leaderboard.json
    python3 analysis/report.py --check    # exit 1 if README.md would change

Generated regions look like:

    <!-- BEGIN GENERATED:summary -->
    ...rendered markdown...
    <!-- END GENERATED:summary -->
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
README = ROOT / "README.md"

BEGIN = "<!-- BEGIN GENERATED:{name} -->"
END = "<!-- END GENERATED:{name} -->"

BLOCKS = ["tldr", "recommend", "summary", "heatmaps", "head2head-tok",
          "head2head-decode", "head2head-req", "speedup", "latency", "gaps"]

NUMERIC = {"in_len": int, "out_len": int, "prompts": int, "repeats": int}
FLOATS = ["elapsed_s", "req_s", "total_tok_s", "out_tok_s", "ttft_mean_ms",
          "ttft_p50_ms", "ttft_p99_ms", "tpot_mean_ms", "tpot_p99_ms",
          "itl_mean_ms", "itl_p99_ms"]


# --------------------------------------------------------------------------- #
# loading + aggregation
# --------------------------------------------------------------------------- #
def load_rows() -> list[dict]:
    path = DATA / "normalized.csv"
    if not path.exists():
        sys.exit("data/normalized.csv missing - run `make ingest` first")
    rows = []
    for raw in csv.DictReader(path.open()):
        row: dict = {}
        for key, val in raw.items():
            if val == "":
                row[key] = None
            elif key in NUMERIC:
                row[key] = NUMERIC[key](float(val))
            elif key in FLOATS:
                row[key] = float(val)
            else:
                row[key] = val
        rows.append(row)
    return rows


def load_manifest() -> dict:
    return json.loads((ROOT / "results" / "manifest.json").read_text())


def aggregate(rows: list[dict]) -> dict:
    """(model, in_len, out_len) -> metrics averaged over repeat runs."""
    groups: dict[tuple, dict] = {}
    for row in rows:
        key = (row["model"], row["in_len"], row["out_len"])
        g = groups.setdefault(key, {"runs": [], "metrics": {}, "sources": set()})
        g["runs"].append(row["run_id"])
        if row.get("out_tok_s_source"):
            g["sources"].add(row["out_tok_s_source"])
        for metric in FLOATS:
            if row[metric] is not None:
                g["metrics"].setdefault(metric, []).append(row[metric])
    agg = {}
    for key, g in groups.items():
        entry = {"n": len(g["runs"]), "runs": g["runs"],
                 "out_tok_s_sources": sorted(g["sources"])}
        for metric in FLOATS:
            vals = g["metrics"].get(metric)
            entry[metric] = sum(vals) / len(vals) if vals else None
        agg[key] = entry
    return agg


def models_of(agg: dict) -> list[str]:
    return sorted({model for model, _, _ in agg})


def lens(agg: dict, which: str) -> list[int]:
    idx = 1 if which == "in" else 2
    return sorted({key[idx] for key in agg})


def scenarios(agg: dict):
    """Yield (in_len, out_len) in stable order."""
    for in_len in lens(agg, "in"):
        for out_len in lens(agg, "out"):
            yield in_len, out_len


def cells_of(agg: dict, model: str) -> list[dict]:
    return [v for k, v in agg.items() if k[0] == model]


def mean_of(agg: dict, model: str, metric: str):
    vals = [c[metric] for c in cells_of(agg, model) if c[metric] is not None]
    return sum(vals) / len(vals) if vals else None


def best_of(agg: dict, in_len: int, out_len: int, metric: str):
    """Return (value, model) for the leading model in one scenario."""
    scored = [(agg[(m, in_len, out_len)][metric], m) for m in models_of(agg)
              if agg[(m, in_len, out_len)][metric] is not None]
    return max(scored) if scored else (None, None)


def baseline_model(agg: dict) -> str:
    return min(models_of(agg), key=lambda m: mean_of(agg, m, "total_tok_s"))


def winners(agg: dict, metric: str) -> dict:
    wins: dict[str, int] = {}
    ties = 0
    for in_len, out_len in scenarios(agg):
        scored = sorted((agg[(m, in_len, out_len)][metric], m) for m in models_of(agg)
                        if agg[(m, in_len, out_len)][metric] is not None)
        scored.reverse()
        if not scored:
            continue
        wins[scored[0][1]] = wins.get(scored[0][1], 0) + 1
        if len(scored) > 1 and (scored[0][0] - scored[1][0]) / scored[0][0] < 0.05:
            ties += 1
    return {"wins": wins, "ties": ties, "scenarios": sum(wins.values())}


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #
def f0(v):
    return "-" if v is None else f"{v:,.0f}"


def f1(v):
    return "-" if v is None else f"{v:.1f}"


def f2(v):
    return "-" if v is None else f"{v:,.2f}"


def fx(v):
    return "-" if v is None else f"{v:.2f}x"


def table(header, aligns, body):
    spec = {"": "---", "<": ":---", ":": "---:"}
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join(spec.get(a, "---") for a in aligns) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# blocks
# --------------------------------------------------------------------------- #
def block_tldr(agg: dict, labels: dict) -> str:
    res = winners(agg, "total_tok_s")
    total = res["scenarios"]
    order = sorted(res["wins"].items(), key=lambda kv: -kv[1])
    win_str = ", ".join(f"**{labels[m]}** {w}/{total}" for m, w in order)

    peak = max(((v["total_tok_s"], k[1], k[2], k[0]) for k, v in agg.items()
                if v["total_tok_s"] is not None))
    decode = [(v["out_tok_s"], k[0], k[1], k[2]) for k, v in agg.items() if v["out_tok_s"]]

    lines = [
        f"- **Wins on total token throughput ({total} scenarios):** {win_str}. "
        f"{res['ties']}/{total} scenarios are decided by under 5% — treat those as ties.",
        f"- **Peak total throughput:** **{f0(peak[0])} tok/s** by {labels[peak[3]]} at "
        f"in{peak[1]}/out{peak[2]} — prefill-heavy, since input tokens dominate this metric.",
    ]
    if decode:
        d = max(decode)
        lines.append(
            f"- **Peak decode throughput:** **{f0(d[0])} output tok/s** by {labels[d[1]]} "
            f"at in{d[2]}/out{d[3]} — the only metric that isolates generation speed.")
    else:
        lines.append("- **Peak decode throughput:** not measurable — no run reports "
                     "`output_throughput` (see data gaps).")
    lines.append("- **The leader flips with the input/output ratio**, so pick per workload "
                 "(table below) rather than per model name.")
    return "\n".join(lines)


WORKLOAD_BUCKETS = [
    ("Long prompt, short answer (RAG, extract, classify)",
     lambda i, o: i >= 1024 and o <= 128, "total_tok_s", "tok/s"),
    ("Short prompt, long answer (generation, agents, code)",
     lambda i, o: i <= 128 and o >= 1024, "out_tok_s", "output tok/s"),
    ("Balanced prompt/response (in == out)",
     lambda i, o: i == o, "total_tok_s", "tok/s"),
    ("Maximum requests/sec (small chatty traffic)",
     lambda i, o: i <= 512 and o <= 128, "req_s", "req/s"),
]


def block_recommend(agg: dict, labels: dict) -> str:
    body = []
    for name, pred, metric, unit in WORKLOAD_BUCKETS:
        # majority winner across the scenarios in this bucket
        tally: dict[str, int] = {}
        for in_len, out_len in scenarios(agg):
            if pred(in_len, out_len):
                _, winner = best_of(agg, in_len, out_len, metric)
                if winner:
                    tally[winner] = tally.get(winner, 0) + 1
        if not tally:
            continue
        pick = max(tally.items(), key=lambda kv: kv[1])[0]

        cells = []
        for in_len, out_len in scenarios(agg):
            if not pred(in_len, out_len):
                continue
            value = agg[(pick, in_len, out_len)][metric]
            best_value, best_model = best_of(agg, in_len, out_len, metric)
            if value is None or best_value is None:
                continue
            if best_model == pick:
                others = sorted((agg[(m, in_len, out_len)][metric] for m in models_of(agg)
                                 if m != pick and agg[(m, in_len, out_len)][metric] is not None),
                                reverse=True)
                delta = (f"+{(value - others[0]) / others[0] * 100:.0f}%" if others else "-")
            else:
                delta = f"\u2212{(best_value - value) / best_value * 100:.0f}% vs {labels[best_model]}"
            fmt = f2 if metric == "req_s" else f0
            cells.append(f"in{in_len}/out{out_len}: {fmt(value)} {unit} ({delta})")
        note = "" if tally[pick] == len(cells) else f" _(wins {tally[pick]}/{len(cells)} scenarios)_"
        body.append([name, f"**{labels[pick]}**{note}", "; ".join(cells)])
    return table(["Workload shape", "Pick", "Measured per scenario (delta vs the scenario leader)"],
                 ["", "<", ""], body)


def block_summary(agg: dict, labels: dict) -> str:
    res = winners(agg, "total_tok_s")
    total = res["scenarios"]
    body = []
    for model in sorted(models_of(agg), key=lambda m: -mean_of(agg, m, "total_tok_s")):
        cells = cells_of(agg, model)
        body.append([
            f"**{labels[model]}**",
            f0(mean_of(agg, model, "total_tok_s")),
            f2(mean_of(agg, model, "req_s")),
            f0(max(c["total_tok_s"] for c in cells if c["total_tok_s"] is not None)),
            f2(max(c["req_s"] for c in cells if c["req_s"] is not None)),
            f0(mean_of(agg, model, "out_tok_s")),
            f"{res['wins'].get(model, 0)} / {total}",
            str(max(c["n"] for c in cells)),
        ])
    return table(["Model", "Avg tok/s", "Avg req/s", "Peak tok/s", "Peak req/s",
                  "Avg out tok/s", "Scenarios won", "Runs / scenario"],
                 ["", "---:", "---:", "---:", "---:", "---:", "---:", "---:"], body)


def block_heatmaps(agg: dict, labels: dict) -> str:
    chunks = []
    for model in models_of(agg):
        rows = [[f"**{in_len}**"] + [f0(agg[(model, in_len, o)]["total_tok_s"])
                                     for o in lens(agg, "out")]
                for in_len in lens(agg, "in")]
        chunks.append(f"**{labels[model]}** — total tok/s\n\n" +
                      table(["In \\ Out"] + [str(o) for o in lens(agg, "out")],
                            [""] + ["---:"] * len(lens(agg, "out")), rows))
    return "\n\n".join(chunks)


def block_head2head(agg: dict, labels: dict, metric: str) -> str:
    models = models_of(agg)
    fmt = f2 if metric == "req_s" else f0
    body = []
    for in_len, out_len in scenarios(agg):
        values = [agg[(m, in_len, out_len)][metric] for m in models]
        _, leader = best_of(agg, in_len, out_len, metric)
        body.append([f"in{in_len}/out{out_len}"] + [fmt(v) for v in values]
                    + [labels.get(leader, "-")])
    return table(["Scenario"] + [labels[m] for m in models] + ["Leader"],
                 [""] + ["---:"] * len(models) + [""], body)


def block_speedup(agg: dict, labels: dict) -> str:
    base = baseline_model(agg)
    models = [m for m in models_of(agg) if m != base]
    body = []
    for in_len, out_len in scenarios(agg):
        b = agg[(base, in_len, out_len)]["total_tok_s"]
        row = [f"in{in_len}/out{out_len}"]
        for m in models:
            v = agg[(m, in_len, out_len)]["total_tok_s"]
            row.append(fx(v / b) if v and b else "-")
        body.append(row)
    note = (f"Baseline for every ratio is **{labels[base]}** (slowest average total "
            f"throughput). Values above 1.00x mean the model beat the baseline on "
            f"total tokens/sec.\n\n")
    return note + table(["Scenario"] + [f"{labels[m]} / {labels[base]}" for m in models],
                        [""] + ["---:"] * len(models), body)


def block_latency(agg: dict, labels: dict) -> str:
    chunks = []
    for model in models_of(agg):
        if not any(c["ttft_mean_ms"] for c in cells_of(agg, model)):
            continue
        rows = []
        for in_len, out_len in scenarios(agg):
            v = agg[(model, in_len, out_len)]
            rows.append([f"in{in_len}/out{out_len}", f0(v["ttft_mean_ms"]),
                         f0(v["ttft_p99_ms"]), f1(v["tpot_mean_ms"]),
                         f1(v["tpot_p99_ms"]), f1(v["itl_p99_ms"])])
        chunks.append(f"**{labels[model]}** — latency in ms (mean, and p99 where noted)\n\n" +
                      table(["Scenario", "TTFT mean", "TTFT p99", "TPOT mean",
                             "TPOT p99", "ITL p99"],
                            ["", "---:", "---:", "---:", "---:", "---:"], rows))
    return "\n\n".join(chunks) if chunks else "_No run reports TTFT / TPOT / ITL._"


def block_gaps(agg: dict, labels: dict, manifest: dict) -> str:
    gaps = []
    for run in manifest["runs"]:
        model = run["model"]
        cells = cells_of(agg, model)
        missing = [name for name, key in [("TTFT", "ttft_mean_ms"),
                                          ("TPOT", "tpot_mean_ms")]
                   if not any(c[key] for c in cells)]
        if missing:
            gaps.append(f"**{labels[model]}**: no {', '.join(missing)} — legacy result "
                        f"format, and unlike output throughput these are not derivable")
        sources = {s for c in cells for s in c.get("out_tok_s_sources", [])}
        if sources == {"derived"}:
            gaps.append(f"**{labels[model]}**: `out_tok_s` is **derived** arithmetic "
                        f"(`total_tok_s × out/(in+out)`), not measured by the bench — "
                        f"rankings are unaffected, the absolute value is unverified")
        if "unknown" in run.get("variant", "").lower():
            gaps.append(f"**{labels[model]}**: model variant (size / quantization) never "
                        f"recorded — the run is not reproducible")
        if run.get("repeats", 1) < 2:
            gaps.append(f"**{labels[model]}**: 1 run per scenario — no variance estimate, "
                        f"gaps under ~5% are noise")
    for entry in manifest.get("excluded", []):
        gaps.append(f"excluded `{Path(entry['path']).name}`: {entry['reason']}")
    seen, uniq = set(), []
    for gap in gaps:
        if gap not in seen:
            seen.add(gap)
            uniq.append(gap)
    return "\n".join(f"- {g}" for g in uniq)


# --------------------------------------------------------------------------- #
# machine-readable twin of the README
# --------------------------------------------------------------------------- #
def leaderboard_json(agg: dict, labels: dict) -> dict:
    res = winners(agg, "total_tok_s")
    models = models_of(agg)
    return {
        "baseline": baseline_model(agg),
        "scenarios": res["scenarios"],
        "ties_under_5pct": res["ties"],
        "wins_total_tok_s": res["wins"],
        "models": [{"model": m, "label": labels[m],
                    "avg_total_tok_s": round(mean_of(agg, m, "total_tok_s"), 1),
                    "avg_req_s": round(mean_of(agg, m, "req_s"), 3),
                    "avg_out_tok_s": (round(mean_of(agg, m, "out_tok_s"), 1)
                                      if mean_of(agg, m, "out_tok_s") is not None else None)}
                   for m in models],
        "scenario_results": [
            {"in_len": i, "out_len": o,
             "leader": best_of(agg, i, o, "total_tok_s")[1],
             "total_tok_s": {m: agg[(m, i, o)]["total_tok_s"] for m in models},
             "req_s": {m: agg[(m, i, o)]["req_s"] for m in models},
             "out_tok_s": {m: agg[(m, i, o)]["out_tok_s"] for m in models}}
            for i, o in scenarios(agg)
        ],
    }


# --------------------------------------------------------------------------- #
# README injection
# --------------------------------------------------------------------------- #
def render(agg: dict, manifest: dict) -> dict:
    labels = {r["model"]: r["label"] for r in manifest["runs"]}
    return {
        "tldr": block_tldr(agg, labels),
        "recommend": block_recommend(agg, labels),
        "summary": block_summary(agg, labels),
        "heatmaps": block_heatmaps(agg, labels),
        "head2head-tok": block_head2head(agg, labels, "total_tok_s"),
        "head2head-decode": block_head2head(agg, labels, "out_tok_s"),
        "head2head-req": block_head2head(agg, labels, "req_s"),
        "speedup": block_speedup(agg, labels),
        "latency": block_latency(agg, labels),
        "gaps": block_gaps(agg, labels, manifest),
    }


def inject(readme: str, blocks: dict) -> str:
    for name, body in blocks.items():
        begin, end = BEGIN.format(name=name), END.format(name=name)
        if begin not in readme or end not in readme:
            sys.exit(f"README.md is missing the markers for block '{name}'")
        start = readme.index(begin) + len(begin)
        stop = readme.index(end, start)
        readme = readme[:start] + "\n" + body.rstrip() + "\n" + readme[stop:]
    return readme


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="fail if README.md is not up to date (used by CI)")
    args = ap.parse_args()

    agg = aggregate(load_rows())
    manifest = load_manifest()
    blocks = render(agg, manifest)

    original = README.read_text()
    updated = inject(original, blocks)
    (DATA / "leaderboard.json").write_text(
        json.dumps(leaderboard_json(agg, {r["model"]: r["label"] for r in manifest["runs"]}),
                   indent=2) + "\n")
    if args.check:
        if updated != original:
            sys.exit("README.md is stale — run `make report` and commit the result")
        print(f"README.md up to date ({len(blocks)} generated blocks verified)")
        return 0
    README.write_text(updated)
    print(f"rewrote {len(blocks)} generated blocks in README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
