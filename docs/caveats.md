# Known caveats

Read this before quoting any number from this repo.

## Provenance

| Run | Model identity | Serve flags | Result format |
|---|---|---|---|
| 2026-08-03 GPT-OSS 120B | asserted by directory name | **not recorded** | legacy (throughput only) |
| 2026-08-04 Qwen 27B FP8 | recorded in the files (`model_id`) | recorded (recovered into `bench/serve/`) | modern (full latency + decode) |
| 2026-08-10 Gemma | **unknown variant** | **not recorded** | legacy (throughput only) |
| 2026-11-03 Qwen 3.8 27B | recorded in the files (`model_id: qwen/qwen3.8-27b`) | **not recorded** | modern (full latency + decode + spec decode) |

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
- **The 2026-11 Qwen run has no recorded serve config.** No `max_num_seqs`,
  `max_num_batched_tokens`, `--kv-cache-dtype`, `--gpu-memory-utilization` and no
  `--speculative-config` (the draft method is only inferable from the reported
  acceptance stats: 3 draft tokens per step). It is the second run in this repo
  with unaudited flags, which is exactly what `README.md` rule 3 warns against.
  Recover it from the deployment before quoting the run as a model upgrade.

## Comparability

- **Serve configs are not known to be equal.** Only Qwen's flags are recorded
  (fp8 quantization, fp8 KV cache, chunked prefill, `--max-model-len 262144`,
  `--gpu-memory-utilization 0.95`). Chunked prefill and KV-cache dtype alone can
  move these numbers by tens of percent, so cross-model gaps are **confounded by
  configuration**, not purely by model architecture.
- All three ran on GPU 0 of the same class of machine, one model at a time, but
  at different times of day on a production box — background load was not
  controlled or recorded.

## The 2026-11 Qwen run is confounded three ways

`Qwen 3.8 27B (0.32+MTP)` vs `Qwen 27B` changes **checkpoint** (3.6 → 3.8),
**engine** (vLLM 0.2x → 0.32) and **speculative decoding** (off → on, 3 draft
tokens) at the same time. The bench client changed too (`--backend openai` →
`--backend vllm`, i.e. chat-completions → completions). Therefore:

- The **prefill** improvement (~1.9×; TTFT slope 4.11 → ~1.6–2.2 ms per input
  token, aggregate prefill ~12k → ~23–31k tok/s) is not spec-decode related, but
  it cannot be split between engine and checkpoint.
- The **decode** improvement is entirely spec decode: `median_ITL / TPOT ==
  spec_accept_len` in all 16 files, step time rose 25–43 % while TPOT per
  accepted token fell 41–64 %. With spec decode off this stack would most likely
  be *slower per token* than the 2026-08 run.
- Nothing in this repo can separate the three factors. The single most
  informative extra run is **Qwen 3.8 on 0.32 with speculative decoding
  disabled**; the second is **Qwen 3.6 on 0.32**.

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

1. **Recover and commit the 2026-11 serve config** (`bench/serve/qwen3.8-27b.yml`)
   — including `max_num_seqs` / `max_num_batched_tokens` and the speculative
   decoding config. Also check the server startup line `Maximum concurrency for
   262,144 tokens: X.Xx`: in-flight decode concurrency fell from ~84 to ~55 and is
   pinned in a 49–58 band across a 16× workload range, which looks like a
   scheduler cap rather than memory pressure (at in128/out2045, 55 sequences hold
   only ~121k KV tokens against a 262k-token context).
2. **Re-run the 2026-11 sweep with `bench/run.sh`, ≥3 repeats**, so it is
   comparable to the harness in this repo and has a variance estimate.
3. **Add the spec-decode-off run** to attribute the decode win.
4. Re-run GPT-OSS and Gemma on a current vLLM with the **modern** result format,
   so all models have `out_tok_s` + TTFT/TPOT.
5. Recover and commit the Gemma checkpoint id and serve flags.
6. Add ≥3 repeats per scenario across the board and report spread.
7. Capture `_env.txt` (GPU, driver, image, `/v1/models`) for every run —
   `bench/run.sh` does this automatically now, which is why the 2026-11 run's
   missing capture is a process regression, not a tooling gap.
