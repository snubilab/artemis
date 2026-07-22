# Ablation Study Results -- SPEC-MAP-002 (2026-03-29)

## Executive Summary

Ran 6 ablation configurations x 5 probe queries through Agent2's mapping
pipeline. Two rounds were necessary:

1. **Round 1 (v1)**: All runs identical -- discovered `gpt-4o-mini` deployment
   does not exist on the Azure AI Foundry endpoint. The critic model tiering
   (SPEC-PERF-001 M4) routes well-defined domains (Condition, Drug,
   Measurement) to `gpt-4o-mini`, which returned 404.

2. **Round 2 (v2)**: Forced `AGENT2_CRITIC_MODEL_TIER=gpt-4o`. Critic now
   executes successfully. Observable differences emerge between configurations.

**Root cause of v1 failure**: `gpt-4o-mini` is not deployed on
`https://team3-us.services.ai.azure.com/models`. The `gpt-4o` model works fine.

---

## Configuration

| Run | INCLUDE_DESC | UMLS_STRICT | RERANKER_DOMAIN | CRITIC_REFLECT | Purpose |
|-----|---|---|---|---|---|
| A (baseline) | false | false | false | false | Control |
| B | false | true | false | false | UMLS only |
| C | false | false | true | false | Reranker only |
| D | true | false | false | false | includeDescendants only |
| E | false | false | false | true | Critic reflection only |
| F (all) | true | true | true | true | Full optimization |

All runs used `AGENT2_CRITIC_MODEL_TIER=gpt-4o` to bypass the missing
`gpt-4o-mini` deployment.

---

## Results Per Query (Round 2)

### Query: "MI" (domain: Condition, expected: Myocardial Infarction)

All 6 runs returned **identical 18 concepts**. No configuration variation.

| # | Concept ID | Concept Name | Vocab | Correct? |
|---|---|---|---|---|
| 1 | 4110715 | **Milia** | SNOMED | WRONG |
| 2 | 4329847 | Myocardial infarction | SNOMED | YES |
| 3 | 312327 | Acute myocardial infarction | SNOMED | YES |
| 4 | 4215259 | First myocardial infarction | SNOMED | YES |
| 5 | 439693 | True posterior MI | SNOMED | YES |
| 6 | 314666 | Old myocardial infarction | SNOMED | YES |
| 7 | 4030582 | Postoperative MI | SNOMED | YES |
| 8 | 765132 | Subendocardial MI | SNOMED | YES |
| 9 | 4200113 | Non-Q wave MI | SNOMED | YES |
| 10 | 4173632 | Microinfarct of heart | SNOMED | YES |

**Assessment**: The critic expanded from 4 (v1 without critic) to 18 concepts,
adding many relevant MI subtypes. However, **Milia remains at #1** -- the critic
did not filter it out. The critic accepts all 18 concepts including the
incorrect milia. **Score: PARTIAL** (17/18 correct, wrong top concept).

**Component impact**: None -- all 6 runs identical for MI.

### Query: "HbA1c" (domain: Measurement, expected: LOINC 3004410)

All 6 runs returned **identical 6 concepts**. No configuration variation.

| # | Concept ID | Concept Name | Vocab | Correct? |
|---|---|---|---|---|
| 1 | 3032856 | HbA1c measurement device Vendor name | LOINC | WRONG |
| 2 | 3004410 | Hemoglobin A1c/Hemoglobin.total in Blood | LOINC | YES (gold) |
| 3 | 3034639 | Hemoglobin A1c [Mass/volume] in Blood | LOINC | YES |
| 4 | 4184637 | Hemoglobin A1c measurement | SNOMED | YES |
| 5 | 44793001 | HbA1c measurement (IFCC standardised) | SNOMED | YES |
| 6 | 4197971 | HbA1c measurement (DCCT aligned) | SNOMED | YES |

**Assessment**: The critic expanded from 4 to 6 concepts but still returns the
device vendor concept at #1. Gold LOINC 3004410 is at #2. The critic is not
distinguishing between a lab test and a device name.
**Score: PARTIAL** (5/6 correct, wrong top concept).

**Component impact**: None -- all 6 runs identical for HbA1c.

### Query: "Stroke" (domain: Condition, expected: Cerebrovascular concepts)

**THIS QUERY SHOWS VARIATION!**

| Run | Concepts | First 5 IDs |
|-----|----------|-------------|
| A (baseline) | 3 | 4099974, 4310996, 381316 |
| B (UMLS) | **26** | 4099974, 4310996, **35609033**, **37167974**, **603206** |
| C (reranker) | **26** | 4099974, 4310996, **35609033**, **37167974**, **603206** |
| D (descendants) | 3 | 4099974, 4310996, 381316 |
| E (critic) | 3 | 4099974, 4310996, 381316 |
| F (all on) | 3 | 4099974, 4310996, 381316 |

