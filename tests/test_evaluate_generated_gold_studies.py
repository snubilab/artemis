"""
Tests for artemis/scripts/evaluate_generated_gold_studies.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ARTEMIS_DIR / "scripts" / "evaluate_generated_gold_studies.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "evaluate_generated_gold_studies",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def test_resolve_studies_returns_canonical_configs():
    studies = MODULE.resolve_studies(["leader", "plato"])

    assert [study.study_key for study in studies] == ["LEADER", "PLATO"]
    assert studies[0].module_name == "artemis_leader_gold_eval"
    assert studies[1].module_filename == "artemis_plato_gold_eval.json"


def test_summarize_attrition_detects_first_zero_and_final_record():
    records = [
        {"level": 0, "person_count": 140, "status": "COMPLETE"},
        {"level": 1, "person_count": 139, "status": "COMPLETE"},
        {"level": 2, "person_count": 0, "status": "COMPLETE"},
    ]

    summary = MODULE.summarize_attrition(records)

    assert summary["levels_processed"] == 3
    assert summary["first_zero_level"] == 2
    assert summary["final_level"] == 2
    assert summary["final_person_count"] == 0
    assert summary["final_record"] == records[-1]


def test_build_clear_generation_cache_sql_targets_cohort_cache_for_source_key():
    sql = MODULE.build_clear_generation_cache_sql("SYNTHEA_CDM_BENCHMARK")

    assert "DELETE FROM webapi.generation_cache" in sql
    assert "gc.type = 'COHORT'" in sql
    assert "source_key = 'SYNTHEA_CDM_BENCHMARK'" in sql


def test_sql_quote_escapes_single_quotes():
    assert MODULE.sql_quote("O'HDSI") == "'O''HDSI'"


def test_classify_outcome_marks_direct_sql_divergence():
    outcome = MODULE.classify_outcome(
        {
            "final_person_count": 0,
            "final_record": {"status": "COMPLETE"},
        },
        {
            "attempted": True,
            "person_count": 139,
            "error": None,
        },
    )

    assert outcome == "webapi_direct_sql_divergence"


def test_render_markdown_handles_missing_direct_sql_for_nonzero_webapi():
    markdown = MODULE.render_markdown(
        {
            "run_id": "run-1",
            "patients_per_study": 300,
            "source_key": "SYNTHEA_CDM_BENCHMARK",
            "studies": [
                {
                    "study_key": "PLATO",
                    "study_dir": "/tmp/plato",
                    "synthea_generation": {"patients_csv_rows": 300},
                    "etl_counts": {"person": 300, "visit_occurrence": 3255},
                    "attrition_summary": {
                        "final_person_count": 12,
                        "first_zero_level": None,
                    },
                    "direct_sql": None,
                    "outcome": "webapi_nonzero",
                }
            ],
        }
    )

    assert "| PLATO | 300 | 300 | 3255 | 12 | None | None | webapi_nonzero |" in markdown
