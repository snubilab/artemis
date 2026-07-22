#!/usr/bin/env python3
"""Trace Gold cohort attrition through WebAPI with reproducible artifacts.

This script is intentionally stdlib-only so it can run in Broadsea without
conda/pip dependencies. It can:

1. Build cumulative L0..Ln payloads from a Gold cohort JSON
2. Optionally prune ConceptSets to only those referenced by the payload
3. Optionally strip censoring/end-strategy for minimal entry-only checks
4. Save payload + generated SQL artifacts
5. Optionally register/generate cohorts on WebAPI and log results as JSONL
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ARTEMIS_DIR / "data" / "gold" / "LEADER" / "LEADER_GOLD.json"
DEFAULT_OUTPUT_ROOT = ARTEMIS_DIR / "output" / "attrition_runs"
DEFAULT_WEBAPI = "http://127.0.0.1/WebAPI"
DEFAULT_SOURCE_KEY = "SYNTHEA_CDM_BENCHMARK"
TARGET_DIALECT = "postgresql"
DEFAULT_TIMEOUT_SECONDS = 14400


class PollTimeoutError(RuntimeError):
    def __init__(
        self,
        *,
        cohort_id: int,
        source_id: int,
        last_status: str,
        elapsed_seconds: int,
    ) -> None:
        super().__init__(
            f"Timed out polling cohort_definition_id={cohort_id} source_id={source_id}"
        )
        self.cohort_id = cohort_id
        self.source_id = source_id
        self.last_status = last_status
        self.elapsed_seconds = elapsed_seconds


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def format_seconds(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    if minutes > 0:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, data: str) -> None:
    path.write_text(data)


def append_jsonl(path: Path, data: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


def _sql_text(sql_resp: Dict[str, Any], key: str) -> str:
    value = sql_resp.get(key, "")
    return value if isinstance(value, str) else ""


def _daimon_table(source: Dict[str, Any], daimon_type: str) -> str:
    for daimon in source.get("daimons", []):
        if daimon.get("daimonType") == daimon_type:
            qualifier = daimon.get("tableQualifier")
            if isinstance(qualifier, str):
                return qualifier
    return ""


def build_sqlrender_placeholders(source: Dict[str, Any], target_cohort_id: int) -> Dict[str, str]:
    cdm_schema = _daimon_table(source, "CDM")
    results_schema = _daimon_table(source, "Results") or (
        f"{cdm_schema}_results" if cdm_schema else ""
    )
    vocabulary_schema = _daimon_table(source, "Vocabulary") or cdm_schema
    return {
        "@cdm_database_schema": cdm_schema,
        "@results_database_schema": results_schema,
        "@target_database_schema": results_schema,
        "@target_cohort_table": "cohort",
        "@target_cohort_id": str(target_cohort_id),
        "@vocabulary_database_schema": vocabulary_schema,
    }


def apply_sqlrender_placeholders(sql: str, placeholders: Dict[str, str]) -> str:
    rendered_sql = sql
    for placeholder, value in placeholders.items():
        rendered_sql = rendered_sql.replace(placeholder, value)
    return rendered_sql


def _split_sql_args(arg_text: str) -> List[str]:
    args: List[str] = []
    current: List[str] = []
    depth = 0
    for char in arg_text:
        if char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            continue
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        current.append(char)
    args.append("".join(current).strip())
    return args


def _rewrite_function_calls(
    sql: str,
    function_name: str,
    replacer,
) -> str:
    token = f"{function_name}("
    upper_sql = sql.upper()
    upper_token = token.upper()
    parts: List[str] = []
    cursor = 0
    while True:
        start = upper_sql.find(upper_token, cursor)
        if start < 0:
            parts.append(sql[cursor:])
            return "".join(parts)

        parts.append(sql[cursor:start])
        args_start = start + len(token)
        depth = 1
        index = args_start
        while index < len(sql):
            char = sql[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        if depth != 0:
            parts.append(sql[start:])
            return "".join(parts)

        args = _split_sql_args(sql[args_start:index])
        replacement = replacer(args)
        if replacement is None:
            parts.append(sql[start : index + 1])
        else:
            parts.append(replacement)
        cursor = index + 1


def _translate_dateadd(args: List[str]) -> Optional[str]:
    if len(args) != 3 or args[0].strip().lower() != "day":
        return None
    return f"({args[2].strip()} + ({args[1].strip()} * INTERVAL '1 day'))"


def _translate_datediff(args: List[str]) -> Optional[str]:
    if len(args) != 3:
        return None
    unit = args[0].strip().strip("'").lower()
    if unit not in {"d", "day"}:
        return None
    return f"(CAST({args[2].strip()} AS DATE) - CAST({args[1].strip()} AS DATE))"


def _translate_datefromparts(args: List[str]) -> Optional[str]:
    if len(args) != 3:
        return None
    return f"make_date({args[0].strip()}, {args[1].strip()}, {args[2].strip()})"


def _temp_table_name(raw_name: str) -> str:
    return f"temp_{raw_name.lstrip('#').lower()}"


def _translate_temp_tables(sql: str) -> str:
    sql = re.sub(
        r"(?i)\bCREATE\s+TABLE\s+#([A-Za-z0-9_]+)",
        lambda match: f"CREATE TEMP TABLE {_temp_table_name(match.group(1))}",
        sql,
    )
    sql = re.sub(
        r"(?i)\bINSERT\s+INTO\s+#([A-Za-z0-9_]+)",
        lambda match: f"INSERT INTO {_temp_table_name(match.group(1))}",
        sql,
    )
    sql = re.sub(
        r"(?i)\bINTO\s+#([A-Za-z0-9_]+)",
        lambda match: f"INTO TEMP {_temp_table_name(match.group(1))}",
        sql,
    )
    sql = re.sub(
        r"(?i)\bDROP\s+TABLE\s+#([A-Za-z0-9_]+)",
        lambda match: f"DROP TABLE IF EXISTS {_temp_table_name(match.group(1))}",
        sql,
    )
    sql = re.sub(
        r"#([A-Za-z0-9_]+)",
        lambda match: _temp_table_name(match.group(1)),
        sql,
    )
    return sql


def render_translated_sql(
    template_sql: str,
    source: Dict[str, Any],
    target_cohort_id: int,
) -> Tuple[str, Dict[str, str]]:
    placeholders = build_sqlrender_placeholders(source, target_cohort_id)
    translated_sql = template_sql
    for placeholder, value in placeholders.items():
        translated_sql = translated_sql.replace(placeholder, value)

    translated_sql = _translate_temp_tables(translated_sql)
    translated_sql = _rewrite_function_calls(translated_sql, "DATEADD", _translate_dateadd)
    translated_sql = _rewrite_function_calls(translated_sql, "DATEDIFF", _translate_datediff)
    translated_sql = _rewrite_function_calls(
        translated_sql,
        "DATEFROMPARTS",
        _translate_datefromparts,
    )
    translated_sql = re.sub(r"(?i)\bCOUNT_BIG\s*\(", "COUNT(", translated_sql)
    return translated_sql, placeholders


def persist_sql_artifacts(
    level_dir: Path,
    sql_resp: Dict[str, Any],
    source: Optional[Dict[str, Any]] = None,
    target_cohort_id: int = 0,
    target_dialect: str = TARGET_DIALECT,
    base_url: str = DEFAULT_WEBAPI,
    allow_python_fallback: bool = False,
) -> Dict[str, Any]:
    template_sql = _sql_text(sql_resp, "templateSql")
    translated_sql = _sql_text(sql_resp, "sql")
    placeholder_values: Dict[str, str] = {}
    translation_method = "webapi_sql" if translated_sql else "template_only"
    if not translated_sql and template_sql:
        sqlrender_resp = translate_sql(base_url, template_sql, target_dialect)
        translated_sql = _sql_text(sqlrender_resp, "targetSQL")
        if translated_sql:
            if source:
                placeholder_values = build_sqlrender_placeholders(source, target_cohort_id)
                translated_sql = apply_sqlrender_placeholders(
                    translated_sql, placeholder_values
                )
            translation_method = "sqlrender_translate"

    if not translated_sql and template_sql and allow_python_fallback and source:
        translated_sql, placeholder_values = render_translated_sql(
            template_sql=template_sql,
            source=source,
            target_cohort_id=target_cohort_id,
        )
        translation_method = "python_fallback"

    if template_sql and not translated_sql:
        raise RuntimeError(
            "sqlrender/translate did not return translated SQL; "
            "rerun with --allow-python-fallback only for explicit debug use"
        )
    template_path = level_dir / "template.sql"
    translated_path = level_dir / "translated.sql"
    translation_meta_path = level_dir / "translation_meta.json"

    write_text(template_path, template_sql)
    if translated_sql:
        write_text(translated_path, translated_sql)

    translation_meta = {
        "target_dialect": target_dialect,
        "translation_method": translation_method,
        "response_keys": sorted(str(key) for key in sql_resp.keys()),
        "placeholder_values": placeholder_values,
        "template_sql_path": str(template_path),
        "template_sql_bytes": len(template_sql.encode("utf-8")),
        "template_sql_present": bool(template_sql),
        "translated_sql_path": str(translated_path) if translated_sql else None,
        "translated_sql_bytes": len(translated_sql.encode("utf-8")),
        "translated_sql_present": bool(translated_sql),
    }
    write_json(translation_meta_path, translation_meta)
    translation_meta["translation_meta_path"] = str(translation_meta_path)
    return translation_meta


def api_request(
    base_url: str,
    method: str,
    endpoint: str,
    data: Optional[Dict[str, Any]] = None,
) -> Any:
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    req = urllib.request.Request(url=url, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
        req.data = payload

    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            content_type = resp.headers.get("Content-Type", "")
            if not body:
                return None
            if "application/json" in content_type or body[:1] in "[{":
                return json.loads(body)
            return body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {method} {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error during {method} {url}: {exc}") from exc


def resolve_source(base_url: str, source_key: str) -> Dict[str, Any]:
    sources = api_request(base_url, "GET", "source/sources")
    if not isinstance(sources, list):
        raise RuntimeError("Unexpected /source/sources response")
    for source in sources:
        if source.get("sourceKey") == source_key:
            return source
    raise RuntimeError(f"Source key not found: {source_key}")


def find_codeset_ids(node: Any) -> Set[int]:
    ids: Set[int] = set()
    if isinstance(node, dict):
        if "CodesetId" in node and isinstance(node["CodesetId"], int):
            ids.add(node["CodesetId"])
        for value in node.values():
            ids |= find_codeset_ids(value)
    elif isinstance(node, list):
        for item in node:
            ids |= find_codeset_ids(item)
    return ids


def build_level_expression(
    gold: Dict[str, Any],
    rule_count: int,
    prune_concept_sets: bool,
    strip_censoring: bool,
    drop_end_strategy: bool,
) -> Tuple[Dict[str, Any], List[str], int]:
    expr = copy.deepcopy(gold)
    all_rules = gold.get("InclusionRules", [])
    selected_rules = copy.deepcopy(all_rules[:rule_count])
    expr["InclusionRules"] = selected_rules

    if strip_censoring:
        expr["CensoringCriteria"] = []
        expr["CensorWindow"] = {}

    if drop_end_strategy:
        expr.pop("EndStrategy", None)

    if prune_concept_sets:
        cs_ids = find_codeset_ids(expr)
        original_sets = {cs["id"]: cs for cs in gold.get("ConceptSets", [])}
        expr["ConceptSets"] = [
            copy.deepcopy(original_sets[csid])
            for csid in sorted(cs_ids)
            if csid in original_sets
        ]

    rule_names = [rule.get("name", f"rule_{idx+1}") for idx, rule in enumerate(selected_rules)]
    concept_set_count = len(expr.get("ConceptSets", []))
    return expr, rule_names, concept_set_count


def generate_levels(
    gold: Dict[str, Any],
    min_level: int,
    max_level: int,
    prune_concept_sets: bool,
    strip_censoring: bool,
    drop_end_strategy: bool,
) -> List[Dict[str, Any]]:
    max_inclusive = min(max_level, len(gold.get("InclusionRules", [])))
    levels: List[Dict[str, Any]] = []
    for level in range(min_level, max_inclusive + 1):
        expr, rule_names, concept_set_count = build_level_expression(
            gold=gold,
            rule_count=level,
            prune_concept_sets=prune_concept_sets,
            strip_censoring=strip_censoring,
            drop_end_strategy=drop_end_strategy,
        )
        label = "EntryOnly" if level == 0 else f"Rule1to{level}"
        levels.append(
            {
                "level": level,
                "label": label,
                "rule_count": level,
                "rule_names": rule_names,
                "concept_set_count": concept_set_count,
                "expression": expr,
            }
        )
    return levels


def register_cohort_definition(
    base_url: str,
    name: str,
    description: str,
    expression: Dict[str, Any],
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "description": description,
        "expressionType": "SIMPLE_EXPRESSION",
        "expression": expression,
    }
    resp = api_request(base_url, "POST", "cohortdefinition", payload)
    if not isinstance(resp, dict) or "id" not in resp:
        raise RuntimeError(f"Unexpected cohortdefinition response: {resp}")
    return resp


def generate_sql(base_url: str, expression: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "expression": expression,
        "options": {"generateStats": True},
        "targetDialect": TARGET_DIALECT,
    }
    resp = api_request(base_url, "POST", "cohortdefinition/sql", payload)
    if not isinstance(resp, dict):
        raise RuntimeError(f"Unexpected SQL generation response: {resp}")
    return resp


def translate_sql(base_url: str, template_sql: str, target_dialect: str) -> Dict[str, Any]:
    payload = {
        "SQL": template_sql,
        "targetdialect": target_dialect,
    }
    resp = api_request(base_url, "POST", "sqlrender/translate", payload)
    if isinstance(resp, str):
        return {"targetSQL": resp}
    if not isinstance(resp, dict):
        raise RuntimeError(f"Unexpected sqlrender/translate response: {resp}")
    return resp


def trigger_generation(base_url: str, cohort_id: int, source_key: str) -> Any:
    return api_request(
        base_url,
        "GET",
        f"cohortdefinition/{cohort_id}/generate/{source_key}",
    )


def fetch_generation_info(base_url: str, cohort_id: int) -> List[Dict[str, Any]]:
    info = api_request(base_url, "GET", f"cohortdefinition/{cohort_id}/info")
    if not isinstance(info, list):
        raise RuntimeError(f"Unexpected generation info response: {info}")
    return info


def poll_generation(
    base_url: str,
    cohort_id: int,
    source_id: int,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> Dict[str, Any]:
    started = time.time()
    poll_round = 0
    last_status = "UNKNOWN"
    while time.time() - started < timeout_seconds:
        poll_round += 1
        infos = fetch_generation_info(base_url, cohort_id)
        for info in infos:
            info_id = info.get("id", {})
            if isinstance(info_id, dict) and info_id.get("sourceId") == source_id:
                status = info.get("status")
                last_status = status
                if status in {"COMPLETE", "FAILED"}:
                    return info
        elapsed = int(time.time() - started)
        print(
            f"[poll:{poll_round:03d}] cohort_definition_id={cohort_id} "
            f"status={last_status} elapsed={format_seconds(elapsed)}"
        )
        time.sleep(poll_interval_seconds)
        if poll_round >= 2 and poll_round % 3 == 0:
            print(
                f"[poll] waiting for completion... remaining poll budget "
                f"{format_seconds(max(timeout_seconds - elapsed, 0))}"
            )
    raise PollTimeoutError(
        cohort_id=cohort_id,
        source_id=source_id,
        last_status=last_status,
        elapsed_seconds=int(time.time() - started),
    )


def build_name(prefix: str, run_id: str, level: int, label: str) -> str:
    return f"{prefix} {run_id} L{level:02d} {label}"


def build_description(
    source_key: str,
    level: int,
    rule_count: int,
    concept_set_count: int,
) -> str:
    return (
        f"Attrition trace for {source_key}: level={level}, "
        f"rule_count={rule_count}, concept_set_count={concept_set_count}"
    )


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-json", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--webapi-url", default=DEFAULT_WEBAPI)
    parser.add_argument("--source-key", default=DEFAULT_SOURCE_KEY)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default=utc_now())
    parser.add_argument("--name-prefix", default="[ATTRITION] Gold LEADER")
    parser.add_argument("--min-level", type=int, default=0)
    parser.add_argument("--max-level", type=int, default=18)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-interval-seconds", type=int, default=5)
    parser.add_argument("--prune-concept-sets", action="store_true")
    parser.add_argument("--strip-censoring", action="store_true")
    parser.add_argument("--drop-end-strategy", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stop-after-first-zero", action="store_true")
    parser.add_argument("--allow-python-fallback", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    gold = read_json(args.gold_json)
    source = resolve_source(args.webapi_url, args.source_key)

    output_dir = args.output_root / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.jsonl"

    manifest = {
        "run_id": args.run_id,
        "gold_json": str(args.gold_json),
        "webapi_url": args.webapi_url,
        "source": {
            "sourceId": source["sourceId"],
            "sourceKey": source["sourceKey"],
            "sourceName": source["sourceName"],
            "daimons": source.get("daimons", []),
        },
        "prune_concept_sets": args.prune_concept_sets,
        "strip_censoring": args.strip_censoring,
        "drop_end_strategy": args.drop_end_strategy,
        "execute": args.execute,
        "min_level": args.min_level,
        "max_level": args.max_level,
        "target_dialect": TARGET_DIALECT,
        "sql_artifacts": {
            "template_sql": "template.sql",
            "translated_sql": "translated.sql",
            "translation_meta": "translation_meta.json",
        },
    }
    write_json(output_dir / "manifest.json", manifest)

    levels = generate_levels(
        gold=gold,
        min_level=args.min_level,
        max_level=args.max_level,
        prune_concept_sets=args.prune_concept_sets,
        strip_censoring=args.strip_censoring,
        drop_end_strategy=args.drop_end_strategy,
    )
    total_levels = len(levels)
    print(
        f"[run] run_id={args.run_id} source={args.source_key} level_range="
        f"{args.min_level}..{args.max_level} total={total_levels} "
        f"mode={'execute' if args.execute else 'dry-run'}"
    )
    write_json(
        output_dir / "levels.json",
        [
            {
                "level": level["level"],
                "label": level["label"],
                "rule_count": level["rule_count"],
                "rule_names": level["rule_names"],
                "concept_set_count": level["concept_set_count"],
            }
            for level in levels
        ],
    )

    for index, level in enumerate(levels, start=1):
        level_num = level["level"]
        label = level["label"]
        remaining = total_levels - index
        print(
            f"[{index}/{total_levels}] start L{level_num:02d} {label} "
            f"(rules={level['rule_count']}, cs={level['concept_set_count']}) "
            f"remaining={remaining}"
        )
        level_dir = output_dir / f"L{level_num:02d}_{label}"
        level_dir.mkdir(parents=True, exist_ok=True)
        level_started = time.time()

        write_json(level_dir / "payload.json", level["expression"])
        sql_resp = generate_sql(args.webapi_url, level["expression"])
        target_cohort_id = level_num

        cohort_name = ""
        cohort_def: Optional[Dict[str, Any]] = None

        if args.execute:
            cohort_name = build_name(args.name_prefix, args.run_id, level_num, label)
            description = build_description(
                source_key=args.source_key,
                level=level_num,
                rule_count=level["rule_count"],
                concept_set_count=level["concept_set_count"],
            )
            cohort_def = register_cohort_definition(
                base_url=args.webapi_url,
                name=cohort_name,
                description=description,
                expression=level["expression"],
            )
            target_cohort_id = int(cohort_def["id"])

        translation_meta = persist_sql_artifacts(
            level_dir,
            sql_resp,
            source=source,
            target_cohort_id=target_cohort_id,
            base_url=args.webapi_url,
            allow_python_fallback=args.allow_python_fallback,
        )

        record: Dict[str, Any] = {
            "timestamp": utc_now(),
            "run_id": args.run_id,
            "level": level_num,
            "label": label,
            "rule_count": level["rule_count"],
            "rule_names": level["rule_names"],
            "concept_set_count": level["concept_set_count"],
            "payload_path": str(level_dir / "payload.json"),
            "template_sql_path": translation_meta["template_sql_path"],
            "template_sql_bytes": translation_meta["template_sql_bytes"],
            "translated_sql_path": translation_meta["translated_sql_path"],
            "translated_sql_bytes": translation_meta["translated_sql_bytes"],
            "translated_sql_present": translation_meta["translated_sql_present"],
            "translation_meta_path": translation_meta["translation_meta_path"],
            "translation_method": translation_meta["translation_method"],
            "sql_response_keys": translation_meta["response_keys"],
            "target_cohort_id": target_cohort_id,
        }

        if not args.execute:
            record["mode"] = "dry-run"
            append_jsonl(results_path, record)
            print(
                f"[dry-run][{index}/{total_levels}] L{level_num:02d} {label}: "
                f"rules={level['rule_count']} cs={level['concept_set_count']} "
                f"template_sql_bytes={record['template_sql_bytes']} "
                f"translated_sql_bytes={record['translated_sql_bytes']} "
                f"took={format_seconds(time.time() - level_started)}"
            )
            continue

        assert cohort_def is not None
        trigger_generation(args.webapi_url, cohort_def["id"], args.source_key)
        try:
            info = poll_generation(
                base_url=args.webapi_url,
                cohort_id=cohort_def["id"],
                source_id=source["sourceId"],
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
        except RuntimeError as exc:
            if not str(exc).startswith("Timed out polling cohort_definition_id="):
                raise

            last_status = getattr(exc, "last_status", "RUNNING")
            elapsed_seconds = getattr(exc, "elapsed_seconds", args.timeout_seconds)
            record.update(
                {
                    "mode": "execute",
                    "cohort_definition_id": cohort_def["id"],
                    "cohort_name": cohort_name,
                    "status": "TIMED_OUT",
                    "last_status": last_status,
                    "person_count": None,
                    "record_count": None,
                    "fail_message": str(exc),
                    "execution_duration": None,
                    "timeout_seconds": args.timeout_seconds,
                    "elapsed_seconds": elapsed_seconds,
                    "generation_info": None,
                }
            )
            append_jsonl(results_path, record)
            print(
                f"[execute][{index}/{total_levels}] L{level_num:02d} {label}: "
                f"status=TIMED_OUT last_status={last_status} "
                f"cohort_id={record.get('cohort_definition_id')} took="
                f"{format_seconds(time.time() - level_started)} remaining={remaining}"
            )
            return 124

        record.update(
            {
                "mode": "execute",
                "cohort_definition_id": cohort_def["id"],
                "cohort_name": cohort_name,
                "status": info.get("status"),
                "person_count": info.get("personCount"),
                "record_count": info.get("recordCount"),
                "fail_message": info.get("failMessage"),
                "execution_duration": info.get("executionDuration"),
                "generation_info": info,
            }
        )
        append_jsonl(results_path, record)
        print(
            f"[execute][{index}/{total_levels}] L{level_num:02d} {label}: "
            f"status={record.get('status')} person_count={record.get('person_count')} "
            f"cohort_id={record.get('cohort_definition_id')} took="
            f"{format_seconds(time.time() - level_started)} remaining={remaining}"
        )

        if args.stop_after_first_zero and record.get("person_count") == 0:
            print("Stopping after first zero person_count.")
            break

    print(f"Artifacts written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
