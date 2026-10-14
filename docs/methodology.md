# Methodology

## What was measured

Each data point is one `vllm bench serve` run: a fixed number of synthetic
requests (`--dataset-name random`) with a fixed prompt length and a fixed
generation length, all submitted at once against a warm server.

| Parameter | Value | Notes |
|---|---|---|
| Dataset | `random` | token ids are random; no real-world prompt structure, no cache hits |
| Prompts per scenario | 100 | identical across all three models |
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

Full column contract: [`../analysis/schema.md`](../analysis/schema.md).

## Why the headline metric is dangerous

`total_tok_s` rewards prefill. At `in2048/out128` the harness feeds 204,800
prompt tokens and generates only 12,800 — a 16:1 ratio. Concretely, for Qwen
that scenario scores **10,488 total tok/s but only 617 output tok/s**, while
`in128/out2045` scores **3,211 total tok/s and 3,022 output tok/s**. So the
headline metric says "3.3× better" for the scenario that generates **4.9× fewer
tokens per second**. Any claim of the form "model X is N× faster" must name the
metric and the scenario.

## What a fair comparison requires

1. Same vLLM version and same serve flags (chunked prefill, KV cache dtype,
   `--max-model-len`, `--gpu-memory-utilization`) — these change throughput more
   than the model often does.
2. Same GPU, same concurrency, same warm-up policy.
3. ≥3 repeats per scenario, reported with spread.
4. Both `total_tok_s` and `out_tok_s` reported, so prefill and decode are
   separable.

Only the Qwen run in this repo satisfies (1) well enough to audit; the other two
runs have no recorded serve flags. See [caveats.md](caveats.md).

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