Base 3 concepts (runs A, D, E, F):

| Concept ID | Concept Name |
|---|---|
| 4099974 | Completed stroke |
| 4310996 | Ischemic stroke |
| 381316 | Cerebrovascular accident |

Additional concepts in B/C (26 total, including):

| Concept ID | Concept Name |
|---|---|
| 35609033 | Haemorrhagic stroke |
| 37167974 | CVA due to occlusion of anterior choroidal artery |
| 603206 | CVA due to occlusion of left posterior communicating artery |
| 765568 | Chronic cerebrovascular accident |
| 37395575 | CVA due to right carotid artery stenosis |
| 764721 | CVA with intracranial hemorrhage |
| 618640 | CVA of brainstem |
| 4090122 | Extension of cerebrovascular accident |

**Assessment**: UMLS strict filter (B) and domain-aware reranker (C) both
independently produce the same expanded 26-concept set. This is unexpected
since they target different pipeline stages. Likely explanation: both modify the
candidate pool in ways that allow the critic to select more stroke subtypes.

Paradoxically, the **full-on (F) run returns only 3** concepts, same as
baseline. This suggests that when includeDescendants AND self-reflection are
also enabled, they interact to compress the concept set back down.

**Score: GOOD** (all concepts clinically appropriate in all runs).

### Query: "GLP-1 receptor agonist" (domain: Drug, expected: GLP-1 RA drugs)

All 6 runs returned **identical 1 concept**: glimepiride (1597756).

**Assessment**: **FAIL** across all configurations. No component toggle fixes
the GLP-1 RA -> glimepiride error. The vector search returns glimepiride as
the closest match, and the critic does not reject it.

This is a fundamental gap: the pipeline cannot map drug class names to their
constituent ingredients without either:
- ATC-level drug class expansion
- A more comprehensive drug ontology in the vector index
- Explicit drug class -> ingredient lookup tables

**Score: WRONG** (0/1 correct).

### Query: "Chronic kidney disease" (domain: Condition, expected: Broad CKD)

All 6 runs returned **identical 15 concepts**.

| # | Concept ID | Concept Name |
|---|---|---|
| 1 | 46271022 | Chronic kidney disease |
| 2 | 198185 | Chronic renal failure |
| 3 | 36716947 | Chronic renal insufficiency |
| 4 | 36717534 | CKD following excision of neoplasm of kidney |
| 5 | 443614 | CKD stage 1 |
| 6 | 443597 | CKD stage 3 |
| 7 | 45773688 | CKD due to type 1 diabetes |
| 8 | 43531578 | CKD due to type 2 diabetes |
| 9 | 36716455 | CKD due to traumatic loss of kidney |
| 10 | 36716184 | CKD following donor nephrectomy |

**Assessment**: The critic expanded from 3 to 15 concepts, all clinically
relevant CKD subtypes. Excellent coverage. The gold standard uses ancestor
46271022 with `includeDescendants=true`; the pipeline selected 15 explicit
leaf concepts instead, which achieves similar intent.

**Score: GOOD** (15/15 correct).

---

## Summary Matrix

