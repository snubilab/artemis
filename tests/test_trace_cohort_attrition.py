"""
Regression tests for artemis/scripts/trace_cohort_attrition.py.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ARTEMIS_DIR / "scripts" / "trace_cohort_attrition.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("trace_cohort_attrition", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def test_parse_args_uses_long_running_default_timeout_budget():
    args = MODULE.parse_args([])

    assert args.timeout_seconds == 14400


def test_persist_sql_artifacts_writes_translated_sql_and_meta(tmp_path):
    template_sql = "SELECT @cdm_database_schema;\n"
    translated_sql = "SELECT * FROM synthea_cdm.person;\n"

    meta = MODULE.persist_sql_artifacts(
        tmp_path,
        {
            "templateSql": template_sql,
            "sql": translated_sql,
            "statsSql": "SELECT 1;\n",
        },
    )

    assert (tmp_path / "template.sql").read_text() == template_sql
    assert (tmp_path / "translated.sql").read_text() == translated_sql

    written_meta = json.loads((tmp_path / "translation_meta.json").read_text())
    assert written_meta["target_dialect"] == "postgresql"
    assert written_meta["translation_method"] == "webapi_sql"
    assert written_meta["response_keys"] == ["sql", "statsSql", "templateSql"]
    assert written_meta["template_sql_path"] == str(tmp_path / "template.sql")
    assert written_meta["translated_sql_path"] == str(tmp_path / "translated.sql")
    assert written_meta["translated_sql_present"] is True
    assert written_meta["translated_sql_bytes"] == len(translated_sql.encode("utf-8"))
    assert meta["translation_meta_path"] == str(tmp_path / "translation_meta.json")


def test_persist_sql_artifacts_uses_sqlrender_translate_when_sql_missing(tmp_path, monkeypatch):
    template_sql = "CREATE TABLE #Codesets (codeset_id int);\n"

    monkeypatch.setattr(
        MODULE,
        "translate_sql",
        lambda base_url, template_sql, target_dialect: {
            "targetSQL": (
                "CREATE TEMP TABLE Codesets (codeset_id int);\n"
                "SELECT * FROM @target_database_schema.@target_cohort_table "
                "WHERE cohort_definition_id = @target_cohort_id;\n"
            )
        },
    )

    meta = MODULE.persist_sql_artifacts(
        tmp_path,
        {
            "templateSql": template_sql,
        },
        source={
            "sourceKey": "TEST",
            "daimons": [
                {"daimonType": "Results", "tableQualifier": "synthea_results"},
            ],
        },
        target_cohort_id=42,
        base_url="http://127.0.0.1/WebAPI",
    )

    assert (tmp_path / "template.sql").read_text() == template_sql
    assert (tmp_path / "translated.sql").read_text() == (
        "CREATE TEMP TABLE Codesets (codeset_id int);\n"
        "SELECT * FROM synthea_results.cohort WHERE cohort_definition_id = 42;\n"
    )

    written_meta = json.loads((tmp_path / "translation_meta.json").read_text())
    assert written_meta["translation_method"] == "sqlrender_translate"
    assert written_meta["response_keys"] == ["templateSql"]
    assert written_meta["translated_sql_present"] is True
    assert written_meta["placeholder_values"]["@target_cohort_id"] == "42"
    assert meta["translated_sql_path"] == str(tmp_path / "translated.sql")


def test_persist_sql_artifacts_fails_without_sqlrender_output_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "translate_sql",
        lambda base_url, template_sql, target_dialect: {},
    )

    try:
        MODULE.persist_sql_artifacts(
            tmp_path,
            {
                "templateSql": "SELECT 1;\n",
            },
            source={"sourceKey": "TEST"},
            target_cohort_id=1,
            base_url="http://127.0.0.1/WebAPI",
        )
    except RuntimeError as exc:
        assert "sqlrender/translate" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when sqlrender translation is missing")


def test_persist_sql_artifacts_allows_python_fallback_only_when_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "translate_sql",
        lambda base_url, template_sql, target_dialect: {},
    )

    meta = MODULE.persist_sql_artifacts(
        tmp_path,
        {
            "templateSql": "SELECT * FROM @target_database_schema.@target_cohort_table;\n",
        },
        source={
            "daimons": [
                {"daimonType": "Results", "tableQualifier": "synthea_results"},
            ]
        },
        target_cohort_id=0,
        base_url="http://127.0.0.1/WebAPI",
        allow_python_fallback=True,
    )

    assert (tmp_path / "translated.sql").read_text() == "SELECT * FROM synthea_results.cohort;\n"
    written_meta = json.loads((tmp_path / "translation_meta.json").read_text())
    assert written_meta["translation_method"] == "python_fallback"
    assert meta["translated_sql_present"] is True


def test_render_translated_sql_fallback_rewrites_placeholders_and_sqlserver_syntax():
    template_sql = """
