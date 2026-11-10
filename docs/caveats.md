# Known caveats

Read this before quoting any number from this repo.

## Provenance

| Run | Model identity | Serve flags | Result format |
|---|---|---|---|
| 2026-08-03 GPT-OSS 120B | asserted by directory name | **not recorded** | legacy (throughput only) |
| 2026-08-04 Qwen 27B FP8 | recorded in the files (`model_id`) | recorded (recovered into `bench/serve/`) | modern (full latency + decode) |
| 2026-08-10 Gemma | **unknown variant** | **not recorded** | legacy (throughput only) |
| 2026-11-03 Qwen 3.8 27B | recorded in the files (`model_id: qwen/qwen3.8-27b`) | recorded **after the fact** (operator supplied `bench/serve/qwen3.8-27b.yml`) | modern (full latency + decode + spec decode) |

- The raw files were copied off a production server; host, driver and GPU model
  were never captured.
- **Every file in the Gemma run is named `results_gpt_oss_120b_*.json`** — the
  benchmark script was copy-pasted and the output prefix never changed. The
  values differ from the GPT-OSS run, so they are not duplicates, but the model
  attribution rests entirely on the source directory name. The pipeline reads
  `results/manifest.json`, never file names, so this cannot corrupt the tables —
  but it is a real audit risk if someone browses the raw files.
- **The Gemma variant (size, quantization) is unknown.** Its column is
  effectively "some Gemma".
- `results/2026-08-03_gpt-oss-120b_a/results_gpt_oss_120b_gpu0.json` (1000
  prompts, no in/out lengths in the name) is excluded from all tables via the
  manifest. It is kept for reference.
- **The 2026-11 run was imported with no recorded configuration at all** — no
  `_env.txt`, no image tag, no GPU count. The compose file was recovered from the
  deployment afterwards and committed as `bench/serve/qwen3.8-27b.yml`. That is the
  second run in this repo whose provenance had to be reconstructed after the fact,
  which is exactly what `README.md` rule 3/4 warn against: run `bench/run.sh` and it
  captures this automatically.

## Comparability

- **Serve configs are not known to be equal.** Only Qwen's flags are recorded
  (fp8 quantization, fp8 KV cache, chunked prefill, `--max-model-len 262144`,
  `--gpu-memory-utilization 0.95`). Chunked prefill and KV-cache dtype alone can
  move these numbers by tens of percent, so cross-model gaps are **confounded by
  configuration**, not purely by model architecture.
- All three ran on GPU 0 of the same class of machine, one model at a time, but
  at different times of day on a production box — background load was not
  controlled or recorded.

## The 2026-11 Qwen run is confounded four ways

`Qwen 3.8 27B (0.32+MTP)` vs `Qwen 27B` changes **GPU count** (1 → 2,
`--data-parallel-size 2`), **checkpoint** (3.6 → 3.8), **engine** (vLLM 0.2x →
0.32.0) and **speculative decoding** (off → on, MTP, 3 draft tokens). The bench
client changed too (`--backend openai` → `--backend vllm`), and
`--kv-cache-dtype fp8` was dropped.

- **The GPU change dominates.** Aggregate mean total tok/s 5,545 → 8,329 (+50 %),
  but **per GPU 5,545 → 4,165 (−27 %)**. Any statement of the form "the new stack
  is 50 % faster" must say "on twice the hardware".
- The **prefill** improvement (~1.9× aggregate; TTFT slope 4.11 → ~1.6–2.2 ms per
  input token) is roughly what DP=2 alone predicts, so this dataset contains **no
  evidence of an engine-level prefill gain**.
- The **decode** improvement is speculative decoding plus a much smaller resident
  batch per rank: `median_ITL / TPOT == spec_accept_len` in all 16 files, step
  time rose 25–43 % while TPOT per accepted token fell 41–64 %.
- Nothing in this repo can separate the four factors. The informative extra runs
  are **Qwen 3.8 on 0.32 on one GPU**, then the same with **speculative decoding
  disabled**, then **Qwen 3.6 on 0.32 on one GPU**.

## Statistics

- **n = 1 per scenario.** No repeats, no warm-up run, no confidence intervals.
  Gaps under ~5% are noise: several scenarios in the head-to-head tables are
  decided by 1–2%, and those should be reported as ties.
- Rankings are stable only where the margin is large (e.g. the long-input
  scenarios).

## Metric coverage

- GPT-OSS and Gemma report **no** `output_throughput`, TTFT, TPOT or ITL — the
  legacy bench format does not emit them. Decode speed and latency are therefore
  **only comparable for Qwen**, and the "which model is fastest" question cannot
  be answered for generation-heavy workloads from this dataset.
- The headline `tok/s` includes prompt tokens; see
  [methodology.md](methodology.md#why-the-headline-metric-is-dangerous).
- **`max_output_tokens_per_s` in the 2026-11 files is broken**: near-constant
  2,150–2,350 and *below* the average `output_throughput` in 13 of 16 files. It is
  not ingested. Use `out_tok_s` instead.
- **`mean_itl_ms` is inflated by chunked-prefill stalls** (p99 ≈ 660 ms in
  short-output runs, in both formats). `itl_median_ms` is the per-step time.

## What to fix first

1. **Re-run Qwen 3.8 on vLLM 0.32 on ONE GPU** (`--data-parallel-size 1`). Until
   that exists, the honest reading is: as deployed +50 % throughput, **per GPU
   −27 %**.
2. **Then the same with `--speculative-config` removed**, to separate engine gain
   from MTP gain.
3. **Restore `--kv-cache-dtype fp8`** and re-measure. In-flight decode concurrency
   is ~27 sequences per DP rank where the single-GPU 2026-08 run held ~84; KV
   bytes per token roughly doubled when fp8 KV was dropped, and MTP adds 3 draft
   slots per sequence. Check the startup block per rank: `GPU KV cache size: N
   tokens` / `Maximum concurrency for 262,144 tokens: X.Xx`. (`--max_num_seqs`
   969 rules out a sequence-count cap.)
4. **Re-run the sweep with `bench/run.sh`, ≥3 repeats**, so it is comparable to
   the harness in this repo and has a variance estimate.
5. Re-run GPT-OSS and Gemma on a current vLLM with the **modern** result format,
   so all models have `out_tok_s` + TTFT/TPOT.
6. Recover and commit the Gemma checkpoint id and serve flags.
6. Add ≥3 repeats per scenario across the board and report spread.
7. Capture `_env.txt` (GPU, driver, image, `/v1/models`) for every run —
   `bench/run.sh` does this automatically now, which is why the 2026-11 run's
   missing capture is a process regression, not a tooling gap.
