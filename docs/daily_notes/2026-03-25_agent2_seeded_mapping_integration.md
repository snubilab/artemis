# 2026-03-25: Agent2 Seeded Mapping Integration

## What Changed

Replaced RAG-only `_recommend_seeded_concept_set` with full Agent 2 pipeline
(`Agent2Workflow.process_with_details`) for seeded cohort generation.

### Commits

- `9cf96cf` — pass criterion domain as expected_domain to concept set recommender
- `38d0d22` — add `_fetch_concept_candidates` helper (concept_ids -> DB -> ConceptCandidate)
- `dbfb9b6` — integrate Agent2Workflow into seeded concept set mapping with RAG fallback

### Architecture

```
Before: seed_text -> ConceptSetRecommender.recommend() [ChromaDB RAG top-k=5]
After:  seed_text -> Agent2Workflow.process_with_details(domain_hint)
          -> ATC expansion / abbreviation / complexity routing / UMLS / LLM reranker / KG critic
          -> concept_ids -> _fetch_concept_candidates (DB) -> ExpressionBuilder -> ATLAS expression
        Fallback: ConceptSetRecommender (RAG-only) if Agent 2 fails
```

## LEADER Trial (NCT01179048) Verification — Study 385

### Improved Mappings

| Criterion | Before (RAG only) | After (Agent 2) |
|-----------|-------------------|-----------------|
| liraglutide (target) | liraglutide Injectable Solution (4 items) | liraglutide (1, clean) |
| Anti-diabetic drug use | ultralente insulin (2 items) | insulin glargine (31 items, ATC expanded) |
| Long-acting insulin analogue | ultralente insulin (1) | insulin glargine (31 items, ATC expanded) |
| Premixed insulin | ultralente insulin (1) | insulin glargine (31 items, more coverage) |
| exenatide | exenatide (3 mixed) | exenatide (1, clean) |
| liraglutide (exclusion) | liraglutide 6 MG/ML Victoza (5) | liraglutide (1, clean) |
| pramlintide | pramlintide (3 mixed) | pramlintide (1, clean) |

### Remaining Issues (separate task)

| Criterion | Current Mapping | Expected | Root Cause |
|-----------|----------------|----------|------------|
| DPP-4 inhibitors | dipropizine (Drug) | DPP-4 inhibitor class (Drug) | ATC name mismatch — "DPP-4 inhibitors" doesn't match any ATC entry text |
| GLP-1 receptor agonist | Substance (Observation) | GLP-1 RA class (Drug) | Same — ATC query text gap |
| Oral anti-diabetic drugs | Procedure (1) | Oral antidiabetics (Drug) | Mapped to wrong domain, ATC didn't fire |
| Human NPH insulin | Insulin NPH [Mass] (Measurement) | NPH insulin (Drug) | "NPH" matches Measurement concept more closely |

### Root Cause for Remaining Issues

Agent 2's ATC expansion (`expand_drug_class_via_vocab`) queries OMOP vocabulary
by exact/fuzzy text match against ATC concept names. When the criterion text
(e.g., "DPP-4 inhibitors") doesn't match any ATC concept name closely enough,
ATC expansion doesn't fire and falls through to the RAG path, which has the same
semantic distance problem as before.

### Potential Next Steps

1. Improve ATC text matching (synonym-aware or fuzzy matching)
2. Add clinical abbreviation → ATC mapping table (DPP-4 → A10BH, GLP-1 RA → A10BJ)
3. Use OMOP concept_synonym table for broader ATC matching