CREATE TABLE #Codesets (codeset_id int);
INSERT INTO #Codesets (codeset_id) VALUES (1);
SELECT DATEADD(day, 1, co.condition_start_date) AS end_date,
       DATEDIFF(d, C.start_date, C.end_date) AS era_days,
       DATEFROMPARTS(2011, 7, 22) AS cutoff_date,
       COUNT_BIG(*) AS total_rows
INTO #qualified_events
FROM @cdm_database_schema.condition_occurrence co;
DELETE FROM @target_database_schema.@target_cohort_table
WHERE cohort_definition_id = @target_cohort_id;
""".strip()

    translated_sql, placeholders = MODULE.render_translated_sql(
        template_sql,
        source={
            "daimons": [
                {"daimonType": "CDM", "tableQualifier": "synthea_cdm_benchmark"},
                {
                    "daimonType": "Results",
                    "tableQualifier": "synthea_cdm_benchmark_results",
                },
                {
                    "daimonType": "Vocabulary",
                    "tableQualifier": "synthea_cdm_benchmark",
                },
            ]
        },
        target_cohort_id=42,
    )

    assert placeholders["@target_cohort_id"] == "42"
    assert "CREATE TEMP TABLE temp_codesets" in translated_sql
    assert "INSERT INTO temp_codesets (codeset_id) VALUES (1);" in translated_sql
    assert "INTO TEMP temp_qualified_events" in translated_sql
    assert "DATEADD(" not in translated_sql
    assert "DATEDIFF(" not in translated_sql
    assert "DATEFROMPARTS(" not in translated_sql
    assert "COUNT_BIG(" not in translated_sql
    assert "make_date(2011, 7, 22)" in translated_sql
    assert "synthea_cdm_benchmark.condition_occurrence" in translated_sql
    assert "synthea_cdm_benchmark_results.cohort" in translated_sql
    assert "cohort_definition_id = 42" in translated_sql


def test_main_dry_run_records_translated_sql_artifacts_from_template_only(tmp_path, monkeypatch):
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(
        json.dumps(
            {
                "PrimaryCriteria": {
                    "CriteriaList": [],
                    "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
                    "PrimaryCriteriaLimit": {"Type": "First"},
                },
                "ConceptSets": [],
                "InclusionRules": [],
            }
        )
    )

    monkeypatch.setattr(
        MODULE,
        "resolve_source",
        lambda base_url, source_key: {
            "sourceId": 1,
            "sourceKey": source_key,
            "sourceName": "Test Source",
            "daimons": [
                {"daimonType": "Results", "tableQualifier": "synthea_results"},
            ],
        },
    )
    monkeypatch.setattr(
        MODULE,
        "generate_sql",
        lambda base_url, expression: {
            "templateSql": (
                "SELECT * FROM @results_database_schema.@target_cohort_table "
                "WHERE cohort_definition_id = @target_cohort_id;\n"
            ),
        },
    )
    monkeypatch.setattr(
        MODULE,
        "translate_sql",
        lambda base_url, template_sql, target_dialect: {
            "targetSQL": "SELECT * FROM synthea_results.cohort WHERE cohort_definition_id = 0;\n"
        },
    )

    output_root = tmp_path / "output"
    run_id = "20260318T000000Z"
    exit_code = MODULE.main(
        [
            "--gold-json",
            str(gold_path),
            "--output-root",
            str(output_root),
            "--run-id",
            run_id,
            "--min-level",
            "0",
            "--max-level",
            "0",
        ]
    )

    assert exit_code == 0

    level_dir = output_root / run_id / "L00_EntryOnly"
    record = json.loads((output_root / run_id / "results.jsonl").read_text().strip())
    translation_meta = json.loads((level_dir / "translation_meta.json").read_text())
    manifest = json.loads((output_root / run_id / "manifest.json").read_text())

    assert (level_dir / "translated.sql").read_text() == (
        "SELECT * FROM synthea_results.cohort WHERE cohort_definition_id = 0;\n"
    )
    assert record["mode"] == "dry-run"
    assert record["translated_sql_path"] == str(level_dir / "translated.sql")
    assert record["translated_sql_bytes"] == len(
        "SELECT * FROM synthea_results.cohort WHERE cohort_definition_id = 0;\n".encode(
            "utf-8"
        )
    )
    assert record["translated_sql_present"] is True
    assert record["translation_meta_path"] == str(level_dir / "translation_meta.json")
    assert record["sql_response_keys"] == ["templateSql"]
    assert record["translation_method"] == "sqlrender_translate"
    assert record["target_cohort_id"] == 0
    assert translation_meta["translated_sql_present"] is True
    assert translation_meta["translation_method"] == "sqlrender_translate"
    assert manifest["target_dialect"] == "postgresql"


def test_main_execute_timeout_persists_timeout_record(tmp_path, monkeypatch):
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(
        json.dumps(
            {
                "PrimaryCriteria": {
                    "CriteriaList": [],
                    "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
                    "PrimaryCriteriaLimit": {"Type": "First"},
                },
                "ConceptSets": [],
                "InclusionRules": [],
            }
        )
    )

    monkeypatch.setattr(
        MODULE,
        "resolve_source",
        lambda base_url, source_key: {
            "sourceId": 5,
            "sourceKey": source_key,
            "sourceName": "Test Source",
            "daimons": [
                {"daimonType": "Results", "tableQualifier": "synthea_results"},
            ],
        },
    )
    monkeypatch.setattr(
        MODULE,
        "generate_levels",
        lambda **kwargs: [
            {
                "level": 0,
                "label": "EntryOnly",
                "rule_count": 0,
                "rule_names": [],
                "concept_set_count": 0,
                "expression": {"ConceptSets": [], "PrimaryCriteria": {}, "InclusionRules": []},
            }
        ],
    )
    monkeypatch.setattr(MODULE, "generate_sql", lambda base_url, expression: {"templateSql": "SELECT 1;\n"})
    monkeypatch.setattr(
        MODULE,
        "persist_sql_artifacts",
        lambda *args, **kwargs: {
            "template_sql_path": str(tmp_path / "template.sql"),
            "template_sql_bytes": 9,
            "translated_sql_path": str(tmp_path / "translated.sql"),
            "translated_sql_bytes": 9,
            "translated_sql_present": True,
            "translation_meta_path": str(tmp_path / "translation_meta.json"),
            "translation_method": "sqlrender_translate",
            "response_keys": ["templateSql"],
        },
    )
    monkeypatch.setattr(
        MODULE,
        "register_cohort_definition",
        lambda **kwargs: {"id": 483},
    )
    monkeypatch.setattr(MODULE, "trigger_generation", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        MODULE,
        "poll_generation",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("Timed out polling cohort_definition_id=483 source_id=5")
        ),
    )

    output_root = tmp_path / "output"
    run_id = "20260323T000000Z"
    exit_code = MODULE.main(
        [
            "--gold-json",
            str(gold_path),
            "--output-root",
            str(output_root),
            "--run-id",
            run_id,
            "--min-level",
            "0",
            "--max-level",
            "0",
            "--execute",
            "--timeout-seconds",
            "3600",
        ]
    )

    assert exit_code == 124
    records = (output_root / run_id / "results.jsonl").read_text().strip().splitlines()
    assert len(records) == 1
    record = json.loads(records[0])
    assert record["mode"] == "execute"
    assert record["cohort_definition_id"] == 483
    assert record["status"] == "TIMED_OUT"
    assert record["last_status"] == "RUNNING"
    assert record["timeout_seconds"] == 3600
    assert "Timed out polling cohort_definition_id=483 source_id=5" in record["fail_message"]
