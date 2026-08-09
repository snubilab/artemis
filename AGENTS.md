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

Score **per eligibility criterion, 1:1, macro-averaged**. Never lead with a micro
average over pooled concept ids. On this corpus the two disagree in DIRECTION, not just
magnitude:

| | micro (concept mass) | per criterion 1:1 |
| --- | --- | --- |
| overall recall / precision | 0.141 / 0.503 | 0.542 / 0.484 |
| ARISTOTLE | 0.087 / 0.863 | 0.749 / 0.153 |

ARISTOTLE reads "worst recall, best precision" under micro and the opposite per
criterion. Its micro recall was set by one 111,910-concept antihypertensive set we never
build; its micro precision by one 10,720-concept aspirin set that matches gold exactly.
Neither describes the other forty criteria, and per criterion 48 of 144 matched pairs
reach full recall — erased by the pooled figure.

Report per-set recall and precision, and the recall distribution rather than only a
mean. Report three populations separately: matched pairs, gold sets with no counterpart
(94 of 238 here), and generated sets with no counterpart. A "best Jaccard match" against
a gold set that has no real counterpart must be reported as *no counterpart*, not as a
weak match.

Always surface **zero-overlap pairs** — both sides exist and share no concept. They are
the sharpest defect class and are invisible in any pooled number: our "linagliptin" set
resolves to sitagliptin, "glimepiride" to three Condition concepts, and our 205-concept
glucose set omits gold's one fasting-glucose LOINC.

`scripts/conceptset_overlap_eval.py` emits this as `per_criterion` and prints it above
the micro block; micro is labelled "concept mass — do not quote as quality".

Gold sets referenced **only** from `CensoringCriteria` are out of scope and reported
under `out_of_scope_gold`, not paired: gold censors at initiation of either arm's drug,
and the generated eligibility cohort has no such section. Six of the scored sets are in
this class. Without the exclusion, CAROLINA's "Hypersensitivity to investigational
product or glimepiride" was matched to gold's glimepiride censoring set by name alone.

**Unreferenced gold sets are kept in the denominator — decided 2026-08-10, do not
silently change it.** 14 of 238 scored gold sets are orphans that no criterion
references, nearly all non-ATC duplicates of the `(ATC)` set PrimaryCriteria actually
uses. They stay because the question this eval asks is whether we built gold's concept
sets, and TROY exports them as a library. The cost of that choice must be paid at
reporting time: **one correction can score as several pairs.** Fixing the entry drug
moved five pairs, but three were orphan duplicates of the other two — the honest count
is two, one per affected trial. Report distinct corrections, not pair counts, and say
which pairs are duplicates when quoting a delta.

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
