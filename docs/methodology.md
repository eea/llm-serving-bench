# Methodology

## What was measured

Each data point is one `vllm bench serve` run: a fixed number of synthetic
requests (`--dataset-name random`) with a fixed prompt length and a fixed
generation length, all submitted at once against a warm server.

| Parameter | Value | Notes |
|---|---|---|
| Dataset | `random` | token ids are random; no real-world prompt structure, no cache hits |
| Prompts per scenario | 100 | identical across all runs |
| Request rate | default `inf` | all 100 submitted immediately → saturation, not SLO |
| Input lengths | 128, 512, 1024, 2048 | |
| Output lengths | 128, 512, 1024, 2045 | 2045 is what was actually run; the reason was never recorded |
| Repeats | 1 | no variance estimate |
| GPU | one GPU (GPU 0) | models served one at a time |

## Metrics

| Metric | Definition | Use it for |
|---|---|---|
| `total_tok_s` | (prompt + generated tokens) / wall-clock seconds | system-level token throughput; **biased toward long prompts** |
| `out_tok_s` | generated tokens / wall-clock seconds | generation (decode) speed — `modern` result format only |
| `req_s` | completed requests / wall-clock seconds | chat-shaped traffic, agent loops |
| `elapsed_s` | wall-clock seconds for the whole batch | sanity check, not a latency |
| `ttft_*` | time to first token | user-perceived responsiveness |
| `tpot_*`, `itl_*` | time / inter-token latency | streaming smoothness |
| `itl_median_ms` | median inter-token latency = time per engine **step** | the honest step time; the mean is inflated by chunked-prefill stalls |
| `spec_accept_len`, `spec_accept_rate` | tokens accepted per speculative-decoding step, and draft acceptance | mandatory context for any TPOT/ITL comparison |

Full column contract: [`../analysis/schema.md`](../analysis/schema.md).

## Why the headline metric is dangerous

`total_tok_s` rewards prefill. At `in2048/out128` the harness feeds 204,800
prompt tokens and generates only 12,800 — a 16:1 ratio. Concretely, for Qwen
that scenario scores **10,488 total tok/s but only 617 output tok/s**, while
`in128/out2045` scores **3,211 total tok/s and 3,022 output tok/s**. So the
headline metric says "3.3× better" for the scenario that generates **4.9× fewer
tokens per second**. Any claim of the form "model X is N× faster" must name the
metric and the scenario.

## Speculative decoding changes what TPOT means

When the server drafts tokens speculatively, one engine step verifies
`1 + n_draft` tokens and emits `spec_accept_len` of them on average. The bench
then reports:

```
TPOT  = time per ACCEPTED token        (what a user waits per token)
ITL   = time per ENGINE STEP           (what the GPU actually spends)
ITL / TPOT == spec_accept_len          (exact, in every 2026-11 file)
```

So a spec-decode run can halve TPOT while making every step ~30 % slower. Two
runs are only comparable on `tpot_*` / `itl_*` if `spec_accept_len` is the same
(or is reported next to the number). `out_tok_s` and `total_tok_s` are unaffected
by this trap — they are wall-clock rates either way.

## Sweep definition drift

The 2026-08 runs used `--backend openai` (chat completions); the 2026-11 run used
`--backend vllm` (completions) and a newer bench client image. That is recorded
per run in `results/manifest.json` under `bench_flags` / `vllm_image`, and it is
one more reason the 2026-11 delta is a **stack** delta, not a model delta.

## What a fair comparison requires

1. Same vLLM version and same serve flags (chunked prefill, KV cache dtype,
   `--max-model-len`, `--gpu-memory-utilization`, speculative decoding on/off,
   `--max-num-seqs`) — these change throughput more than the model often does.
2. **Same number of GPUs**, same concurrency, same warm-up policy. If that is not
   possible, divide throughput by GPU count before comparing (`Avg tok/s / GPU` in
   the summary table; the count lives in `results/manifest.json` under `gpus`).
   Doubling the hardware is not an optimisation.
3. ≥3 repeats per scenario, reported with spread.
4. Both `total_tok_s` and `out_tok_s` reported, so prefill and decode are
   separable, and the speculative-decoding state reported (`spec_accept_len`),
   because it changes what `tpot_*` and `itl_*` measure.

The two Qwen runs in this repo are the only auditable ones, and they differ in GPU
count (1 vs 2). See [caveats.md](caveats.md).

## Re-running

```bash
# 1. start the server with a committed config
docker compose -f bench/serve/qwen3.6-27b-fp8.yml up -d

# 2. sweep it (writes results/<date>_<model>_<tag>/ + an _env.txt capture)
bench/run.sh --model qwen3.6-27b-fp8 --label "Qwen 27B" \
             --base-url http://localhost:9000 --served-model qwen/qwen3.6-27b

# 3. register + regenerate
python3 analysis/register.py --dir results/<run_id> --model qwen3.6-27b-fp8 \
             --label "Qwen 27B" --repeats 3 --notes "..."
make ingest report figures verify
```

`bench/run.sh` derives the output file prefix from `--model`, so results cannot
be mislabelled by copy-paste.
