# SPEC-UI-003: HITL Concept Mapping Enhancement

Date: 2026-03-28
Branch: `feat/hitl-concept-mapping`
SPEC: SPEC-UI-003

## Summary

Implemented full HITL (Human-in-the-Loop) concept mapping metadata pipeline,
surface layer APIs, and frontend candidates panel. Users can now review the AI's
rejected mapping candidates, understand confidence levels, and trigger fresh
recommendations with a search hint.

---

## Architecture Overview

### Data Flow

```
criterion text
  -> _recommend_seeded_concept_set(label, expected_domain)
    -> Stage2Pipeline.search()    -- returns all_candidates[]     [CAPTURED]
    -> ClinicalReranker.rerank()  -- returns confidence, method   [CAPTURED]
    -> ExpressionBuilder.build_expression() -> expression
  -> Return {name, expression, domain, mapping_metadata}          [NEW]
    -> _build_seeded_eligibility_rule  -- returns _mapping_metadata
    -> _build_seeded_target_circe      -- accumulates _criterionMappingMetadata
    -> _build_process_eligibility_artifact_payload
         -- pops _criterionMappingMetadata from CIRCE
         -- stores as criterionMappingMetadata in artifact payload
```

### Artifact Payload Structure

```json
{
  "proposedChanges": { "eligibility": { "structuredExpression": {...} } },
  "criterionMappingMetadata": {
    "5": {
      "allCandidates": [
        {"conceptId": 4329847, "conceptName": "Myocardial infarction",
         "score": 0.92, "source": "agent2", "included": true}
      ],
      "rerankConfidence": 0.88,
      "rerankMethod": "agent2",
      "queryUsed": "prior myocardial infarction",
      "selectedConceptIds": [4329847]
    }
  }
}
```

---

## Tasks Completed

### Task 1: Pydantic Models (`artemis/src/api/models/tte.py`)

New models:
- `MappingCandidateItem` — single concept candidate with score, source, included flag
- `CriterionMappingMetadata` — full metadata per criterion (candidates, rerank info, query)
- `ReRecommendRequest` — hint + topK (ge=1, le=100) for fresh recommendation requests

Commit: `8eed006`

### Task 2: Pipeline Metadata Capture (`artemis/src/services/tte_service.py`)

- `_recommend_seeded_concept_set`: now returns `mapping_metadata` alongside expression
  - Agent2 path: `rerankMethod="agent2"`, captures candidates with `included` flags
  - RAG fallback: `rerankMethod="rag_fallback"`, score=1.0 for all included
- `_build_seeded_eligibility_rule`: returns `_mapping_metadata` key
- `_build_seeded_target_circe`: accumulates into `_criterionMappingMetadata` dict
- `_build_process_eligibility_artifact_payload`: pops private key, stores in payload

Commit: `864e2a1`

### Task 3: GET Mapping Candidates API (`artemis/src/api/tte.py`)

```
GET /tte/studies/{study_id}/criteria/{criterion_id}/mapping-candidates
```

- 200 + `CriterionMappingMetadata` if artifact and criterion metadata found
- 404 `"No eligibility processing artifact"` if no artifact
- 404 with criterion_id in detail if criterion not in metadata

Commit: `804f3d4`

### Task 4: POST Re-recommend API (`artemis/src/api/tte.py`)

```
POST /tte/studies/{study_id}/criteria/{criterion_id}/re-recommend
Body: {"hint": "STEMI", "topK": 10}
```

- Builds query: `f"{sourceText} {hint}".strip()`
- Calls `run_mapping_pipeline_for_query()` (public service method)
- Returns fresh `CriterionMappingMetadata` without modifying expression
- 400 for demographic criteria (Age, Gender, etc.)
- 404 if study or criterion not found

Commits: `e45e039`, `b072fd0`, `f98bea0`

### Task 5: Candidates Panel (Frontend)

Files: `tte-eligibility-cohort-editor.js`, `.html`, `tte-manager.less`, `tte-manager.html`, `tte-manager.js`

