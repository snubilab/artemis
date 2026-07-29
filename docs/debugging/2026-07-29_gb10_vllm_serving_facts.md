# GB10 vLLM Serving Facts

**Date:** 2026-07-29
**Box:** GB10, single unified 119.7 GiB pool shared between GPU and host
**Purpose:** Serving facts established while evaluating local models for the concept-mapping
benchmark. Written down so the next agent does not rediscover them.

Every number below was measured on this box on this date. Nothing here is estimated.

---

## 1. vLLM will not start without a clean env

`vllm_serve.sh` launches through `env -u PYTHONPATH -u PYTHONHOME`. Without it every
model dies at **import time, before touching the weights**:

```
torchvision/io/video.py -> AttributeError
```

Something on the inherited `sys.path` supplies a namespace-package `av`.
`torchvision/io/video.py` catches only `ImportError`, so the `AttributeError` escapes
and vLLM exits. The failure looks like a model/config problem and is not one.

Do not "fix" this by editing the shared venv. Launch clean.

## 2. Memory: only one number means what it says

| Source | Behaviour on GB10 |
| --- | --- |
| `nvidia-smi` global memory columns | **`Not Supported`** — unusable |
| `nvidia-smi --query-compute-apps=pid,used_memory` | **Works. The only trustworthy per-server number.** |
| `torch.cuda.mem_get_info()` free | **Undercounts by the reclaimable page cache** |
| `free -g` field 7 (`available`) | Correct; equals `free -h` `available` |

Measured instance of the `mem_get_info` trap: immediately after stopping a 51 GiB model,
`mem_get_info` reported **63.1 GiB free** while `free -g` reported **110 GiB available**
with **48 GiB in buff/cache**. Reading 51 GiB of safetensors fills the page cache; that
memory is reclaimable and a new allocation gets it. A "56 GiB still held" reading after a
clean stop is page cache, **not** a leaked process.

Distinguishing a real leak from page cache: `--query-compute-apps` lists a PID or it does
not. If no compute app is listed, nothing is leaked.

Real leaks do happen: `EngineCore` is a **separate child process** holding the whole pool.
Killing only the api_server parent leaves it resident and starves every other server.
`vllm_serve.sh stop` kills parent + children and waits for the allocator to hand memory back.

## 3. Per-model startup and residency

`--enforce-eager`, `--dtype auto`, `--max-model-len 16384`, single process, nothing else on the GPU.

| Model | Weights | Ready | First token | Resident | util |
| --- | --- | --- | --- | --- | --- |
| `google/medgemma-27b-text-it` | 51 GiB, 12 shards, `model_type: gemma3_text` | **367 s** | +2.5 s | **98435 MiB** | 0.80 |
| `google/gemma-4-31B-it` | 59 GiB | **460 s** | +3.0 s | **106559 MiB** | 0.85 |
| `snuh/hari-q3-8b` (production, :8000) | — | — | — | ~48372 MiB | 0.35 |

`google/gemma-4-26B-A4B-it` — **NOT RUN.** Never loaded. No claim either way.

Shard load runs ~26-28 s/shard cold. A reload right after a stop is faster because the
shards are still in page cache.

Big models are servable **one at a time**. Two 27B+ models cannot be co-resident in a
119.7 GiB pool. Small models can share.

## 4. The throughput ceiling — the number that decides feasibility

Measured on `medgemma-27b-text-it`:

| Mode | Result |
| --- | --- |
| Sequential | 500 completion tokens / 169.9 s = **2.94 tok/s** |
| 6-way concurrent | 1800 completion tokens / 241.6 s = **7.5 tok/s aggregate** |

The box is **memory-bandwidth bound** — ~50 GiB of weights streamed per token on unified
LPDDR. Batching buys only ~2.5x. `--enforce-eager` (disables CUDA graphs) likely costs
another ~2x; that has **not** been measured, so removing it is an untested lever, not a
known win.

Consequence: a 242-item benchmark emitting ~300 output tokens per call is ~72k tokens,
which is **hours per model arm** at 7.5 tok/s, not tens of minutes. Budget from measured
tok/s and your pipeline's actual `completion_tokens`, never from wall-clock intuition.
Sequential request loops get 2.94 tok/s and nothing more — issue calls concurrently.

## 5. Four silent-corruption shapes seen in one afternoon

All four produce a **clean-looking table** with no error surfaced. This is the pattern to
watch for on this stack.

