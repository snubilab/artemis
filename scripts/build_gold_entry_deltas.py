#!/usr/bin/env python3
"""Build baseline-vs-Gold entry delta cohorts and save dry-run artifacts.

This script constructs a small family of cohorts to isolate which Gold entry
component causes WebAPI cohort generation to diverge from baseline.
"""

from __future__ import annotations

import argparse
import copy
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_DIR = ARTEMIS_DIR / "output" / "attrition_compare" / "20260317_baseline_compare"
DEFAULT_GOLD = ARTEMIS_DIR / "data" / "gold" / "LEADER" / "LEADER_GOLD.json"
DEFAULT_OUTPUT_DIR = ARTEMIS_DIR / "output" / "attrition_compare" / "20260317_delta_payloads"
DEFAULT_WEBAPI = "http://127.0.0.1/WebAPI"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, text: str) -> None:
    path.write_text(text)


def api_post_json(base_url: str, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} POST {url}: {body}") from exc


def collect_codeset_ids(node: Any) -> Set[int]:
    ids: Set[int] = set()
    if isinstance(node, dict):
        if "CodesetId" in node and isinstance(node["CodesetId"], int):
            ids.add(node["CodesetId"])
        for value in node.values():
            ids |= collect_codeset_ids(value)
    elif isinstance(node, list):
        for item in node:
            ids |= collect_codeset_ids(item)
    return ids


def prune_concept_sets(expression: Dict[str, Any], gold: Dict[str, Any]) -> None:
    ids = collect_codeset_ids(expression)
    concept_map = {cs["id"]: cs for cs in gold.get("ConceptSets", [])}
    expression["ConceptSets"] = [
        copy.deepcopy(concept_map[csid])
        for csid in sorted(ids)
        if csid in concept_map
    ]


def load_baseline_expression(baseline_dir: Path, cohort_id: int) -> Dict[str, Any]:
    return read_json(baseline_dir / str(cohort_id) / "expression.json")


def build_variants(
    baseline_expr: Dict[str, Any],
    gold: Dict[str, Any],
) -> List[Dict[str, Any]]:
    variants: List[Dict[str, Any]] = []

    p0 = copy.deepcopy(baseline_expr)
    variants.append(
        {
            "key": "P0",
            "description": "Baseline 238 expression",
            "expression": p0,
        }
    )

    p1 = copy.deepcopy(baseline_expr)
    p1["AdditionalCriteria"] = copy.deepcopy(gold["AdditionalCriteria"])
    prune_concept_sets(p1, gold)
    variants.append(
        {
            "key": "P1",
            "description": "P0 + AdditionalCriteria only",
            "expression": p1,
        }
    )

    p2 = copy.deepcopy(p1)
    p2["EndStrategy"] = copy.deepcopy(gold["EndStrategy"])
    prune_concept_sets(p2, gold)
    variants.append(
        {
            "key": "P2",
            "description": "P1 + EndStrategy",
            "expression": p2,
        }
    )

    p3 = copy.deepcopy(p2)
    p3["CensoringCriteria"] = copy.deepcopy(gold["CensoringCriteria"])
    p3["CensorWindow"] = copy.deepcopy(gold.get("CensorWindow", {}))
    prune_concept_sets(p3, gold)
    variants.append(
        {
            "key": "P3",
            "description": "P2 + CensoringCriteria",
            "expression": p3,
        }
    )

    p4 = copy.deepcopy(p1)
    p4["ConceptSets"] = copy.deepcopy(gold["ConceptSets"])
    variants.append(
        {
            "key": "P4",
            "description": "P1 + full Gold ConceptSets",
            "expression": p4,
        }
    )

    p5 = copy.deepcopy(p4)
    p5["InclusionRules"] = [copy.deepcopy(gold["InclusionRules"][0])]
    variants.append(
        {
            "key": "P5",
            "description": "P4 + Rule 1 (Age >= 50)",
            "expression": p5,
        }
    )

    return variants


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE_DIR)
    parser.add_argument("--baseline-id", type=int, default=238)
    parser.add_argument("--gold-json", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--webapi-url", default=DEFAULT_WEBAPI)
    args = parser.parse_args(list(argv))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    gold = read_json(args.gold_json)
    baseline_expr = load_baseline_expression(args.baseline_dir, args.baseline_id)
    variants = build_variants(baseline_expr, gold)

    manifest: List[Dict[str, Any]] = []
    for variant in variants:
        key = variant["key"]
        expr = variant["expression"]
        vdir = args.output_dir / key
        vdir.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": f"[DELTA] {key}",
            "description": variant["description"],
            "expressionType": "SIMPLE_EXPRESSION",
            "expression": expr,
        }
        write_json(vdir / "payload.json", payload)
        write_json(vdir / "expression.json", expr)

        sql_resp = api_post_json(
            args.webapi_url,
            "cohortdefinition/sql",
            {
                "expression": expr,
                "options": {"generateStats": True},
                "targetDialect": "postgresql",
            },
        )
        write_json(vdir / "sql_response.json", sql_resp)
        write_text(vdir / "template.sql", sql_resp.get("templateSql", ""))
        if sql_resp.get("sql"):
            write_text(vdir / "translated.sql", sql_resp["sql"])

        summary = {
            "key": key,
            "description": variant["description"],
            "concept_set_count": len(expr.get("ConceptSets", [])),
            "concept_set_ids": [cs["id"] for cs in expr.get("ConceptSets", [])],
            "inclusion_rule_count": len(expr.get("InclusionRules", [])),
            "has_additional_criteria": isinstance(expr.get("AdditionalCriteria"), dict),
            "has_end_strategy": "EndStrategy" in expr and bool(expr.get("EndStrategy")),
            "censoring_criteria_count": len(expr.get("CensoringCriteria", [])),
            "template_sql_bytes": len(sql_resp.get("templateSql", "").encode("utf-8")),
        }
        write_json(vdir / "summary.json", summary)
        manifest.append(summary)

    write_json(args.output_dir / "manifest.json", manifest)
    print(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