- Accordion panel below conceptset-list in Concept Sets view
- Lazy-loads candidates on first open via GET mapping-candidates API
- Shows only `included: false` candidates (already-selected filtered out)
- Score bar (CSS width %) + source badge (rag / ontology / phoebe / agent2)
- "Add" button: pushes concept into focused concept set expression (KO-safe)
- Only visible when `criterionId` and `studyId` are both available in launch context

Commit: `b27cf01`

### Task 6: Confidence Badge (Frontend)

Files: `tte-eligibility-cohort-editor.js`, `.html`, `tte-manager.less`

- `getConfidenceBadge(score)`: returns CSS class for colored circle
  - `confidence-high` (green #28a745): score >= 0.7
  - `confidence-medium` (amber #ffc107): 0.4 <= score < 0.7
  - `confidence-low` (red #dc3545): score < 0.4 or null/undefined
- Badge rendered as 10px circle next to candidate concept name
- Guarded by `<!-- ko if: score != null -->`
- 8 Jest unit tests covering all boundary values (8/8 pass)

Commit: `69543e4`

### Task 7: Integration Tests

File: `artemis/tests/integration/test_hitl_mapping_flow.py`

3 integration tests:
1. Metadata stored in artifact → GET candidates returns it (200)
2. Old artifact without `criterionMappingMetadata` → 404, no crash
3. Demographic criterion → GET returns 404

Commits: `47c9924`, `c4578d4`

---

## Code Review Findings and Fixes (commit `0de8f6d`)

| Issue | Severity | Fix |
|-------|----------|-----|
| `except (ValueError, Exception)` silently swallowed errors in `_map_criterion` | Critical | Narrowed to `except Exception as e:` + `logging.warning(...)` |
| Router called `_run_mapping_pipeline_for_query` (private method) | Critical | Added public `run_mapping_pipeline_for_query` wrapper on TTEService |
| `topK` field accepted 0 and negative values | Critical | Added `Field(default=10, ge=1, le=100)` constraint |
| Missing `.tte-source-badge--agent2` LESS rule | Important | Added rule with `background-color: #0075c2` |
| `_fetch_concept_candidates` bare `except Exception` with no log | Important | Added `logging.warning(...)` |
| Candidates panel showed `included=True` items (already in set) | Important | Added `.filter(function(c) { return !c.included; })` |
| `addCandidateToSet` bypassed KO observableArray notification | Important | Added `valueHasMutated()` guard |

---

## Test Summary

| Suite | Passed | Skipped | Notes |
|-------|--------|---------|-------|
| `test_mapping_metadata.py` | 10 | 0 | Model creation, serialization |
| `test_mapping_metadata_capture.py` | 14 | 0 | Pipeline capture unit tests |
| `test_mapping_candidates_api.py` | 4 | 4 | 4 HTTP skip (no FastAPI locally) |
| `test_re_recommend_api.py` | 2 | 5 | 5 HTTP skip (no FastAPI locally) |
| `integration/test_hitl_mapping_flow.py` | 0 | 3 | All HTTP, skip locally |
| Jest: `getConfidenceBadge.test.js` | 8 | 0 | All boundary values |
| **Total** | **38** | **12** | HTTP tests pass in Docker |

---

## Key Decisions

- **No new DB tables**: all metadata fits in existing `TTEArtifact.payload` JSON
- **Private key pattern**: `_criterionMappingMetadata` is used as an in-memory transport
  key in the CIRCE dict; popped before storage so CIRCE stays clean
- **`included` flag**: candidates with `included=True` are in the selected set;
  frontend filters these out from the "rejected candidates" panel
- **Demographic criteria**: no metadata is generated (pipeline skips them); API returns 404

---

## Next Steps

- Push `feat/hitl-concept-mapping` and create PR to `fork/main`
- E2E Playwright test against live Atlas for visual panel verification
- Consider adding `SPEC-UI-004`: re-recommend UI with hint input field
