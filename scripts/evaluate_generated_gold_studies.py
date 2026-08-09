#!/usr/bin/env python3
"""Run end-to-end 10k generated-data evaluations for canonical Gold studies.

For each study this script:
1. Builds a Synthea module from the Gold JSON
2. Generates N synthetic patients with Synthea
3. Loads CSVs into the benchmark native schema
4. Runs OMOP ETL into synthea_cdm_benchmark
5. Executes WebAPI attrition tracing
6. If the final WebAPI count is zero, executes translated SQL directly for comparison

Every run writes step logs plus JSON/Markdown summaries under output/generated_gold_eval/.

NOT A QUALITY MEASURE (note added 2026-08-09). What this IS for: the generated-gold
data pipeline itself -- Synthea module build, patient generation, native load, OMOP ETL,
and (the reason CLAUDE.md/AGENTS.md name it the preferred entrypoint) clearing the
WebAPI COHORT generation cache before attrition, so a stale "Using cached generation
results" cannot be mistaken for a real count. That job is infrastructure and stays.

What its output is NOT evidence of: pipeline quality. The counts it prints are patient
counts against synthea_cdm_benchmark, which this very script generates FROM data/gold/
via scripts/generate_synthea_from_gold.py -- so a count partly measures that generator's
conventions. Worked failure: gold writes the ARISTOTLE platelet threshold as 100
(thousands/uL) and the protocol PDF writes 100,000/mm3; both are correct, nothing
records a unit, and that 1000x gap alone took the cohort to 0 patients. Read the
attrition output as a diagnostic of WHERE a cohort collapses, never as a quality score.

Measure of record: per-eligibility-criterion 1:1 concept-set overlap against data/gold/,
macro-averaged -- scripts/conceptset_overlap_eval.py --mode closure (see AGENTS.md
EVALUATION and docs/debugging/2026-08-09_benchmark_cdm_is_not_an_oracle.md).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


REPO_DIR = Path(__file__).resolve().parents[2]
ARTEMIS_DIR = REPO_DIR / "artemis"
SYNTHEA_DIR = REPO_DIR / "data" / "synthea" / "synthea"
MODULES_DIR = SYNTHEA_DIR / "src" / "main" / "resources" / "modules"

GENERATOR_SCRIPT = ARTEMIS_DIR / "scripts" / "generate_synthea_from_gold.py"
TRACE_SCRIPT = ARTEMIS_DIR / "scripts" / "trace_cohort_attrition.py"
LOAD_SQL = ARTEMIS_DIR / "scripts" / "load_synthea_benchmark.sql"
RUN_ETL_SCRIPT = ARTEMIS_DIR / "scripts" / "run_etl_full.sh"

DEFAULT_OUTPUT_ROOT = ARTEMIS_DIR / "output" / "generated_gold_eval"
DEFAULT_PATIENTS = 10_000
DEFAULT_SOURCE_KEY = "SYNTHEA_CDM_BENCHMARK"
DEFAULT_WEBAPI_URL = "http://127.0.0.1/WebAPI"
DEFAULT_DB_NAME = "ohdsi"
DEFAULT_ATTRITION_TIMEOUT_SECONDS = 3600


@dataclass(frozen=True)
class StudyConfig:
    study_key: str
    gold_json: Path
    module_name: str
    module_filename: str

    @property
    def module_path(self) -> Path:
        return MODULES_DIR / self.module_filename


STUDY_CONFIGS: Dict[str, StudyConfig] = {
    "LEADER": StudyConfig(
        study_key="LEADER",
        gold_json=ARTEMIS_DIR / "data" / "gold" / "LEADER" / "LEADER_GOLD.json",
        module_name="artemis_leader_gold_eval",
        module_filename="artemis_leader_gold_eval.json",
    ),
    "PLATO": StudyConfig(
        study_key="PLATO",
        gold_json=ARTEMIS_DIR / "data" / "gold" / "PLATO" / "PLATO_GOLD.json",
        module_name="artemis_plato_gold_eval",
        module_filename="artemis_plato_gold_eval.json",
    ),
    "ARISTOTLE": StudyConfig(
        study_key="ARISTOTLE",
        gold_json=ARTEMIS_DIR / "data" / "gold" / "ARISTOTLE" / "ARISTOTLE_GOLD.json",
        module_name="artemis_aristotle_gold_eval",
        module_filename="artemis_aristotle_gold_eval.json",
    ),
    "EMPA-REG": StudyConfig(
        study_key="EMPA-REG",
        gold_json=ARTEMIS_DIR / "data" / "gold" / "EMPA-REG" / "EMPA_REG_GOLD.json",
        module_name="artemis_empa_reg_gold_eval",
        module_filename="artemis_empa_reg_gold_eval.json",
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)


def study_to_json(study: StudyConfig) -> Dict[str, Any]:
    return {
        "study_key": study.study_key,
        "gold_json": str(study.gold_json),
        "module_name": study.module_name,
        "module_filename": study.module_filename,
    }


def resolve_studies(studies: Iterable[str]) -> List[StudyConfig]:
    resolved: List[StudyConfig] = []
    for study in studies:
        key = study.strip().upper()
        if key not in STUDY_CONFIGS:
            raise ValueError(f"Unknown study: {study}")
        resolved.append(STUDY_CONFIGS[key])
    return resolved


def run_command(
    cmd: List[str],
    *,
    cwd: Optional[Path] = None,
    log_path: Optional[Path] = None,
    stdin_path: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    log_handle = None
    stdin_handle = None
    try:
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("w", encoding="utf-8")
            log_handle.write("$ " + " ".join(cmd) + "\n\n")
            log_handle.flush()
        if stdin_path:
            stdin_handle = stdin_path.open("r", encoding="utf-8")
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdin=stdin_handle,
            stdout=log_handle or subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}")
        return result
    finally:
        if stdin_handle:
            stdin_handle.close()
        if log_handle:
            log_handle.close()


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def count_csv_rows(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8") as handle:
        # minus header
        return max(sum(1 for _ in handle) - 1, 0)


def study_slug(study_key: str) -> str:
    return study_key.lower().replace("-", "_")


def build_module(study: StudyConfig, study_dir: Path) -> Dict[str, Any]:
    log_path = study_dir / "logs" / "01_generate_module.log"
    run_command(
        [
            sys.executable,
            str(GENERATOR_SCRIPT),
            "--gold",
            str(study.gold_json),
            "--out",
            str(study.module_path),
            "--name",
            study.module_name,
        ],
        cwd=REPO_DIR,
        log_path=log_path,
    )
    module_json = read_json(study.module_path)
    local_module_dir = study_dir / "local_modules"
    local_module_dir.mkdir(parents=True, exist_ok=True)
    staged_module_path = local_module_dir / study.module_filename
    shutil.copyfile(study.module_path, staged_module_path)
    return {
        "module_path": str(study.module_path),
        "staged_module_path": str(staged_module_path),
        "local_module_dir": str(local_module_dir),
        "remarks": module_json.get("remarks", []),
    }


def generate_synthea_data(
    study: StudyConfig,
    study_dir: Path,
    patients: int,
) -> Dict[str, Any]:
    staged_module_dir = study_dir / "local_modules"
    out_dir = study_dir / "synthea_output"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    log_path = study_dir / "logs" / "02_generate_synthea.log"
    run_command(
        [
            "java",
            "-Xmx4g",
            "-jar",
            "build/libs/synthea-with-dependencies.jar",
            "-d",
            str(staged_module_dir),
            "-m",
            Path(study.module_filename).stem,
            "-p",
            str(patients),
            "--exporter.csv.export=true",
            "--exporter.fhir.export=false",
            "--exporter.hospital.fhir.export=false",
            "--exporter.practitioner.fhir.export=false",
            f"--exporter.baseDirectory={out_dir}",
        ],
        cwd=SYNTHEA_DIR,
        log_path=log_path,
    )
    csv_dir = out_dir / "csv"
    return {
        "output_dir": str(out_dir),
        "csv_dir": str(csv_dir),
        "patients_csv_rows": count_csv_rows(csv_dir / "patients.csv"),
        "encounters_csv_rows": count_csv_rows(csv_dir / "encounters.csv"),
        "conditions_csv_rows": count_csv_rows(csv_dir / "conditions.csv"),
        "medications_csv_rows": count_csv_rows(csv_dir / "medications.csv"),
        "observations_csv_rows": count_csv_rows(csv_dir / "observations.csv"),
    }


def tune_etl_database(study_dir: Path) -> None:
    log_path = study_dir / "logs" / "03_tune_etl_db.log"
    sql_path = study_dir / "03_tune_etl_db.sql"
    write_text(
        sql_path,
        "\n".join(
            [
                "ALTER DATABASE ohdsi SET max_parallel_workers_per_gather = 0;",
                "ALTER DATABASE ohdsi SET work_mem = '64MB';",
                "ALTER DATABASE ohdsi SET enable_parallel_hash = off;",
                "ALTER DATABASE ohdsi SET enable_hashagg = off;",
                "",
            ]
        ),
    )
    run_command(
        [
            "docker",
            "exec",
            "-i",
            "broadsea-atlasdb",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "postgres",
        ],
        cwd=REPO_DIR,
        log_path=log_path,
        stdin_path=sql_path,
    )


def load_native_csvs(study_dir: Path) -> None:
    csv_dir = study_dir / "synthea_output" / "csv"
    logs_dir = study_dir / "logs"
    run_command(
        ["docker", "exec", "broadsea-atlasdb", "rm", "-rf", "/tmp/synthea_csv"],
        cwd=REPO_DIR,
        log_path=logs_dir / "04a_prepare_container_dir.log",
    )
    run_command(
        ["docker", "cp", str(csv_dir), "broadsea-atlasdb:/tmp/synthea_csv"],
        cwd=REPO_DIR,
        log_path=logs_dir / "04b_copy_csvs.log",
    )
    run_command(
        [
            "docker",
            "exec",
            "-i",
            "broadsea-atlasdb",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            DEFAULT_DB_NAME,
        ],
        cwd=REPO_DIR,
        log_path=logs_dir / "04c_load_native.log",
        stdin_path=LOAD_SQL,
    )


def run_etl(study_dir: Path) -> None:
    run_command(
        ["bash", str(RUN_ETL_SCRIPT)],
        cwd=ARTEMIS_DIR,
        log_path=study_dir / "logs" / "05_run_etl.log",
        env={
            **os.environ,
            "ARTEMIS_DB_NAME": DEFAULT_DB_NAME,
        },
    )


def query_tsv(
    sql: str,
    *,
    db_name: str = DEFAULT_DB_NAME,
    log_path: Optional[Path] = None,
) -> List[List[str]]:
    result = subprocess.run(
        [
            "docker",
            "exec",
            "broadsea-atlasdb",
            "psql",
            "-U",
            "postgres",
            "-d",
            db_name,
            "-At",
            "-F",
            "\t",
            "-c",
            sql,
        ],
        cwd=str(REPO_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = (
            "$ docker exec broadsea-atlasdb psql -U postgres "
            f"-d {db_name} -At -F '\\t' -c {sql_quote(sql)}\n\n"
        )
        output = result.stdout or ""
        error = result.stderr or ""
        write_text(log_path, command + output + error)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "psql query failed")
    rows: List[List[str]] = []
    for line in result.stdout.splitlines():
        if line.strip():
            rows.append(line.split("\t"))
    return rows


def query_table_counts() -> Dict[str, int]:
    sql = """