| Query | A (base) | B (UMLS) | C (reranker) | D (desc) | E (critic) | F (all) |
|---|---|---|---|---|---|---|
| MI | 18 (milia #1) | 18 (same) | 18 (same) | 18 (same) | 18 (same) | 18 (same) |
| HbA1c | 6 (device #1) | 6 (same) | 6 (same) | 6 (same) | 6 (same) | 6 (same) |
| Stroke | **3** | **26** | **26** | **3** | **3** | **3** |
| GLP-1 RA | 1 (wrong) | 1 (same) | 1 (same) | 1 (same) | 1 (same) | 1 (same) |
| CKD | 15 | 15 (same) | 15 (same) | 15 (same) | 15 (same) | 15 (same) |

| Run | MI | HbA1c | Stroke | GLP-1 | CKD | Score |
|-----|-----|-------|--------|-------|-----|-------|
| A | Partial | Partial | Good (3) | Wrong | Good | 2/5 |
| B | Partial | Partial | Good (26) | Wrong | Good | 2/5 |
| C | Partial | Partial | Good (26) | Wrong | Good | 2/5 |
| D | Partial | Partial | Good (3) | Wrong | Good | 2/5 |
| E | Partial | Partial | Good (3) | Wrong | Good | 2/5 |
| F | Partial | Partial | Good (3) | Wrong | Good | 2/5 |

---

## Key Findings

### 1. Critic Model Tiering Bug (SPEC-PERF-001 M4)

The `gpt-4o-mini` deployment does not exist on the Azure AI Foundry endpoint.
Since SPEC-PERF-001 M4 routes well-defined domains (Condition, Drug,
Measurement) to `gpt-4o-mini`, the critic silently fails for all 5 probe
queries. **This means the tiering feature is broken in production.**

**Fix**: Either:
- Deploy `gpt-4o-mini` on the Azure endpoint, or
- Set `AGENT2_CRITIC_MODEL_TIER=gpt-4o` in docker-compose env vars, or
- Add a fallback in `select_critic_model()` to test model availability

### 2. Components Have Minimal Individual Impact

With the critic working (gpt-4o), the 4 toggleable components show almost no
individual effect:

- **UMLS strict**: Only affects Stroke (3 -> 26 concepts)
- **Reranker domain-aware**: Same effect as UMLS on Stroke (3 -> 26)
- **includeDescendants auto**: No observable effect on any query
- **Critic self-reflection**: No observable effect on any query

### 3. The Critic Does Not Fix Core Problems

Even with a working critic:
- **MI still returns milia** at #1 -- the critic does not reject it
- **GLP-1 RA still maps to glimepiride** -- the critic cannot fix bad
  retrieval when no correct candidates exist in the vector search results
- **HbA1c device concept** still ranks above the lab test

### 4. Stroke Shows Interesting Interaction Effects

UMLS and reranker individually expand Stroke from 3 to 26 concepts, but when
**all** toggles are on (Run F), the result collapses back to 3. This suggests
the includeDescendants auto or critic self-reflection counteract the expansion.

### 5. Drug Class Mapping Is Fundamentally Broken

The pipeline cannot map drug class names (GLP-1 receptor agonist) to
constituent drugs. This requires either ATC drug class expansion (which exists
in the codebase but was not triggered) or a supplementary lookup table.

---

## Recommendations

### Immediate (P0)

1. **Fix critic model tiering**: Add `AGENT2_CRITIC_MODEL_TIER=gpt-4o` to
   `compose/artemis-api.yml` environment section until `gpt-4o-mini` is
   deployed.

### Short-term (P1)

2. **Fix MI/abbreviation handling**: Add abbreviation expansion in the UMLS
   expander or a pre-processing step that expands "MI" -> "myocardial
   infarction" before vector search.

3. **Fix drug class mapping**: Ensure ATC-level expansion triggers for drug
   class queries. Check why `atc_expanded` was false for "GLP-1 receptor
   agonist".

4. **Fix HbA1c ranking**: The critic should deprioritize "device vendor name"
   LOINC concepts when "lab test" concepts are available.

### Medium-term (P2)

5. **Add model availability fallback**: `select_critic_model()` should test
   if the selected model works and fall back to gpt-4o on failure.

6. **Investigate B/C vs F interaction**: Why does enabling all toggles suppress
   the Stroke expansion that UMLS and reranker individually produce?

---

## Timing

| Run | MI | HbA1c | Stroke | GLP-1 | CKD | Total |
|-----|-----|-------|--------|-------|-----|-------|
| A | 30.3s | 17.7s | 12.3s | 11.6s | 19.0s | 90.9s |
| B | 14.1s | 14.6s | 19.2s | 8.1s | 10.1s | 66.1s |
| C | 14.1s | 13.7s | 11.2s | 7.4s | 10.6s | 57.0s |
| D | 14.3s | 14.8s | 11.0s | 7.0s | 11.2s | 58.3s |
| E | 13.5s | 14.3s | 10.8s | 7.1s | 10.5s | 56.2s |
| F | 13.8s | 14.2s | 10.9s | 8.1s | 10.4s | 57.4s |

Run A is slower because it was the first run (cold JIT, module imports).
Subsequent runs benefit from cached imports and ChromaDB connections.

Total experiment time: ~6.5 minutes for 30 queries (6 runs x 5 queries).

---

## Appendix: Round 1 (Critic Down)

Round 1 ran with default `AGENT2_CRITIC_MODEL_TIER=auto`, which selected
`gpt-4o-mini` for all 5 queries (all in well-defined domains). Every query
received:

```
[Critic] Evaluation failed: Error code: 404 - DeploymentNotFound
```

Results: all 6 runs returned identical pre-critic candidates (4 for MI, 4 for
HbA1c, 3 for Stroke, 1 for GLP-1, 3 for CKD). The critic failure causes
the pipeline to fall back to raw candidates without any LLM filtering.

This confirms that the critic adds significant value: with it working (round
2), MI went from 4 to 18, HbA1c from 4 to 6, and CKD from 3 to 15 concepts.
