# Benchmark Full Results — 2026-04-01

## Status Summary

| Task | Status |
|------|--------|
| 100-sample LLM benchmarks (gpt-4.1, 4.1-mini, 5-chat, 5.1, 5.2, 5.4, o4-mini) | DONE |
| 100-sample Agent2-v2 benchmark | DONE |
| 100-sample RAG recheck benchmark | DONE |
| RAG full (7,945 items) — PID 90977 | CRASHED (no output file) |
| LLM full runs (7,945 items) — PIDs 34478/81/87/92/99/500 | IN PROGRESS (stdout→/dev/null) |
| Agent2 full (7,945 items) — container artemis-api | STARTED 10:42 KST |

Note: All LLM full-run processes started at ~10:37 KST. They are sleeping (SN state) while awaiting API responses.
Expected completion: several hours depending on rate limits.

---

## Overall Metrics (N=100, matched sample IDs)

| Model | Recall | Precision | F1 | Hit@1 | Hit@5 | Hit@10 | Lat (s/item) |
|-------|--------|-----------|-----|-------|-------|--------|-------------|
| **agent2-v2** | **0.341** | **0.322** | **0.287** | 0.270 | **0.570** | **0.570** | 24.8 |
| RAG (MedCPT, recheck) | 0.279 | 0.055 | 0.076 | 0.140 | 0.370 | 0.490 | 1.15 |
| gpt-5.4 | 0.167 | 0.126 | 0.106 | **0.270** | 0.340 | 0.360 | 2.5 |
| gpt-5.2 | 0.162 | 0.118 | 0.095 | 0.260 | 0.320 | 0.320 | 2.3 |
| gpt-4.1 | 0.149 | 0.025 | 0.035 | 0.240 | 0.320 | 0.330 | 3.3 |
| gpt-5-chat | 0.136 | 0.048 | 0.059 | 0.260 | 0.320 | 0.320 | 1.5 |
| gpt-5.1 | 0.134 | 0.033 | 0.037 | 0.260 | 0.310 | 0.320 | 2.2 |
| gpt-4.1-mini | 0.067 | 0.010 | 0.015 | 0.120 | 0.140 | 0.140 | 2.7 |
| o4-mini | 0.037 | 0.058 | 0.031 | 0.090 | 0.100 | 0.100 | 24.4 |

> Corrected comparison uses matched `sample_ids` across methods.
> The earlier `bench_rag_agent2_20260401_093640.json` artifact was invalid for RAG reporting because it stored empty `pred_raw_ids` for all 100 items.
> Publication-ready table with 95% bootstrap CI is available at:
> `artemis/output/benchmark_results/2026-04-01_paper_method_comparison_sample100.md`

---

## 2026-04-02 Addendum: Hybrid Ablations on the Same Matched Sample-100

### Added Hybrid Rows

| Model | Recall | Precision | F1 | Hit@1 | Hit@5 | Hit@10 | Lat (s/item) |
|-------|--------|-----------|-----|-------|-------|--------|-------------|
| GPT54 RAG (EASTUS2) | 0.194 | 0.238 | 0.165 | 0.400 | 0.450 | 0.450 | 3.6 |
| LLM RAG (gpt-4o + MedCPT) | 0.197 | 0.203 | 0.156 | 0.340 | 0.440 | 0.440 | 2.7 |

Artifacts:
- `artemis/data/benchmark_results/bench_gpt54_rag_sample100_eastus2.json`
- `artemis/data/benchmark_results/bench_llm_rag_sample100.json`

### Addendum Insights

- Both hybrid ablations outperform plain `RAG` on `Precision` and `F1` by a wide margin.
- `RAG` remains recall-oriented (`R=0.279`, `P=0.055`, `F1=0.076`), while the hybrids trade some recall for much better precision and overall F1.
- `GPT54 RAG` is the strongest hybrid row so far:
  - `F1=0.165` vs `0.156` for `LLM RAG`
  - `F1=0.165` vs `0.106` for best `LLM Direct (gpt-5.4)`
