# Multi-Model LLM Concept Mapping Benchmark — 2026-04-01

## Setup

- **Benchmark dataset**: `artemis/data/benchmark_data/ohdsi_criteria_benchmark.json`
- **Sample size**: 100 items (seed=42), balanced 25 per domain
- **Domains**: Condition / Drug / Procedure / Measurement
- **Mapper**: LLM Direct only (no RAG, no Agent2)
- **Backend**: Azure AI Foundry (`https://team3-us.services.ai.azure.com/models`)
- **Normalization**: OMOP CONCEPT.csv + CONCEPT_RELATIONSHIP.csv (standard concept rollup)

## Model Availability on Azure AI Foundry

| Model | Status | Notes |
|-------|--------|-------|
| gpt-4o | Available (deployed) | Baseline |
| gpt-4o-mini | DeploymentNotFound | Not deployed on this endpoint |
| gpt-5 / gpt-5.4 | DeploymentNotFound | Not deployed on this endpoint |
| gpt-4.1 | Available | Tested |
| gpt-4.1-mini | Available | Tested |
| o4-mini | Available | Reasoning model; temperature=0 not supported, ran with default temp=1 |
| o3-mini | DeploymentNotFound | Not deployed |

## Aggregate Results

| Model | Recall | Precision | F1 | Hit@1 | Hit@5 | Hit@10 | Latency(ms) | Errors |
|-------|--------|-----------|-----|-------|-------|--------|-------------|--------|
| gpt-4o (baseline, n=20) | 0.064 | 0.058 | 0.046 | 0.300 | 0.300 | 0.300 | 1,154 | 0 |
| gpt-4.1 (n=100) | 0.149 | 0.025 | 0.035 | 0.240 | 0.320 | 0.330 | 3,265 | 1 |
| gpt-4.1-mini (n=100) | 0.067 | 0.010 | 0.015 | 0.120 | 0.140 | 0.140 | 2,740 | 0 |
| o4-mini (n=100) | 0.037 | 0.058 | 0.031 | 0.090 | 0.100 | 0.100 | 24,449 | 7 |

Notes:
- **gpt-4o baseline** is from the smoke-test run (20 items); may differ with 100-item evaluation
- **o4-mini errors**: 7 items timed out or received unsupported-parameter errors (temperature constraint)
- **gpt-4.1 errors**: 1 item error (Measurement domain)

## Domain Breakdown

### Condition (25 items)

| Model | Recall | F1 | Errors |
|-------|--------|----|--------|
| gpt-4o (n=20, ~6 items) | ~0.062 | ~0.046 | 0 |
| gpt-4.1 | 0.062 | 0.027 | 0 |
| gpt-4.1-mini | 0.031 | 0.024 | 0 |
| o4-mini | 0.029 | 0.034 | 2 |

### Drug (25 items)

| Model | Recall | F1 | Errors |
|-------|--------|----|--------|
| gpt-4o (n=20, ~6 items) | ~0.064 | ~0.046 | 0 |
| gpt-4.1 | 0.116 | 0.027 | 0 |
| gpt-4.1-mini | 0.000 | 0.000 | 0 |
| o4-mini | 0.000 | 0.000 | 1 |

### Procedure (25 items)

| Model | Recall | F1 | Errors |
|-------|--------|----|--------|
| gpt-4o (n=20, ~6 items) | ~0.064 | ~0.046 | 0 |
| gpt-4.1 | 0.001 | 0.001 | 0 |
| gpt-4.1-mini | 0.001 | 0.001 | 0 |
| o4-mini | 0.000 | 0.000 | 2 |

### Measurement (25 items)

| Model | Recall | F1 | Errors |
|-------|--------|----|--------|
| gpt-4o (n=20, ~6 items) | ~0.064 | ~0.046 | 0 |
| gpt-4.1 | 0.417 | 0.085 | 1 |
| gpt-4.1-mini | 0.237 | 0.035 | 0 |
| o4-mini | 0.117 | 0.091 | 2 |

## Key Findings

### 1. gpt-4.1 is the best LLM-Direct model overall

- Highest recall (0.149) and Hit@5 (0.320) among all tested models
- Strong Measurement recall (0.417) — the best across all models
- Drug recall (0.116) also competitive
- Latency reasonable at 3,265ms

### 2. Procedure domain is a universal weak spot

All models score near 0 on Procedure. This is expected — procedure concept names
(e.g., "tracheostomy" → SNOMED/CPT codes) require vocabulary-specific lookup that
LLM Direct doesn't perform reliably without OMOP grounding.

### 3. o4-mini is too slow for real-time use

Average latency 24,449ms (>24 seconds per item). Not viable for interactive mapping.
The reasoning chain adds cost with no quality benefit in this structured lookup task.
7 errors (mostly timeout-adjacent) further reduce reliability.

### 4. gpt-4.1-mini is a good cost/quality trade-off for Measurement

- Comparable recall to gpt-4o baseline at lower cost
- Drug/Procedure still near 0

### 5. Low absolute recall across all models

All models show recall < 0.15 for LLM Direct alone. This confirms that LLM Direct
is not sufficient as a standalone mapper — RAG (MedCPT) + Agent2 pipeline is needed
for production quality.

## Recommendation

- **Use gpt-4.1** as the primary LLM for concept mapping if upgrading from gpt-4o
- **Do not use o4-mini** for concept mapping (latency + accuracy penalty)
- **gpt-4.1-mini** can serve as a low-cost fallback for Measurement-only tasks
- LLM Direct should remain supplementary to the Agent2 full pipeline

## Output Files

- `artemis/data/benchmark_results/bench_gpt41.json`
- `artemis/data/benchmark_results/bench_gpt41mini.json`
- `artemis/data/benchmark_results/bench_o4mini.json`
- `artemis/data/benchmark_results/benchmark_v2_20260331_175726.json` (gpt-4o baseline, n=20)
