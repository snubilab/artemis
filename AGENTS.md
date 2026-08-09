# ARTEMIS BACKEND AGENT GUIDE

## OVERVIEW

- ARTEMIS is the Python/FastAPI TTE backend for Broadsea.
- Edit this tree for backend API, agent, pipeline, analysis, and report behavior.
- Root `../AGENTS.md` owns workspace-wide Compose, TTE reporting, and generated-gold cache policy.
- Keep this file backend-local; do not repeat root workspace prose.

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| FastAPI app | `src/api/main.py` | `create_app()` wires `/health`, TTE routes, optional conceptset routes, Spark startup check |
| TTE API contract | `src/api/tte.py`, `src/api/models/tte.py` | Request/response models used by Atlas TTE UI |
| TTE orchestration | `src/services/tte_service.py` | Main service boundary for studies, generation, mapping, execution, analysis, reports |
| TTE persistence | `src/services/tte_store.py` | Local store/concurrency behavior |
| Agent stages | `src/agents/agent1` through `src/agents/agent6` | Extraction, mapping, assembly, validation, analysis/report stage workers |
| Concept sets | `src/agents/conceptset/` | NLU, search, ranking, expression building |
| Pipeline runtime | `src/pipeline/` | Supervisor, WebAPI client, cohort execution, Spark execution |
| Analysis | `src/analysis/` | OMOP access, propensity, KM, Cox, balance, covariates |
| Reporting | `src/reporting/`, `src/services/report_*` | PDF/HTML/report plot generation |
| Scripts | `scripts/` | Benchmarks, loaders, generated-gold eval, diagnostics, one-off repair tools |
| Gold cohort definitions | `data/gold/<TRIAL>/` | TROY v1.1 CIRCE JSON; the reference for concept-set quality |
| Gold vs generated compare | `scripts/compare_gold_vs_generated_circe.py` | Definition-level only, no DB. `PAIRS` currently omits ARISTOTLE/LEADER/PLATO |
| Achilles value distributions | `scripts/achilles_measurement_dist.R` | Populates analysis 1815 for one CDM; runs in `broadsea-hades` |
| Tests | `tests/` | Unit tests plus Docker-backed integration tests |
| Docs | `docs/` | ADRs, daily notes, debugging logs, benchmark history |

## CONVENTIONS

- Use `src/services/tte_service.py` as the orchestration boundary before adding new API route logic.
- Keep Pydantic API shapes in `src/api/models/tte.py`; avoid ad hoc response dicts in routes.
- Put WebAPI/cohort runtime concerns in `src/pipeline/`, not in `src/agents/`.
- Put statistical execution in `src/analysis/`; put presentation assembly in `src/reporting/` or existing `report_*` services.
- Use existing script patterns under `scripts/` for benchmark and data-maintenance entrypoints.
- Treat `.venv/`, `chroma_db/`, `data/cache/`, `tmp/`, and `.pytest_cache/` as runtime or generated state.
- `pyproject.toml` sets `pytest` `asyncio_mode = "auto"`.
- Tests marked `integration` require Docker infrastructure: WebAPI, PostgreSQL, and Neo4j.

## EVALUATION

Judge concept-set and criteria quality by **closure overlap against `data/gold/`**,
not by patient counts against `synthea_cdm_{aristotle,leader,plato}`.

Those CDMs are generated *from gold* by `scripts/generate_synthea_from_gold.py`,
which inverts each gold value constraint and injects one constant per lab. So a
patient count partly measures that generator's conventions. Worked example: gold
writes the platelet threshold as `100` (thousands/uL) and the protocol PDF writes
`100,000/mm3`; both are correct, nothing records a unit, and the 1000x gap alone
takes the ARISTOTLE cohort to 0. Details and the other traps (empty
`procedure_occurrence`, clinically-sound concept sets that match 0 rows) in
`docs/debugging/2026-08-09_benchmark_cdm_is_not_an_oracle.md`.

Resolve a concept set the way Circe does, or the overlap is not comparable: direct
items as listed, descendants joined through `concept_ancestor` filtered by
`invalid_reason IS NULL`, `isExcluded` items subtracted as an anti-join. Confirm
against the rendered SQL by POSTing the expression to
`WebAPI /cohortdefinition/sql` rather than assuming.

Report per-set recall and precision. A "best Jaccard match" against a gold set that
has no real counterpart must be reported as *no counterpart*, not as a weak match.

## ANTI-PATTERNS

- Do not move API contract fields without checking Atlas TTE consumers under `../atlas-dev/js/pages/target-trial-emulation/`.
- Do not report a patient count from a trial benchmark CDM as evidence of pipeline quality; see EVALUATION above.
- Do not infer a measurement's unit from its value distribution. An exclusion threshold sits in the abnormal tail by design, so "outside the observed range" is what a *correct* threshold looks like; the molar cases that must be refused score better than the decimal cases that must be accepted. Achilles 1815 is a sound detector and an unsound repairer.
- Do not retype a wire-format constant (for example the `[OR-GROUP]` prefix, join, and separator). Import it from its owning module; `tests/test_dry_or_group_contract.py` fails if a second copy appears, and a guessed format silently makes every probe against it return `False`.
- Do not treat a passing unit test on a predicate as proof its caller honours the predicate. `restates_or_group_alternative` correctly refuses to call an OR group a duplicate, and `enricher._merge_criteria` then drops it anyway via the legacy `SequenceMatcher`.
- Do not bypass `TTEService` with parallel orchestration in routes.
- Do not commit generated cache, Chroma, tmp, virtualenv, or pytest cache contents.
- Do not duplicate generated-gold cache SQL here; use `scripts/evaluate_generated_gold_studies.py` and the parent cache rule.
- Do not mark Docker-backed tests as plain unit tests; use the existing `integration` marker.

## COMMANDS

```bash
# Local venv shell
source .venv/bin/activate

# Backend boot check
python -m src.boot_check

# Full backend suite
pytest tests/ -v

# Targeted test file
pytest tests/test_boot_check.py -v

# Targeted test name
pytest tests/test_boot_check.py::test_boot_check_reports_missing_package -v

# Integration tests only
pytest tests/integration/ -m integration -v

# Generated-gold rerun entrypoint
python scripts/evaluate_generated_gold_studies.py
```