- `Ours` still remains clearly ahead (`F1=0.287`), so the extra layers beyond retrieval + LLM selection still matter materially:
  - UMLS expansion
  - KG expansion
  - critic / refiner
  - additional domain-aware post-processing
- Interpretation boundary remains the same:
  - these hybrid rows still use `concept_set_name` as input
  - they are concept-name mapping ablations, not full free-text criterion-understanding evaluations
- Operational note:
  - the first `GPT54 RAG` attempt failed on the default Azure endpoint due to `DeploymentNotFound`
  - the valid `GPT54 RAG` row uses the EASTUS2 Azure endpoint override

---

## Evaluation Method

- Each criterion is evaluated as a set of concept IDs, not a single-label classification.
- For a given criterion:
  - `precision = |pred ∩ gold| / |pred|`
  - `recall = |pred ∩ gold| / |gold|`
  - `f1 = 2PR / (P+R)`
- Metrics are computed after OMOP normalization (`Maps to`) and reported as macro averages across criteria.
- `Hit@1`, `Hit@5`, and `Hit@10` indicate whether at least one gold concept appears within the top-k predicted IDs.

---

## Domain Breakdown (N=100, 25 items per domain)

### Condition Domain (n=25)

| Model | Recall | F1 | Hit@1 |
|-------|--------|-----|-------|
| agent2-v2 | 0.244 | 0.215 | 0.000 |
| gpt-5.1 | 0.109 | 0.063 | 0.000 |
| gpt-5.4 | 0.093 | 0.066 | 0.000 |
| gpt-5-chat | 0.072 | 0.028 | 0.000 |
| gpt-4.1 | 0.062 | 0.027 | 0.000 |
| gpt-5.2 | 0.052 | 0.030 | 0.000 |
| gpt-4.1-mini | 0.031 | 0.024 | 0.000 |
| o4-mini | 0.029 | 0.033 | 0.000 |

### Drug Domain (n=25)

| Model | Recall | F1 | Hit@1 |
|-------|--------|-----|-------|
| agent2-v2 | 0.607 | 0.580 | 0.000 |
| gpt-5.2 | 0.232 | 0.156 | 0.000 |
| gpt-5.4 | 0.189 | 0.131 | 0.000 |
| gpt-5-chat | 0.149 | 0.029 | 0.000 |
| gpt-5.1 | 0.143 | 0.027 | 0.000 |
| gpt-4.1 | 0.116 | 0.027 | 0.000 |
| gpt-4.1-mini | 0.000 | 0.000 | 0.000 |
| o4-mini | 0.000 | 0.000 | 0.000 |

### Procedure Domain (n=25)

| Model | Recall | F1 | Hit@1 |
|-------|--------|-----|-------|
| agent2-v2 | 0.117 | 0.087 | 0.000 |
| gpt-5.1 | 0.006 | 0.006 | 0.000 |
| gpt-5-chat | 0.003 | 0.003 | 0.000 |
| gpt-4.1 | 0.001 | 0.001 | 0.000 |
| gpt-5.4 | 0.001 | 0.001 | 0.000 |
| gpt-4.1-mini | 0.001 | 0.001 | 0.000 |
| gpt-5.2 | 0.000 | 0.000 | 0.000 |
| o4-mini | 0.000 | 0.000 | 0.000 |

### Measurement Domain (n=25)

| Model | Recall | F1 | Hit@1 |
|-------|--------|-----|-------|
| gpt-4.1 | 0.417 | 0.085 | 0.000 |
| agent2-v2 | 0.397 | 0.265 | 0.000 |
| gpt-5.4 | 0.383 | 0.228 | 0.000 |
| gpt-5.2 | 0.363 | 0.195 | 0.000 |
| gpt-5-chat | 0.320 | 0.174 | 0.000 |
| gpt-5.1 | 0.278 | 0.054 | 0.000 |
| gpt-4.1-mini | 0.237 | 0.035 | 0.000 |
| o4-mini | 0.117 | 0.091 | 0.000 |

---

## Key Findings

### 1. Agent2-v2 vs LLM Direct vs RAG