1. **Critic model tier.** `select_critic_model()` in `auto` mode routes
   Condition/Drug/Measurement to `gpt-4o-mini`. Those are **217 of 242 items (90%)** of
   this benchmark, so a run labelled with a local model mostly reported OpenAI.
   Fixed: `quick_concept_benchmark_v2.py` defaults `AGENT2_CRITIC_MODEL_TIER=gpt-4o` and
   records the effective value as `critic_model_tier` in both payloads.

2. **Runtime env allowlist.** `bootstrap_runtime_env()` clears `os.environ` and retains
   only `ALLOWED_RUNTIME_ENV`. `VLLM_BASE_URL`/`VLLM_API_KEY` were missing, so a
   shell-exported local-model target was **wiped** and the run silently fell back to the
   default OpenAI model — mislabelling every local-model run. Both added.

3. **LLM timeout.** `--llm-timeout` defaults to **45 s**. At ~3 tok/s every item returns
   `error=timeout` and the harness still prints a complete table of `0.000`.

4. **Server swapped mid-run.** Stopping a vLLM server under a running benchmark produced
   174 `APIConnectionError`s; the harness completed and wrote its output anyway. Gate on
   `/v1/models` before starting and abort mid-run on a burst of connection errors.

Provenance beats vigilance: record the effective model, endpoint and critic tier **in the
result payload** so a later reader can tell whether a run was contaminated.

## 6. Data the benchmark needs and does not ship with

| Artifact | State | How to produce |
| --- | --- | --- |
| `data/benchmark_data/ohdsi_criteria_benchmark.json` | Absent | `BENCHMARK_STUDIES_DIR=$PWD/data/gold python scripts/extract_criteria_benchmark.py` |
| `omop_vocab/files/CONCEPT.csv` | Absent | `\copy (select concept_id, standard_concept, invalid_reason, domain_id, vocabulary_id from omop_vocab.concept) to stdout with (format csv, delimiter E'\t', header, null '')` |
| `omop_vocab/files/CONCEPT_RELATIONSHIP.csv` | Absent | same, from `omop_vocab.concept_relationship where relationship_id = 'Maps to'` |

Both vocabulary files are **tab-delimited with a header** (Athena format) — the resolver
uses `csv.DictReader(delimiter="\t")`. Sizes: 6.33M and 4.53M rows. Without them the
harness crashes at scoring **after** spending all the LLM time.

`extract_criteria_benchmark.py`'s default `STUDIES_DIR` (`data/ohdsi_studies`) does not
exist here; the studies are in `data/gold`. Override via `BENCHMARK_STUDIES_DIR`.

Generated dataset: **242 items across all six studies** — ARISTOTLE 58, CAROLINA 54,
EMPA-REG OUTCOME 46, CARMELINA 40, LEADER 28, PLATO 16. Domains: Condition 118, Drug 57,
Measurement 42, Procedure 25.

## 7. Study coverage limit

Only **ARISTOTLE, LEADER and PLATO** have `*_BENCHMARK` CDM sources in WebAPI.
CARMELINA, CAROLINA and EMPA-REG have gold criteria in `data/gold/` but no OMOP source.

So the six-study run works for **concept mapping** but not for anything requiring cohort
generation or attrition.

## 8. Endpoint wiring

- `artemis-api` reaches the host at **`http://61.107.200.12:8000/v1`** (`VLLM_BASE_URL`).
  `host.docker.internal` does **not** resolve from the container.
- Because that is pinned to **:8000**, serving a candidate model on :8001 requires
  recreating the container. Serving on :8000 does not.
- The model is passed **per request** (`{"model": "..."}`), so the container's `LLM_MODEL`
  does not need changing.
- `vllm/` prefix routing: `get_llm()` strips `vllm/` and sends the remainder, so the
  request model must be `vllm/<served-model-name>`.
- `:8000` is hari's production port (`snuh/hari-q3-8b`, util 0.35, len 16384,
  `--tool-call-parser qwen3_xml`). Restore it when done.

---

## Files touched on this date

- `scripts/vllm_serve.sh` — `env -u PYTHONPATH -u PYTHONHOME` launch; `medgemma-27b-text` alias
- `scripts/quick_concept_benchmark_v2.py` — critic tier default + `critic_model_tier` provenance
  in both payloads; `VLLM_BASE_URL`/`VLLM_API_KEY` added to `ALLOWED_RUNTIME_ENV`
- `scripts/extract_criteria_benchmark.py` — `STUDIES_DIR` overridable via `BENCHMARK_STUDIES_DIR`

## What was NOT established

No model-comparison results were produced. No arm of the benchmark was run to completion.
`gemma-4-26B-A4B-it` was never loaded. The `--enforce-eager` speedup was never measured.
These are open, not failed.
