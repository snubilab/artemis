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

## ANTI-PATTERNS

- Do not move API contract fields without checking Atlas TTE consumers under `../atlas-dev/js/pages/target-trial-emulation/`.
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