- **Agent2-v2 is the clear winner overall** (Recall 0.341, F1 0.287) vs best LLM (gpt-5.4, Recall 0.167, F1 0.106)
- Agent2 recall advantage: **2.04x** over best LLM on recall; **2.71x** on F1
- RAG recovered meaningful recall (**0.279**) after rerun, but precision remained low (**0.055**)
- Agent2 dominates Drug domain (0.607 vs 0.232 for gpt-5.2)
- Agent2 is the only model with reasonable Procedure recall (0.117)
- Measurement: LLM models are competitive, gpt-4.1 actually edges Agent2 (0.417 vs 0.397)
- Trade-off: Agent2 is ~10x slower than top LLM direct baselines and ~20x slower than RAG

### 2. RAG Zero-Score Artifact Was Invalid

- The prior RAG row with all-zero scores came from an artifact where `pred_raw_ids=[]` for every item.
- Fresh RAG rerun on the same `sample_ids` produced non-zero metrics with zero recorded errors.
- Manuscript-facing tables should use the rerun artifact:
  - `artemis/data/benchmark_results/bench_rag_recheck_20260401_135233.json`

### 3. LLM Model Ranking (overall recall)

gpt-5.4 > gpt-5.2 > gpt-4.1 > gpt-5-chat ≈ gpt-5.1 > gpt-4.1-mini >> o4-mini

### 4. o4-mini Underperformance

- Surprising: o4-mini (0.037 recall) significantly underperforms all GPT-5.x models
- Latency is similar to Agent2 (24.4s) but quality is much worse
- May have prompt format issues or reasoning mode penalty for direct concept lookup

### 5. Agent2-v1 vs v2 Discrepancy

- v1 (03:00 KST run): recall=0.010 — broken/invalid pipeline artifact
- v2 (09:47 KST run): recall=0.341 — validated current production pipeline
- Current paper table should exclude v1-era artifacts except for explicit failure analysis

### 6. How To Read Condition Performance

- Condition domain should not be interpreted the same way as clean single-disease classification.
- A substantial fraction of low-performing Condition criteria are not simple disease names, but broad condition buckets or concept-set proxies that expand to large OMOP descendant sets.
- Representative hard cases include:
  - `conditions indicating established cardiovascular disease`
  - `Malignant neoplasms of lymphoma`
  - `Parkinsonism confounder conditions`
  - `Chronic Stable Angina (no descendants)`
  - `Type 2 Diabetes Mellitus`
  - `Non ST Elevated Myocardial Infarction`
- In these cases, failure is often driven by one of two mechanisms:
  - the gold set is structurally large, so partial recovery still yields low recall
  - the model overpredicts semantically nearby cardiovascular or inflammatory concepts, which collapses precision

### 7. Noise-Aware Interpretation

- The benchmark contains a meaningful number of criteria whose labels include project tags, bracketed prefixes, proxy wording, or compositional mixed phrases.
- Examples of these hard cases include:
  - `[DOAC]Transient atrial fibrillation (cardiac surgery, pericarditis, myocarditis, pulmonary embolism)`
  - `[plp tutorial 2018] antipsychotic drug/measurement/observation/procedure`
  - `[PhenotypePhebruary][Alzheimer] Dementia`
- When filtering out three hard-case groups:
  - noisy tagged labels
  - broad / ambiguous labels
  - compositional mixed phrases
  the remaining Agent2 keep set (`427` rows from the current partial run) improves to:
  - macro Precision `0.1893`
  - macro Recall `0.4196`
  - macro F1 `0.1852`
- This should be treated as a diagnostic secondary view, not a replacement for the main benchmark table.

### 8. Condition-Only Filtered Subset

- On the filtered keep set, Condition remains recall-oriented rather than precision-oriented:
  - Precision `0.1506`
  - Recall `0.4277`
  - F1 `0.1554`
- The dominant failure patterns are:
  - large gold concept sets (`>=10`)
  - overprediction on small-gold cases (`gold <= 2`, `pred >= 10`)
  - partial rather than total failure
- Representative low-precision / high-recall examples:
  - `Disseminated intravascular coagulation`
  - `Pancreatitis`
  - `Chronic Pancreatitis`
