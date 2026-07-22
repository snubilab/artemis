# 2026-04-01 Benchmark Failure Analysis

## Scope

Files reviewed:

- `artemis/scripts/quick_concept_benchmark.py`
- `artemis/data/benchmark_results/quick_benchmark_20260331_162257.json`
- `artemis/data/benchmark_results/quick_benchmark_20260331_162258.json`
- `artemis/data/benchmark_data/ohdsi_criteria_benchmark.json`

New fix:

- `artemis/scripts/quick_concept_benchmark_v2.py`

## Executive summary

The broken quick benchmark was not measuring the intended benchmark at all.

The script was:

1. loading `/app/data/atlas_cohorts/*.json` instead of `ohdsi_criteria_benchmark.json`
2. round-robin sampling all domains, so only `12/50` sampled items were clinical and `38/50` were administrative or otherwise non-clinical
3. scoring raw concept IDs with exact-set overlap only, even though the real benchmark gold uses `ground_truth_concept_ids` and many comparisons need standard/non-standard normalization
4. timing out Agent2 incorrectly because the `ThreadPoolExecutor` context manager still blocked on shutdown after the timeout fired

The aggregate metrics in the saved runs are therefore not trustworthy as concept-mapping benchmark numbers.

## Evidence from the reviewed files

### 1. The script is wired to the wrong dataset

`quick_concept_benchmark.py` loads ATLAS cohort JSON files:

- `atlas_dir = "/app/data/atlas_cohorts"`
- `load_concept_set_items(...)` extracts concept sets directly from those files

It never reads `artemis/data/benchmark_data/ohdsi_criteria_benchmark.json`.

That mismatch is visible immediately in the samples:

- Broken run first items include values like `genders`, `Emergency Room`, `Primary Care Provider Specialties`, `AMMS group prefix for Fully Insured`
- The intended benchmark file’s first 20 items are all `Condition` criteria such as `Narcolepsy`, `Bell's palsy`, `Appendicitis`

This means the reported metrics were computed on the wrong corpus.

### 2. The saved runs were dominated by non-clinical domains

Both broken result files have the same sample distribution:

- sample size: `50`
- clinical domains (`Condition`, `Drug`, `Procedure`, `Measurement`): `12`
- non-clinical domains: `38`

Top sampled domains were evenly round-robin mixed, including:

- `Visit`
- `Observation`
- `Device`
- `Meas Value`
- `Specimen`
- `Geography`
- `Gender`
- `Provider`
- `Revenue Code`
- `Sponsor`
- `Metadata`

So the quick benchmark was mostly measuring easy administrative/domain-enumeration guesses, not clinical concept mapping.

### 3. The output format dropped the gold IDs

`quick_concept_benchmark.py` saves:

```python
{k: v for k, v in row.items() if k != "gold_ids"}
```

Result:

- `150/150` saved per-item rows in each broken JSON are missing gold IDs
- post-hoc inspection cannot validate why a row scored as it did

This did not change the in-memory aggregate during the run, but it made later diagnosis much harder.

## Root cause by metric

### Agent2 = 0.0

This was wrong for two reasons.

#### Root cause A: the timeout was not real

The old code did this per item:

```python
with ThreadPoolExecutor(max_workers=1) as ex:
    fut = ex.submit(_agent2_call, agent2, name, domain)
    pred_ids = fut.result(timeout=30)
```

When `fut.result(timeout=30)` timed out, the code set `pred_ids = []`, but the surrounding `with ThreadPoolExecutor(...)` still executed `shutdown(wait=True)` on exit and waited for the worker thread anyway.

That is why the saved "30s timeout" latencies are not ~30s:

- run 1 Agent2 average latency: `45085.9 ms`
- run 2 Agent2 average latency: `46038.0 ms`

And why most rows were empty:

- run 1 Agent2 empty predictions: `42/50`
- run 2 Agent2 empty predictions: `40/50`

So the script was converting slow/hanging Agent2 calls into empty predictions, then still waiting for them in the background. That collapses recall to zero while pretending there was a timeout policy.

#### Root cause B: the sample was mostly the wrong kind of item

Even when Agent2 returned something, it was often on non-clinical benchmark rows that should not have been in this benchmark at all.

The second run proves this. Agent2 was not truly "always zero":

- run 1 aggregate recall: `0.000`
- run 2 aggregate recall: `0.002`

The tiny non-zero on run 2 came from a few rows finishing before the bad timeout pattern bit, not from a stable benchmark result.

### LLM Direct = 0.103

This number was suspicious because it was artificially inflated by the wrong sample mix.

Evidence from broken run 1 by-domain F1:

- `Visit`: `0.711`
- `Gender`: `0.476`
- `Place of Service`: `0.286`
- `Provider`: `0.211`
- `Revenue Code`: `0.143`

Those are administrative/enumeration-style domains where an LLM can guess common OMOP concepts without doing real clinical mapping.

When I recomputed the same broken runs on the clinical subset only, the apparent signal disappeared:

- run 1 clinical-only LLM recall: `0.0101`
- run 2 clinical-only LLM recall: `0.0076`

So the reported `0.103` overall recall was not a valid clinical benchmark number. It was mostly non-clinical-domain inflation.

There was a second issue too: the old benchmark did raw exact-ID comparison against the wrong source data, not the `ground_truth_concept_ids` field from `ohdsi_criteria_benchmark.json`, and it did not normalize standard vs non-standard IDs. That means even real vocabulary-equivalent matches could be undercounted.

Net effect:

- the wrong sample made the LLM look too good overall
- the wrong scorer still undercounted legitimate clinical matches

