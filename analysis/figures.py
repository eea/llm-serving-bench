#!/usr/bin/env python3
"""Generate PNG figures from data/normalized.csv into docs/figures/.

Requires matplotlib (kept optional so the core pipeline stays stdlib-only):
    python3 -m venv .venv && .venv/bin/pip install matplotlib
    .venv/bin/python analysis/figures.py

Exits 0 with a notice if matplotlib is unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "figures"
sys.path.insert(0, str(ROOT / "analysis"))

import report  # noqa: E402

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
except ImportError:
    print("matplotlib not installed - skipping figures "
          "(python3 -m venv .venv && .venv/bin/pip install matplotlib)")
    sys.exit(0)


def main() -> int:
    agg = report.aggregate(report.load_rows())
    manifest = report.load_manifest()
    labels = {r["model"]: r["label"] for r in manifest["runs"]}
    models = report.models_of(agg)
    ins, outs = report.lens(agg, "in"), report.lens(agg, "out")
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. per-model heatmaps of total token throughput ------------------------
    fig, axes = plt.subplots(1, len(models), figsize=(5 * len(models), 4.2))
    axes = [axes] if len(models) == 1 else axes
    grid = [[[agg[(m, i, o)]["total_tok_s"] for o in outs] for i in ins] for m in models]
    flat = [v for g in grid for row in g for v in row if v]
    vmax, vmin = max(flat), min(flat)
    for ax, model, data in zip(axes, models, grid):
        im = ax.imshow(data, cmap="viridis", norm=LogNorm(vmin=vmin, vmax=vmax))
        ax.set_xticks(range(len(outs)), [str(o) for o in outs])
        ax.set_yticks(range(len(ins)), [str(i) for i in ins])
        ax.set_xlabel("output tokens")
        ax.set_ylabel("input tokens")
        ax.set_title(f"{labels[model]} — total tok/s")
        for r, row in enumerate(data):
            for c, v in enumerate(row):
                ax.text(c, r, f"{v:,.0f}", ha="center", va="center",
                        fontsize=7, color="white")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.suptitle("Total token throughput (prompt + generated tokens per wall-clock second)")
    fig.tight_layout()
    fig.savefig(OUT / "heatmap_total_tok_s.png", dpi=140)
    plt.close(fig)

    # 2. speedup vs the slowest model ---------------------------------------
    base = report.baseline_model(agg)
    others = [m for m in models if m != base]
    fig, ax = plt.subplots(figsize=(6, 4.2))
    data = [[max(agg[(m, i, o)]["total_tok_s"] for m in others) / agg[(base, i, o)]["total_tok_s"]
             for o in outs] for i in ins]
    vmax = max(v for row in data for v in row)
    im = ax.imshow(data, cmap="coolwarm", vmin=1.0, vmax=vmax)
    ax.set_xticks(range(len(outs)), [str(o) for o in outs])
    ax.set_yticks(range(len(ins)), [str(i) for i in ins])
    ax.set_xlabel("output tokens")
    ax.set_ylabel("input tokens")
    ax.set_title(f"Best non-baseline speedup vs {labels[base]}")
    for r, row in enumerate(data):
        for c, v in enumerate(row):
            ax.text(c, r, f"{v:.2f}x", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(OUT / "speedup_vs_baseline.png", dpi=140)
    plt.close(fig)

    # 3. throughput vs input length, one panel per output length ------------
    fig, axes = plt.subplots(1, len(outs), figsize=(4.2 * len(outs), 3.8), sharey=True)
    axes = [axes] if len(outs) == 1 else axes
    for ax, out_len in zip(axes, outs):
        for model in models:
            ax.plot(ins, [agg[(model, i, out_len)]["total_tok_s"] for i in ins],
                    marker="o", label=labels[model])
        ax.set_title(f"out {out_len} tok")
        ax.set_xlabel("input tokens")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("total tok/s")
    axes[0].legend(fontsize=8)
    fig.suptitle("Total token throughput scales with prompt size, not just model size")
    fig.tight_layout()
    fig.savefig(OUT / "throughput_vs_input.png", dpi=140)
    plt.close(fig)

    # 4. request throughput vs output length --------------------------------
    fig, axes = plt.subplots(1, len(ins), figsize=(4.2 * len(ins), 3.8), sharey=True)
    axes = [axes] if len(ins) == 1 else axes
    for ax, in_len in zip(axes, ins):
        for model in models:
            ax.plot(outs, [agg[(model, in_len, o)]["req_s"] for o in outs],
                    marker="s", label=labels[model])
        ax.set_xscale("log", base=2)
        ax.set_title(f"in {in_len} tok")
        ax.set_xlabel("output tokens")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("req/s")
    axes[0].legend(fontsize=8)
    fig.suptitle("Request throughput (concurrency ceiling: 100 requests fired at once)")
    fig.tight_layout()
    fig.savefig(OUT / "req_throughput_vs_output.png", dpi=140)
    plt.close(fig)

    # 5. decode throughput: generated tokens per second ----------------------
    fig, axes = plt.subplots(1, len(ins), figsize=(4.2 * len(ins), 3.8), sharey=True)
    axes = [axes] if len(ins) == 1 else axes
    for ax, in_len in zip(axes, ins):
        for model in models:
            ax.plot(outs, [agg[(model, in_len, o)]["out_tok_s"] for o in outs],
                    marker="^", label=labels[model])
        ax.set_xscale("log", base=2)
        ax.set_title(f"in {in_len} tok")
        ax.set_xlabel("output tokens")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("generated tok/s")
    axes[0].legend(fontsize=8)
    fig.suptitle("Decode throughput — what a model actually generates per second")
    fig.tight_layout()
    fig.savefig(OUT / "decode_throughput.png", dpi=140)
    plt.close(fig)

    # 6. decode concurrency and speculative decoding -------------------------
    # Only runs whose result format reports TPOT can be decomposed; legacy runs
    # are skipped rather than guessed at.
    modern = [m for m in models
              if all(agg[(m, i, o)]["tpot_mean_ms"] for i in ins for o in outs)]
    if modern:
        scen = [(i, o) for i in ins for o in outs]
        fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
        w = 0.8 / len(modern)
        ax = axes[0]
        for k, model in enumerate(modern):
            off = (k - (len(modern) - 1) / 2) * w
            ys = [agg[(model, i, o)]["out_tok_s"] * agg[(model, i, o)]["tpot_mean_ms"] / 1000
                  for i, o in scen]
            ax.bar([n + off for n in range(len(scen))], ys, width=w, label=labels[model])
        ax.axhline(100, color="crimson", ls=":", lw=1.2)
        ax.text(0, 101, "100 requests fired at once", color="crimson", fontsize=8)
        ax.set_ylim(0, 128)
        ax.legend(fontsize=7, loc="upper right")
        ax.set_xticks(range(len(scen)), [f"in{i}/out{o}" for i, o in scen],
                      rotation=60, ha="right", fontsize=7)
        ax.set_ylabel("requests generating at the same instant")
        ax.set_title("In-flight decode concurrency = out_tok_s x TPOT\n"
                     "aggregate over all DP ranks; below 100 means the server, not the "
                     "client, is the limit", fontsize=10)
        ax.legend(fontsize=7)

        ax = axes[1]
        longest = max(outs)
        w2 = 0.8 / (2 * len(modern))
        for k, model in enumerate(modern):
            for j, (metric, name, alpha) in enumerate([("tpot_mean_ms", "TPOT", 1.0),
                                                       ("itl_median_ms", "median ITL", 0.55)]):
                ys = [agg[(model, i, longest)][metric] for i in ins]
                off = (2 * k + j - (2 * len(modern) - 1) / 2) * w2
                ax.bar([n + off for n in range(len(ins))], ys, width=w2,
                       color=f"C{k}" if j == 0 else f"C{k}", alpha=alpha,
                       hatch="" if j == 0 else "//",
                       label=f"{labels[model]} - {name}")
        for n, i in enumerate(ins):
            al = agg[(modern[-1], i, longest)]["spec_accept_len"]
            if al:
                top = max(agg[(m, i, longest)]["itl_median_ms"] or 0 for m in modern)
                ax.text(n, top + 2, f"x{al:.2f} tok/step", ha="center",
                        fontsize=8, color="darkorange", fontweight="bold")
        ax.set_ylim(0, 62)
        ax.set_xticks(range(len(ins)), [f"in {i}" for i in ins])
        ax.set_xlabel(f"input tokens (all scenarios with out={longest})")
        ax.set_ylabel("ms")
        ax.set_title("TPOT is per accepted token, median ITL is per step.\n"
                     "With spec decode a step gets slower but emits x tok/step - the two\n"
                     "are not comparable across runs unless acceptance is shown", fontsize=10)
        ax.legend(fontsize=7, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.24))
        fig.tight_layout()
        fig.savefig(OUT / "decode_concurrency_and_spec_decode.png", dpi=140)
        plt.close(fig)
        n_figures = 6
    else:
        n_figures = 5

    print(f"wrote {n_figures} figures to {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