- Representative stronger Condition cases:
  - `Guillian-Barre syndrome`
  - `Alcoholic Pancreatitis`
  - `Takotsubo cardiomyopathy`
  - `Myocarditis Pericarditis`

---

## Currently Running Processes

### LLM Full Runs (7,945 items each)

| Model | PID | Save Path | Log |
|-------|-----|-----------|-----|
| gpt-4o | 34478 | bench_llm_gpt_4o_full_20260401_103722.json | stdout→/dev/null |
| gpt-4.1 | 34481 | bench_llm_gpt_4_1_full_20260401_103722.json | stdout→/dev/null |
| gpt-5-chat | 34487 | bench_llm_gpt_5_chat_full_20260401_103722.json | stdout→/dev/null |
| gpt-5.1 | 34492 | bench_llm_gpt_5_1_full_20260401_103722.json | stdout→/dev/null |
| gpt-5.2 | 34499 | bench_llm_gpt_5_2_full_20260401_103722.json | stdout→/dev/null |
| gpt-5.4 | 34500 | bench_llm_gpt_5_4_full_20260401_103722.json | stdout→/dev/null |

### Agent2 Full Run (7,945 items)

- Container: `artemis-api`
- Log: `docker exec artemis-api tail -f /tmp/bench_agent2_full.log`
- Result: `/app/data/benchmark_results/bench_agent2_full_20260401_104612.json`
- Started: 10:46 KST (restart after NEO4J_URI env fix)
- Speed: ~9 items/min → ETA ~14-15 hours (complete ~01:00 KST next day)
- Fix applied: Added NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD to ALLOWED_RUNTIME_ENV in benchmark script

### RAG Full Run

- PID 90977 crashed — no output file generated at `bench_rag_full_20260401_100006.json`
- Recommend restarting RAG full run when bandwidth allows

---

## Result File Reference

All results at `/Users/kyh/Workspace/Broadsea/artemis/data/benchmark_results/`

| File | N | Model | Status |
|------|---|-------|--------|
| bench_gpt41.json | 100 | gpt-4.1 | Done |
| bench_gpt41mini.json | 100 | gpt-4.1-mini | Done |
| bench_gpt5chat.json | 100 | gpt-5-chat | Done |
| bench_gpt51.json | 100 | gpt-5.1 | Done |
| bench_gpt52.json | 100 | gpt-5.2 | Done |
| bench_gpt54.json | 100 | gpt-5.4 | Done |
| bench_o4mini.json | 100 | o4-mini | Done |
| bench_rag_recheck_20260401_135233.json | 100 | RAG (validated rerun) | Done |
| bench_agent2_20260401_094702.json | 100 | Agent2-v2 | Done |
| bench_llm_gpt_4o_full_20260401_103722.json | 7945 | gpt-4o | Running |
| bench_llm_gpt_4_1_full_20260401_103722.json | 7945 | gpt-4.1 | Running |
| bench_llm_gpt_5_chat_full_20260401_103722.json | 7945 | gpt-5-chat | Running |
| bench_llm_gpt_5_1_full_20260401_103722.json | 7945 | gpt-5.1 | Running |
| bench_llm_gpt_5_2_full_20260401_103722.json | 7945 | gpt-5.2 | Running |
| bench_llm_gpt_5_4_full_20260401_103722.json | 7945 | gpt-5.4 | Running |
| bench_agent2_full_20260401_104229.json | 7945 | Agent2 (container) | Running |

---

## Next Steps

1. **Wait for full runs to complete** — check periodically:
   ```bash
   ls -la artemis/data/benchmark_results/bench_llm_*_20260401_103722.json
   docker exec artemis-api tail -5 /tmp/bench_agent2_full.log
   ```

2. **Parse full results** once files appear — use same aggregate parsing pattern

3. **Restart RAG full** after Agent2 finishes to avoid resource contention

4. **Investigate Hit@1 domain bug** — aggregate shows nonzero but per-domain shows 0.000

5. **Compare 100 vs 7945 results** to assess how much variance there is in the 100-sample estimates
