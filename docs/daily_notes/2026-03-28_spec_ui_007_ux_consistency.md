# 2026-03-28: SPEC-UI-007 TTE UX Consistency Overhaul

## Summary

Unified 5 UX patterns across all 8 TTE tabs that had diverged during SPEC-UI-001 through 006. Pure frontend refactoring — no backend changes.

Branch: `feat/spec-ui-007-ux-consistency` (merged to `main` as `359f3bc`)

## Problem

Each SPEC-UI iteration improved individual tabs in isolation, creating 5 types of UX inconsistency:
- Button placement: 5 different patterns (banner, panel bottom, inline, side-by-side, none)
- State display: 4 patterns (5-state banner, cohortId if/else, nextRequiredAction, none)
- Read-only mode: 3 patterns (locked+edit toggle, summary→Change, always editable)
- Progress feedback: Treatment-only breadcrumb vs nothing
- Contextual guidance: Treatment-only data source note vs nothing

## Design Decisions

| Pattern | Decision | Rationale |
|---|---|---|
| Button placement | Keep positions, unify `btn-primary btn-lg` style | Banners bind state+action tightly |
| Status display | Extend 5-state banner to Outcomes + Execute Study | Consistent feedback for actionable tabs |
| Read-only toggle | Keep current, unify `.tte-summary-card` appearance | Over-locking frustrates users |
| Progress indicator | All tabs + inline nextRequiredAction CTA | Replace dead `nextRequiredAction` banner |
| Context notes | Info alert in all 8 tabs | Start with guidance, remove if noisy |

## Implementation (Bottom-Up)

| Phase | Tasks | What |
|---|---|---|
| Phase 1 (parallel) | 1-5 | TDD computeds + component + LESS styles |
| Phase 2 (sequential) | 6-11 | HTML changes across all 8 tabs |
| Fixes | 12 | Integration test + review fixes |

### Commits (14 total)

| Commit | Description |
|---|---|
| `8acb941` | LESS styles: progress bar, context note, summary card, status banner |
| `9755f62` | Progress indicator KO component (html + js) |
| `e8003c3` | tabCompletionStates computed (allCriteriaMapped, hasCompletedExecution) |
| `ae11d2f` | outcomesBannerState computed (isSuggestingOutcomes) |
| `f1876ec` | executeStudyBannerState computed (staleness via timestamps) |
| `709fe03` | CSS rename: .tte-cohort-generation-banner → .tte-status-banner |
| `ad41171` | Progress indicator + context notes to all 8 tabs |
| `2a31745` | Button style unification (3 locations) |
| `5190639` | Summary card migration (Treatment + Outcomes → .tte-summary-card) |
| `87692d7` | Dead .tte-next-required-action CSS cleanup |
| `e651735` | Outcomes 3-state status banner |
| `4ea1c34` | Execute Study 5-state status banner |
| `4cca519` | Review fix: role="status" on Treatment banner |
| `359f3bc` | Merge to main |

## New Components

### tte-progress-indicator
- KO component: `components/tte-progress-indicator.{html,js}`
- Params: `steps`, `currentStep`, `completionStates`, `nextAction`, `nextActionCta`, `onStepClick`
- Accessibility: `role="navigation"`, `aria-current="step"`, `aria-live="polite"` CTA row
- Responsive: labels hidden < 768px, overflow-x auto

### Tab Completion Conditions

| Tab | Condition | Status |
|---|---|---|
| Specification | `studyId` exists | Confirmed |
| Eligibility | All criteria have conceptId | Confirmed |
| Treatment | `cohortGenerationState === 'complete'` | Tentative |
| Outcomes | `primaryOutcome.cohortId() != null` | Tentative |
| Analysis | `outcomeModel` + `selectedPsStrategy` set | Tentative |
| Execute Study | Execution with COMPLETED status | Tentative |
| Gen & Analysis | `hasAnalysisResults()` | Tentative |
| Report Summary | `reportHtmlContent()` exists | Tentative |

## New Computeds in tte-manager.js

- `allCriteriaMapped` — every inclusion/exclusion criterion has conceptSetId or conceptId
- `hasCompletedExecution` — any execution with status COMPLETED
- `tabCompletionStates` — object with per-tab boolean
- `isSuggestingOutcomes` — dedicated observable (not shared isCapabilityRunning)
- `outcomesBannerState` — generating > blocked > complete
- `lastExecutionTimestamp` / `lastSettingsChangeTimestamp` — staleness tracking
- `isExecutionStale` — settings changed after last execution
- `executeStudyBannerState` — generating > blocked > stale > complete > ready
- `currentContextNote` — per-tab message from contextNoteMessages map

## CSS Changes

- New: `.tte-progress-bar/*`, `.tte-context-note`, `.tte-summary-card/*`, `.tte-status-banner/*`
- Renamed: `.tte-cohort-generation-banner` → `.tte-status-banner`
- Removed: `.tte-outcome-ready`, `.tte-next-required-action`

## Tests

- 33 new Jest tests (20 progressIndicator + 5 outcomesBanner + 8 executeStudyBanner)
- 182 total tests passing
- Pattern: extracted pure functions tested with plain objects (no KO dependency)

## Key Lessons

- Subagent HTML edits can silently revert earlier commits if they read stale state — always `git checkout -- file` to restore HEAD after subagent work
- `isCapabilityRunning` is shared across 12+ async operations — dedicate per-feature observables for banner states
- `selectedPsStrategy` is a pureComputed wrapper — subscribe to underlying `psMethod` for change detection
- Codex Ensemble needs `timeout` param threaded through `run_codex_worker` function signature
