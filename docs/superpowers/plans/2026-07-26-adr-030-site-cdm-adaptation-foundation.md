# ADR-030 Per-Site CDM Adaptation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` task-by-task.

**Goal:** Implement an official-ACHILLES-compatible site snapshot bundle and a safe, proposal-only CDM adaptation engine.

**Architecture:** A site sends `achilles_prevalence.csv` plus run metadata in one ZIP bundle. ARTEMIS evaluates CIRCE against the snapshot and local OMOP vocabulary, then emits feasibility, granularity, comparator-grounding, and Tier-2 verification proposals without mutating CIRCE.

**Tech Stack:** Python 3.12, Pydantic 2, pytest, psycopg2, OMOP vocabulary, ACHILLES 1.7.2.

## Global Constraints

- Never connect to site patient records or the site CDM.
- `stratum_1=concept_id` and `count_value=distinct persons` apply only to analyses `200/400/600/700/800/1800`.
- Parse `stratum_1` as a validated decimal concept ID.
- Missing rows are `suppressed_or_absent` whenever `smallCellCount > 0`.
- Descendant sums are upper bounds, never exact patient counts.
- Tier-1 evidence never mutates CIRCE automatically.
- Do not commit `.env`, patient data, caches, or generated reports.

---

### Task 1: Isolated worktree

- Create branch `feat/adr-030-site-cdm-adaptation` from `d26a73e`.
- Use `/home/bilab/work/projects/Broadsea/.worktrees/artemis-adr-030-site-cdm-adaptation`.
- Copy ADR-030 and the ACHILLES request document only.
- Preserve the original checkout's `.env` and direct-CDM `_concept_prevalence` diff.
- Run the full baseline test suite.

### Task 2: Correct the ADR and request contract

- Define `achilles_site_snapshot.zip` containing `achilles_prevalence.csv` and `manifest.json`.
- Use `<resultsDatabaseSchema>.achilles_results`, not a fixed `<cdm>_results` name.
- Scope `stratum_1` and `count_value` semantics to the six requested analyses.
- Document `smallCellCount`, suppression, PostgreSQL-only examples, and site governance.
- Support CSV export only in v1; remove the database-dump option.

### Task 3: Snapshot loader and evidence

- Add `src/services/site_cdm_adaptation.py`.
- Validate ZIP members, manifest fields, exact CSV columns, concept IDs, counts, analysis completeness, and duplicates.
- Compute a deterministic signature from canonical manifest JSON and CSV bytes.
- Add vocabulary descendant lookup against a local OMOP vocabulary schema only.
- Classify populated, suppressed-or-absent, exact-zero, and unknown-vocabulary states.

### Task 4: CIRCE proposal compiler

- Recursively traverse primary criteria, inclusion rules, and nested `ANY/ALL` groups.
- Interpret CIRCE occurrence type `2` as presence and `0` as absence.
- Emit polarity-aware entry, inclusion, and exclusion proposals.
- Require Tier-2 verification for suppression, value, time-window, and joint conditions.
- Propose populated-descendant granularity changes and ground comparator candidates.
- Prove the input CIRCE remains unchanged.

### Task 5: A/B/C fixtures and CLI

- Export the 1,212 selected Synthea ACHILLES rows.
- Build deterministic hospital A/B/C snapshot bundles with no explicit zero rows.
- Add `scripts/build_site_adaptation_fixtures.py` and `scripts/adapt_site_cdm.py`.
- Verify the three expected adaptation profiles through the CLI.

### Task 6: Verification and project records

```bash
python -m pytest tests/test_site_cdm_adaptation.py -v
python -m pytest tests/ -q
python -m ruff check src/services/site_cdm_adaptation.py scripts/adapt_site_cdm.py tests/test_site_cdm_adaptation.py
python -m src.boot_check
git diff --check
git status --short
```

- Update ADR implementation boundaries.
- Synchronize `docs/tte_agent/06_backend_atomic_todo_plan.md` and `07_current_status.md`.
- Commit each independently testable slice.

## Deferred

- Formal intent schema and semantic domain rerouting.
- Tier-2 site SQL execution.
- API persistence and Atlas HITL UI.