SELECT 'person', count(*) FROM synthea_cdm_benchmark.person
UNION ALL
SELECT 'visit_occurrence', count(*) FROM synthea_cdm_benchmark.visit_occurrence
UNION ALL
SELECT 'condition_occurrence', count(*) FROM synthea_cdm_benchmark.condition_occurrence
UNION ALL
SELECT 'drug_exposure', count(*) FROM synthea_cdm_benchmark.drug_exposure
UNION ALL
SELECT 'measurement', count(*) FROM synthea_cdm_benchmark.measurement
UNION ALL
SELECT 'observation', count(*) FROM synthea_cdm_benchmark.observation
ORDER BY 1;
"""
    return {name: int(count) for name, count in query_tsv(sql)}


def build_clear_generation_cache_sql(source_key: str) -> str:
    return f"""
WITH source_row AS (
  SELECT source_id
  FROM webapi.source
  WHERE source_key = {sql_quote(source_key)}
),
deleted AS (
  DELETE FROM webapi.generation_cache gc
  USING source_row s
  WHERE gc.type = 'COHORT'
    AND gc.source_id = s.source_id
  RETURNING gc.id
)
SELECT
  COALESCE((SELECT source_id::text FROM source_row), ''),
  count(*)::text
FROM deleted;
"""


def clear_webapi_generation_cache(study_dir: Path) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for _ in range(5):
        try:
            rows = query_tsv(
                build_clear_generation_cache_sql(DEFAULT_SOURCE_KEY),
                db_name="postgres",
                log_path=study_dir / "logs" / "05b_clear_webapi_generation_cache.log",
            )
            if not rows or not rows[0][0]:
                raise RuntimeError(
                    f"WebAPI source key not found in webapi.source: {DEFAULT_SOURCE_KEY}"
                )
            source_id, deleted_count = rows[0]
            return {
                "source_key": DEFAULT_SOURCE_KEY,
                "source_id": int(source_id),
                "deleted_count": int(deleted_count),
            }
        except RuntimeError as exc:
            last_error = exc
            message = str(exc).lower()
            if "recovery mode" not in message and "starting up" not in message:
                raise
            time.sleep(2)
    raise RuntimeError(f"Failed to clear WebAPI generation cache: {last_error}")


def run_attrition_trace(study: StudyConfig, study_dir: Path) -> Path:
    run_id = f"{utc_now()}_{study_slug(study.study_key)}_10k_attrition"
    output_root = study_dir / "attrition_runs"
    max_level = len(read_json(study.gold_json).get("InclusionRules", []))
    run_command(
        [
            sys.executable,
            str(TRACE_SCRIPT),
            "--gold-json",
            str(study.gold_json),
            "--webapi-url",
            DEFAULT_WEBAPI_URL,
            "--source-key",
            DEFAULT_SOURCE_KEY,
            "--output-root",
            str(output_root),
            "--run-id",
            run_id,
            "--min-level",
            "0",
            "--max-level",
            str(max_level),
            "--timeout-seconds",
            str(DEFAULT_ATTRITION_TIMEOUT_SECONDS),
            "--execute",
            "--stop-after-first-zero",
        ],
        cwd=REPO_DIR,
        log_path=study_dir / "logs" / "06_run_attrition.log",
    )
    return output_root / run_id


def load_results_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def summarize_attrition(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {
            "levels_processed": 0,
            "first_zero_level": None,
            "final_level": None,
            "final_person_count": None,
            "final_status": None,
            "final_record": None,
        }
    first_zero = next((record for record in records if record.get("person_count") == 0), None)
    final_record = records[-1]
    return {
        "levels_processed": len(records),
        "first_zero_level": first_zero.get("level") if first_zero else None,
        "final_level": final_record.get("level"),
        "final_person_count": final_record.get("person_count"),
        "final_status": final_record.get("status"),
        "final_record": final_record,
    }


def execute_translated_sql(record: Dict[str, Any], study_dir: Path) -> Dict[str, Any]:
    translated_sql_path = record.get("translated_sql_path")
    target_cohort_id = record.get("target_cohort_id")
    if not translated_sql_path or target_cohort_id is None:
        return {
            "attempted": False,
            "cohort_definition_id": target_cohort_id,
            "person_count": None,
            "error": "translated_sql_path or target_cohort_id missing",
        }

    log_path = study_dir / "logs" / "07_execute_translated_sql.log"
    try:
        run_command(
            ["docker", "exec", "-i", "broadsea-atlasdb", "psql", "-U", "postgres", "-d", "ohdsi"],
            cwd=REPO_DIR,
            log_path=log_path,
            stdin_path=Path(translated_sql_path),
        )
        sql = (
            "SELECT count(DISTINCT subject_id) "
            "FROM synthea_cdm_benchmark_results.cohort "
            f"WHERE cohort_definition_id = {int(target_cohort_id)};"
        )
        rows = query_tsv(sql)
        person_count = int(rows[0][0]) if rows else 0
        return {
            "attempted": True,
            "cohort_definition_id": int(target_cohort_id),
            "person_count": person_count,
            "translated_sql_path": translated_sql_path,
            "log_path": str(log_path),
            "error": None,
        }
    except Exception as exc:
        return {
            "attempted": True,
            "cohort_definition_id": int(target_cohort_id),
            "person_count": None,
            "translated_sql_path": translated_sql_path,
            "log_path": str(log_path),
            "error": str(exc),
        }


def classify_outcome(attrition_summary: Dict[str, Any], direct_sql: Optional[Dict[str, Any]]) -> str:
    final_record = attrition_summary.get("final_record") or {}
    final_person_count = attrition_summary.get("final_person_count")
    if final_person_count and final_person_count > 0:
        return "webapi_nonzero"
    if final_record.get("status") == "FAILED":
        return "webapi_failed"
    if direct_sql and direct_sql.get("error"):
        return "direct_sql_error"
    if direct_sql and direct_sql.get("attempted") and (direct_sql.get("person_count") or 0) > 0:
        return "webapi_direct_sql_divergence"
    if direct_sql and direct_sql.get("attempted"):
        return "direct_sql_zero"
    return "webapi_zero"


def render_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# Generated Gold Study Evaluation",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Patients per study: `{summary['patients_per_study']}`",
        f"- Source key: `{summary['source_key']}`",
        "",
        "| Study | Patients CSV | person | visit_occurrence | WebAPI final | First zero | Direct SQL | Outcome |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for study in summary["studies"]:
        etl_counts = study.get("etl_counts", {})
        attrition = study.get("attrition_summary", {})
        direct_sql = study.get("direct_sql") or {}
        lines.append(
            "| {study} | {patients} | {person} | {visit} | {webapi_final} | {first_zero} | {direct_sql_count} | {outcome} |".format(
                study=study["study_key"],
                patients=study.get("synthea_generation", {}).get("patients_csv_rows", 0),
                person=etl_counts.get("person", 0),
                visit=etl_counts.get("visit_occurrence", 0),
                webapi_final=attrition.get("final_person_count"),
                first_zero=attrition.get("first_zero_level"),
                direct_sql_count=direct_sql.get("person_count"),
                outcome=study.get("outcome"),
            )
        )
    lines.extend(
        [
            "",
            "## Artifact Roots",
            "",
        ]
    )
    for study in summary["studies"]:
        lines.append(f"- `{study['study_key']}`: `{study['study_dir']}`")
    return "\n".join(lines) + "\n"


def run_study(study: StudyConfig, run_dir: Path, patients: int) -> Dict[str, Any]:
    study_dir = run_dir / study_slug(study.study_key)
    study_dir.mkdir(parents=True, exist_ok=True)

    study_summary: Dict[str, Any] = {
        "study_key": study.study_key,
        "gold_json": str(study.gold_json),
        "study_dir": str(study_dir),
    }

    try:
        module_generation = build_module(study, study_dir)
        study_summary["module_generation"] = module_generation

        synthea_generation = generate_synthea_data(study, study_dir, patients)
        study_summary["synthea_generation"] = synthea_generation

        tune_etl_database(study_dir)
        load_native_csvs(study_dir)
        run_etl(study_dir)
        study_summary["webapi_generation_cache_clear"] = clear_webapi_generation_cache(study_dir)

        etl_counts = query_table_counts()
        study_summary["etl_counts"] = etl_counts

        attrition_dir = run_attrition_trace(study, study_dir)
        attrition_records = load_results_jsonl(attrition_dir / "results.jsonl")
        attrition_summary = summarize_attrition(attrition_records)
        study_summary["attrition_dir"] = str(attrition_dir)
        study_summary["attrition_summary"] = attrition_summary

        direct_sql = None
        final_record = attrition_summary.get("final_record") or {}
        if attrition_summary.get("final_person_count") == 0:
            direct_sql = execute_translated_sql(final_record, study_dir)
        study_summary["direct_sql"] = direct_sql
        study_summary["outcome"] = classify_outcome(attrition_summary, direct_sql)
    except Exception as exc:
        study_summary["error"] = str(exc)
        study_summary["outcome"] = "study_error"

    write_json(study_dir / "study_summary.json", study_summary)
    return study_summary


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--studies",
        default="LEADER,PLATO,ARISTOTLE,EMPA-REG",
        help="Comma-separated canonical study keys",
    )
    parser.add_argument("--patients", type=int, default=DEFAULT_PATIENTS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default=utc_now())
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    studies = resolve_studies(args.studies.split(","))
    run_dir = args.output_root / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": args.run_id,
        "patients_per_study": args.patients,
        "source_key": DEFAULT_SOURCE_KEY,
        "webapi_url": DEFAULT_WEBAPI_URL,
        "db_name": DEFAULT_DB_NAME,
        "studies": [study_to_json(study) for study in studies],
    }
    write_json(run_dir / "manifest.json", manifest)

    summaries: List[Dict[str, Any]] = []
    for study in studies:
        summaries.append(run_study(study, run_dir, args.patients))

    overall = {
        "run_id": args.run_id,
        "patients_per_study": args.patients,
        "source_key": DEFAULT_SOURCE_KEY,
        "db_name": DEFAULT_DB_NAME,
        "studies": summaries,
    }
    write_json(run_dir / "summary.json", overall)
    write_text(run_dir / "summary.md", render_markdown(overall))
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
