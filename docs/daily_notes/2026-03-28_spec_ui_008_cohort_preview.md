# 2026-03-28: SPEC-UI-008 Treatment Cohort Preview & Approval

## Summary

Added clinician review gate before treatment cohort definitions are registered in Atlas. Generate now produces a structured preview table; user must Approve before registration.

## Problem

Generate Cohorts clicked → CIRCE immediately registered in Atlas → no clinician review opportunity.

## Solution

3-endpoint backend pattern + 7-state frontend state machine + preview table UI.

### Backend (3 commits)

| Commit | Description |
|---|---|
| `ccf5f02` | Pydantic models: `CircePreviewResponse`, `ConceptSetPreview`, `InclusionRulePreview`, `ArmPreview`, `TimeParametersPreview` |
| `b0a4640` | Service: `preview_seeded_cohorts()`, `register_seeded_cohorts()`, `_parse_circe_for_preview()`, preview cache with SHA-256 hash, 30min eviction |
| `fedec8a` | Endpoints: `POST /preview-seeded-cohorts`, `POST /register-seeded-cohorts` (409 on expired preview) |

### Frontend (4 commits)

| Commit | Description |
|---|---|
| `4c8248c` | API paths + `TTEService.previewSeededCohorts()`, `registerSeededCohorts()` |
| `3df6028` | 7-state machine (+ preview, registering) + 8 Jest tests + eligibility stale guard |
| `eee77c2` | Flow wiring: `triggerSeededCohortGeneration` → preview API, `cancelCircePreview`, `approveCircePreview` |
| `f79843e` | Preview table HTML (shared `tte-arm-preview-template`) + CSS |

## Flow

```
Generate click → preview API (dry run) → preview table shown
  → Cancel → ready (no registration)
  → Approve → register API (uses cached CIRCE + hash) → Atlas registration → complete
```

## Key Design Decisions

- Separate `/preview` and `/register` endpoints (not `dry_run` param) — clean REST
- Server-side preview cache keyed by `(study_id, hash)` — ensures Approve registers exact same CIRCE
- 7-state: blocked → ready → generating → preview → registering → complete / stale
- Read-only preview (editing deferred to future SPEC)
- Preview banner uses light blue border for visual distinction
- Concept IDs: show individual if ≤5, show count if >5

## Tests

- 12 pytest (CIRCE parser, preview hash, domain detection)
- 82 Jest (8 new for 7-state machine + existing)