So `0.103` was both misleadingly high and methodologically wrong.

### RAG = 0.031

This number was wrong for two separate reasons.

#### Root cause A: wrong sample population

RAG was evaluated on the same `50`-item mixed-domain sample, not the clinical criteria benchmark.

When I recomputed the broken run on the clinical-only subset, the already-low score collapsed further:

- run 1 clinical-only RAG recall: `0.0032`
- run 2 clinical-only RAG recall: `0.0032`

So the reported `0.031` was also being distorted by non-clinical rows.

#### Root cause B: the RAG call ignored the domain hint

`rag.search(...)` supports `domain_filter`, but the broken script called:

```python
candidates = rag.search(name, n_results=top_k)
```

with no domain filter at all.

That means a clinical query like a measurement or procedure searched the full concept space, not the known target domain from the benchmark item. For a retrieval baseline that is a direct benchmark bug.

#### Root cause C: exact raw-ID scoring undercounted vocabulary-equivalent hits

The old metric logic compared raw `pred_ids` vs raw `gold_ids` directly. That ignores:

- non-standard gold concepts
- `Maps to` standard substitutions
- vocabulary mismatches where the prediction is standard but the gold seed is not

So the `0.031` was not just low; it was computed with the wrong benchmark population and the wrong matching logic.

## Fixes applied in `quick_concept_benchmark_v2.py`

### 1. Correct dataset and domain filtering

The new script:

- loads `artemis/data/benchmark_data/ohdsi_criteria_benchmark.json`
- uses `ground_truth_concept_ids` as the gold field
- filters benchmark items to clinical domains only:
  - `Condition`
  - `Drug`
  - `Procedure`
  - `Measurement`
- stratifies the sample across those four domains only

### 2. Correct Agent2 timeout handling

The new script replaces the broken executor context-manager pattern with a real per-item timeout wrapper based on a daemon thread:

- timeout is configurable
- default Agent2 timeout is `120s`
- if a call exceeds the timeout, the row records a clear timeout error instead of silently blocking on executor shutdown

This fixes the specific failure mode that produced empty Agent2 rows with fake 30s timeout semantics.

### 3. Correct evaluation logic

The new scorer:

- preserves `gold_raw_ids` in memory and output
- normalizes both gold and predictions offline using local OMOP vocabulary files:
  - `omop_vocab/files/CONCEPT.csv`
  - `omop_vocab/files/CONCEPT_RELATIONSHIP.csv`
- maps non-standard concepts through `Maps to` before scoring
- falls back to raw IDs only when no standard mapping exists

This makes recall/precision comparison use the right benchmark field and the right concept-ID equivalence logic.

### 4. Domain-aware RAG and LLM calls

Additional pragmatic fixes in v2:

- RAG now passes `domain_filter=item["domain"]`
- LLM Direct prompt now includes the target clinical domain
- v2 preserves per-item errors and latencies so service failures are visible instead of silently collapsing into empty rows

## Verification

### Main verification run

Command:

```bash
conda run -n artemis python artemis/scripts/quick_concept_benchmark_v2.py \
  --sample 20 \
  --mappers rag,agent2 \
  --agent2-timeout 120
```

Result:

| Mapper | Precision | Recall | F1 | Hit@1 | Hit@5 | Hit@10 | Latency |
|--------|-----------|--------|----|-------|-------|--------|---------|
| RAG | 0.048 | 0.267 | 0.062 | 0.100 | 0.350 | 0.450 | 650 ms |
| Agent2 | 0.050 | 0.050 | 0.050 | 0.050 | 0.050 | 0.050 | 7,236 ms |

Domain-balanced sample:

- `Condition`: 5
- `Drug`: 5
- `Procedure`: 5
- `Measurement`: 5

Important observations:

- `RAG` now shows meaningful non-zero recall on the intended clinical benchmark.
- `Agent2` no longer reports the fake timeout pattern from the broken run.
- `Agent2` rows show real latency instead of "timed out at 30s but still waited anyway".

Example preview rows from the verification run:

- `microscopic hematuria`
  - `RAG`: recall `1.000`
  - `Agent2`: recall `1.000`
- `[TROY lab] Total bilirubin`
  - `RAG`: recall `0.500`
  - `Agent2`: recall `0.000`
- `tracheostomy`
  - `RAG`: recall `0.227`
  - `Agent2`: recall `0.000`

This satisfies the minimum verification requirement:

- at least one clinical mapper (`RAG`) shows non-zero recall
- `Agent2` reports actual latency instead of the broken timeout artifact

### LLM Direct error-path smoke test

Because outbound LLM calls are blocked in this sandbox, I validated that the new script reports a clear error instead of hanging or crashing.

Command:

```bash
conda run -n artemis python artemis/scripts/quick_concept_benchmark_v2.py \
  --sample 1 \
  --mappers llm \
  --llm-timeout 45
```

Observed result:

- `LLM Direct` latency: `1386 ms`
- `Errors`: `1`
- per-item error: `APIConnectionError: Connection error.`

That confirms the fixed script handles unavailable LLM service cleanly.

## Deliverables completed

- created `artemis/scripts/quick_concept_benchmark_v2.py`
- ran a 20-item clinical-only verification sample
- documented the RCA and verification here

## Bottom line

The original quick benchmark failed because it benchmarked the wrong dataset, mixed mostly non-clinical domains into the sample, used broken timeout semantics for Agent2, and scored raw IDs without normalizing the gold benchmark field correctly.

`quick_concept_benchmark_v2.py` fixes all of those issues and produces clinically meaningful benchmark output in this sandboxed environment.
