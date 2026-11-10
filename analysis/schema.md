# Canonical result schema

`analysis/ingest.py` maps every raw vLLM bench JSON onto one row. Raw files are
never edited or renamed — the model identity lives in `results/manifest.json`.

One row = one (run, input length, output length) measurement.

| Column | Meaning | Notes |
|---|---|---|
| `run_id` | `<date>_<model>_<n>` | join key into `results/manifest.json` |
| `model` | stable model key | from the manifest, **not** from the file name |
| `label` | display name used in tables | from the manifest |
| `date` | ISO date of the run | from the manifest |
| `repeats` | runs captured for this entry | 1 today → no variance estimate |
| `gpus` | GPUs the server used, from `results/manifest.json` | **divide throughput by this before comparing runs** (the 2026-11 run used 2, the 2026-08 runs used 1) |
| `src_format` | `legacy` \| `modern` | which vLLM bench output version produced it |
| `source_file` | repo-relative path to the raw JSON | immutable |
| `in_len` / `out_len` | requested prompt / generation lengths | parsed from `in<N>_out<N>` in the file name |
| `prompts` | completed requests in the run | must equal the requested `--num-prompts` |
| `elapsed_s` | wall-clock seconds for the whole batch | not per-request latency |
| `req_s` | `prompts / elapsed_s` | |
| `total_tok_s` | `(in_len + out_len) * prompts / elapsed_s` | **headline metric — counts prompt tokens** |
| `out_tok_s` | generated tokens / second | decode-only speed; `modern` format only |
| `ttft_mean_ms` / `ttft_p50_ms` / `ttft_p99_ms` | time to first token | `modern` format only |
| `tpot_mean_ms` / `tpot_p99_ms` | time per output token | meaningless for very short outputs (prefill interference) |
| `itl_mean_ms` / `itl_p99_ms` | inter-token latency | `modern` format only |
| `itl_median_ms` | median inter-token latency = time per engine **step** | `modern` only; the mean is inflated by chunked-prefill stalls (p99 ≈ 660 ms at short outputs) |
| `spec_accept_len` / `spec_accept_rate` | mean tokens accepted per speculative step / draft acceptance rate | `None` when the server ran without speculative decoding — **required context for any TPOT or ITL comparison** |

## Format detection

| `src_format` | identifying keys |
|---|---|
| `legacy` | `elapsed_time`, `num_requests`, `total_num_tokens`, `requests_per_second`, `tokens_per_second` |
| `modern` | `duration`, `completed`, `failed`, `total_input_tokens`, `total_output_tokens`, `request_throughput`, `total_token_throughput`, `output_throughput`, `*_ttft_ms`, `*_tpot_ms`, `*_itl_ms` |

## Hard integrity rules (ingest refuses the file otherwise)

1. `total tokens == prompts * (in_len + out_len)` — the requested lengths were honoured.
2. `total_tok_s == total tokens / elapsed_s` (within 1e-6).
3. `req_s == prompts / elapsed_s` (within 1e-6).
4. `modern` runs must report `failed == 0`.
5. One file per (run, in_len, out_len) — duplicates are an error, not averaged.

## Deliberately not ingested

| Raw key | Why |
|---|---|
| `max_output_tokens_per_s` | broken in the vLLM 0.32 output: near-constant 2,150–2,350 and **below** the average `output_throughput` in 13 of 16 files in `2026-11-03_qwen3.8-27b_a`. Quoting it would be wrong. |
| `latencies`, `queue_times` | per-request arrays, ~100 floats per file; they would bloat the canonical table. Aggregate queueing is already visible as the TTFT intercept. |
| `spec_decode_num_drafts`, `_draft_tokens`, `_accepted_tokens`, `_per_position_acceptance_rates` | derivable from `spec_accept_len` / `spec_accept_rate`; kept in the raw files. |

## Metric warning

`total_tok_s` counts prompt tokens, so it rewards prefill-heavy scenarios by
construction. A run at in2048/out128 looks ~12x better than in128/out2045 on
`total_tok_s` while generating far fewer tokens per second. Compare `out_tok_s`
for generation speed and `req_s` for chat-shaped traffic.
