# Known caveats

Read this before quoting any number from this repo.

## Provenance

| Run | Model identity | Serve flags | Result format |
|---|---|---|---|
| 2026-08-03 GPT-OSS 120B | asserted by directory name | **not recorded** | legacy (throughput only) |
| 2026-08-04 Qwen 27B FP8 | recorded in the files (`model_id`) | recorded (recovered into `bench/serve/`) | modern (full latency + decode) |
| 2026-08-10 Gemma | **unknown variant** | **not recorded** | legacy (throughput only) |

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

## Comparability

- **Serve configs are not known to be equal.** Only Qwen's flags are recorded
  (fp8 quantization, fp8 KV cache, chunked prefill, `--max-model-len 262144`,
  `--gpu-memory-utilization 0.95`). Chunked prefill and KV-cache dtype alone can
  move these numbers by tens of percent, so cross-model gaps are **confounded by
  configuration**, not purely by model architecture.
- All three ran on GPU 0 of the same class of machine, one model at a time, but
  at different times of day on a production box — background load was not
  controlled or recorded.

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

## What to fix first

1. Re-run GPT-OSS and Gemma on a current vLLM with the **modern** result format,
   so all three models have `out_tok_s` + TTFT/TPOT.
2. Recover and commit the Gemma checkpoint id and serve flags.
3. Add ≥3 repeats per scenario and report spread.
4. Capture `_env.txt` (GPU, driver, image, `/v1/models`) for every run —
   `bench/run.sh` does this automatically now.
