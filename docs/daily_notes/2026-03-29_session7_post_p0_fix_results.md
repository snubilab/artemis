# Session 7: Post-P0 Fix Mapping Results (Study 420)

**Date:** 2026-03-29
**Branch:** feat/agent2-mapping-accuracy
**Context:** After applying P0 fixes (Bug 1-3), ran process_eligibility on Study 420 (LEADER trial)

## Applied Fixes (all committed)

| Commit | Fix |
|--------|-----|
| `6c3c229` | Use criterion domain for CIRCE criteria type (Bug 2) |
| `688f10d` | Split compound 'or' drug class queries for ATC expansion (Bug 3) |
| `ebe0a03` | Skip isGroupLabel rows in ordered_pairs reconstruction |
| `7cdc337` | Skip group-label criteria from Agent2 mapping |

## Mapping Run Stats

- **Total Agent2 Result calls:** 170
- **Per-criterion avg:** 220 seconds (~3.7 min)
- **Range:** 33s (fastest) to 449s (slowest)
- **All slow path** (Critic LLM gpt-4o on every criterion)
- **Generated concept sets:** 79

## Results: Study 420 Concept Sets

### Positive Findings
- GLP-1 RA mapped to drug concepts: liraglutide (3 items), sitagliptin (1 item)
- Drug class expansion working (compound 'or' split)

### Critical Issues Found

#### 1. Roll-up Overbroad (P1)
Expression Builder rolls up specific concepts into overly broad ancestors:
- "Cerebrovascular disease" (4 concepts) — should be specific stroke/TIA
- "Clinical finding" (appears 5 times) — meaningless ancestor
- "Disease" (appears 2 times) — meaningless ancestor
- "Observable entity" — meaningless
- "Disorder of cardiovascular system" (appears 4 times, 3-4 concepts each)
- "Digestive system finding" — too broad

#### 2. Duplicate Concept Sets (P1)
Same criterion mapped multiple times due to parallel workers:
- "Medullary thyroid carcinoma" — **6 duplicate** concept sets (2 concepts each)
- "Multiple endocrine neoplasia, type 2" — **4 duplicate** concept sets
- "glimepiride" — 2 duplicates

#### 3. HbA1c Missing (P0)
- HbA1c/Hemoglobin A1c criterion exists in eligibility (domain=Measurement)
- But NO concept set for LOINC HbA1c codes in structuredExpression
- Possibly skipped during CIRCE building or roll-up eliminated it

#### 4. Concept Count Too Low
Many concept sets have only 1-2 concepts where Gold standard has 5-20.
Examples:
- "Type 2 diabetes mellitus" → 1 concept (Gold has ~10)
- "sitagliptin" → 1 concept (Gold has 5+ formulations)

## Root Cause Analysis

1. **Roll-up**: `expression_builder.py` uses ancestor hierarchy to group concepts. The roll-up algorithm climbs too high when seed concepts share a distant common ancestor.
2. **Dedup**: No deduplication of concept sets by criterion. Parallel workers (16 threads) can produce multiple results for the same criterion text.
3. **HbA1c**: Needs investigation — could be domain mismatch (Measurement not handled) or mapping failure.

## Issue Tracker (prioritized)

### P0 — Cohort generation broken (directly affects finalCount)

| # | Issue | Root Cause | Fix Location |
|---|-------|------------|--------------|
| P0-1 | ANY InclusionRule has groups=0 (12 empty rules) | CIRCE builder fails to link criteria inside ANY groups | `tte_service.py` — `_build_seeded_eligibility` |
| P0-2 | HbA1c, eGFR Measurement concept sets missing | Measurement domain CIRCE build path missing or lost in roll-up | `tte_service.py` + `expression_builder.py` |
| P0-3 | Roll-up → overbroad ancestors (29/79 sets, 37%) | "Clinical finding", "Disease" etc. climbed to meaningless top-level | `expression_builder.py` |

### P1 — Quality/efficiency (indirect impact on cohort accuracy)

| # | Issue | Root Cause | Fix Location |
|---|-------|------------|--------------|
| P1-1 | Concept sets accumulate on re-call (no idempotency) | process_eligibility appends without clearing existing CS | `tte_service.py` — entry point |
| P1-2 | Low concept count (avg 2.5 vs Gold 6.6) | includeDescendants policy, retriever recall | `expression_builder.py` + `recommender.py` |
| P1-3 | Same criterion processed 2.3x (170 runs / 74 unique) | No criterion-text-level cache | `tte_service.py` or `recommender.py` |

### Already Fixed (this branch)

| Commit | Fix |
|--------|-----|
| `6c3c229` | Use criterion domain for CIRCE criteria type |
| `688f10d` | Split compound 'or' drug class queries for ATC expansion |
| `ebe0a03` | Skip isGroupLabel rows in ordered_pairs reconstruction |
| `7cdc337` | Skip group-label criteria from Agent2 mapping |

## Duplicate Root Cause (clarification)

The 170/74 = 2.3x duplication is NOT a parallel worker bug.
Code (`tte_service.py:2643-2647`) submits each criterion exactly once.

Actual cause: `process-eligibility` was called **twice** on study 420:
```
POST /tte/studies/420/process-eligibility → 200 OK  (1st call)
POST /tte/studies/420/process-eligibility → 200 OK  (2nd call)
```
The 2nd call appended concept sets on top of 1st call results.
Fix: clear existing `structuredExpression.ConceptSets` at start of process_eligibility.

## Performance Summary

| Metric | Value |
|--------|-------|
| Total Agent2 runs | 170 (74 unique × 2.3 calls) |
| Total compute time | 570 min (CPU-time) |
| Wall clock (16 workers) | ~36 min |
| Avg per criterion | 201 sec (~3.4 min) |
| Range | 33s – 449s |
| Speed: <1min | 5 (3%) |
| Speed: 1-3min | 79 (46%) |
| Speed: 3-5min | 55 (32%) |
| Speed: >5min | 31 (18%) |
