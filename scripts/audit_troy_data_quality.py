#!/usr/bin/env python3
"""
TROY Cohort Definition Data Quality Audit
==========================================
Scans all [TROY] JSON files in data/sample/ to identify:
1. Name vs Value mismatch (rule name implies X but logic checks Y)
2. Name vs Occurrence mismatch (PRESENCE vs ABSENCE confusion)
3. CodesetId integrity (references to undefined concept sets)
4. Temporal window anomalies (clinically implausible windows)
5. Cross-trial consistency (same concept sets with different logic)
6. Concept set quality (empty sets, non-standard without includeMapped)

Usage:
    python scripts/audit_troy_data_quality.py
"""

import json
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any


# ── Occurrence Type mapping in Circe JSON ──
OCCURRENCE_TYPE = {
    0: "EXACTLY",    # exactly N times
    1: "AT_MOST",    # at most N times
    2: "AT_LEAST",   # at least N times
}

OP_LABELS = {
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "eq": "=",
    "neq": "!=",
    "bt": "between",
    "!bt": "not between",
}


@dataclass
class Finding:
    severity: str           # CRITICAL / WARNING / INFO
    category: str
    rule_name: str
    detail: str
    file: str = ""


@dataclass
class AuditResult:
    file: str
    trial: str
    cohort_name: str
    total_concept_sets: int = 0
    total_inclusion_rules: int = 0
    findings: list = field(default_factory=list)


def parse_troy_json(filepath: Path) -> dict:
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def extract_concept_set_ids(data: dict) -> dict[int, str]:
    cs_map = {}
    for cs in data.get("ConceptSets", []):
        cs_map[cs["id"]] = cs["name"]
    return cs_map


def extract_value_from_name(name: str) -> list[dict]:
    """Extract numeric thresholds from rule name."""
    results = []
    for match in re.finditer(r'([><=!]+)\s*([\d.]+)', name):
        op_str, val_str = match.group(1), match.group(2)
        op_map = {">=": "gte", "<=": "lte", ">": "gt", "<": "lt", "=": "eq", "!=": "neq"}
        op = op_map.get(op_str, op_str)
        results.append({"op": op, "value": float(val_str)})
    range_match = re.search(r'(\d+)\s*[-–]\s*(\d+)', name)
    if range_match:
        results.append({
            "op": "between",
            "low": float(range_match.group(1)),
            "high": float(range_match.group(2))
        })
    return results


def check_name_implies_presence_or_absence(name: str) -> str | None:
    lower = name.lower().strip()
    if re.match(r'^(no |not |without |exclude|absence)', lower):
        return "ABSENCE"
    if re.match(r'^(has |with |prior |history )', lower):
        return "PRESENCE"
    return None


def window_to_days(window_endpoint: dict) -> int:
    """Convert Circe window endpoint to actual day offset.
    
    Circe convention:
    - Days: absolute number of days
    - Coeff: -1 = before event, +1 = after event
    So Days=180, Coeff=-1 → -180 (180 days before)
       Days=0, Coeff=1  → 0 (event date)
       Days=0, Coeff=-1 → 0 (also event date, since 0*-1 = 0)
    """
    days = window_endpoint.get("Days", 0)
    coeff = window_endpoint.get("Coeff", 1)
    return days * coeff


def audit_criteria(criteria_item: dict, rule_name: str, cs_map: dict[int, str]) -> list[Finding]:
    findings = []
    criteria = criteria_item.get("Criteria", {})
    
    table_key = None
    table_data = None
    for key in ["Measurement", "ConditionOccurrence", "DrugExposure", 
                 "ProcedureOccurrence", "Observation", "DeviceExposure", "VisitOccurrence"]:
        if key in criteria:
            table_key = key
            table_data = criteria[key]
            break
    
    if not table_data:
        return findings
    
    # ── Check 1: CodesetId integrity ──
    codeset_id = table_data.get("CodesetId")
    if codeset_id is not None and codeset_id not in cs_map:
        findings.append(Finding(
            severity="CRITICAL",
            category="codeset_missing",
            rule_name=rule_name,
            detail=f"CodesetId={codeset_id} in {table_key} not defined in ConceptSets"
        ))
    
    # ── Check 2: Name vs ValueAsNumber mismatch ──
    value_spec = table_data.get("ValueAsNumber")
    if value_spec:
        actual_value = value_spec.get("Value")
        actual_op = value_spec.get("Op", "")
        actual_op_label = OP_LABELS.get(actual_op, actual_op)
        
        name_values = extract_value_from_name(rule_name)
        for nv in name_values:
            if "value" in nv and actual_value is not None:
                if nv["value"] != actual_value:
                    findings.append(Finding(
                        severity="CRITICAL",
                        category="name_value_mismatch",
                        rule_name=rule_name,
                        detail=(
                            f"Name implies value={nv['value']} (op={OP_LABELS.get(nv['op'], nv['op'])}), "
                            f"but actual ValueAsNumber: {actual_op_label} {actual_value}"
                        )
                    ))
                elif nv.get("op") and nv["op"] != actual_op:
                    findings.append(Finding(
                        severity="WARNING",
                        category="name_op_mismatch",
                        rule_name=rule_name,
                        detail=(
                            f"Name implies op={OP_LABELS.get(nv['op'], nv['op'])}, "
                            f"but actual Op={actual_op_label} (value={actual_value})"
                        )
                    ))
    
    # ── Check 3: Name vs Occurrence mismatch ──
    occurrence = criteria_item.get("Occurrence", {})
    occ_type = occurrence.get("Type")
    occ_count = occurrence.get("Count")
    
    if occ_type is not None:
        occ_label = OCCURRENCE_TYPE.get(occ_type, f"unknown({occ_type})")
        is_absence = (occ_type == 0 and occ_count == 0)
        
        name_expectation = check_name_implies_presence_or_absence(rule_name)
        
        if is_absence and name_expectation == "PRESENCE":
            findings.append(Finding(
                severity="CRITICAL",
                category="occurrence_mismatch",
                rule_name=rule_name,
                detail=f"Name implies PRESENCE, but Occurrence is EXACTLY 0 (=ABSENCE)"
            ))
        elif not is_absence and name_expectation == "ABSENCE":
            findings.append(Finding(
                severity="WARNING",
                category="occurrence_mismatch",
                rule_name=rule_name,
                detail=f"Name implies ABSENCE, but Occurrence is {occ_label} {occ_count}"
            ))
        
        # Flagging ABSENCE + value_filter pattern (HbA1c-like)
        if is_absence and value_spec:
            findings.append(Finding(
                severity="INFO",
                category="absence_with_value",
                rule_name=rule_name,
                detail=(
                    f"Ceiling/floor check: no measurement "
                    f"{OP_LABELS.get(value_spec.get('Op',''), '')} {value_spec.get('Value')} "
                    f"allowed (Occurrence=EXACTLY 0)"
                )
            ))
    
    # ── Check 4: Temporal window anomalies ──
    window = criteria_item.get("StartWindow")
    if window:
        start = window.get("Start", {})
        end = window.get("End", {})
        start_day = window_to_days(start)
        end_day = window_to_days(end)
        
        if start_day > end_day:
            findings.append(Finding(
                severity="CRITICAL",
                category="window_inversion",
                rule_name=rule_name,
                detail=f"Temporal window inverted: start={start_day}d > end={end_day}d"
            ))
        
        span = abs(end_day - start_day)
        if span > 3650:
            findings.append(Finding(
                severity="WARNING",
                category="window_large",
                rule_name=rule_name,
                detail=f"Temporal window > 10y: {start_day}d to {end_day}d ({span} days)"
            ))
    
    return findings


def audit_inclusion_rules(data: dict, cs_map: dict[int, str]) -> list[Finding]:
    findings = []
    for rule in data.get("InclusionRules", []):
        rule_name = rule.get("name", "<unnamed>")
        expression = rule.get("expression", {})
        
        for ci in expression.get("CriteriaList", []):
            findings.extend(audit_criteria(ci, rule_name, cs_map))
        
        stack = list(expression.get("Groups", []))
        while stack:
            group = stack.pop()
            for ci in group.get("CriteriaList", []):
                findings.extend(audit_criteria(ci, rule_name, cs_map))
            stack.extend(group.get("Groups", []))
    
    return findings


def audit_primary_criteria(data: dict, cs_map: dict[int, str]) -> list[Finding]:
    findings = []
    pc = data.get("PrimaryCriteria", {})
    for item in pc.get("CriteriaList", []):
        for key in ["DrugExposure", "ConditionOccurrence", "Measurement", 
                     "ProcedureOccurrence", "Observation", "DeviceExposure"]:
            if key in item:
                codeset_id = item[key].get("CodesetId")
                if codeset_id is not None and codeset_id not in cs_map:
                    findings.append(Finding(
                        severity="CRITICAL",
                        category="codeset_missing",
                        rule_name="PrimaryCriteria",
                        detail=f"CodesetId={codeset_id} in {key} not defined"
                    ))
    return findings


def audit_concept_sets(data: dict) -> list[Finding]:
    findings = []
    for cs in data.get("ConceptSets", []):
        name = cs.get("name", "<unnamed>")
        items = cs.get("expression", {}).get("items", [])
        
        if len(items) == 0:
            findings.append(Finding(
                severity="WARNING",
                category="empty_concept_set",
                rule_name=f"ConceptSet: {name}",
                detail=f"'{name}' (id={cs['id']}) has 0 items"
            ))
        
        non_std = []
        for item in items:
            c = item.get("concept", {})
            if c.get("STANDARD_CONCEPT") != "S" and not item.get("includeMapped", False):
                non_std.append(f"{c.get('CONCEPT_NAME','?')} ({c.get('VOCABULARY_ID','?')})")
        
        if non_std:
            findings.append(Finding(
                severity="WARNING",
                category="non_standard_no_mapped",
                rule_name=f"ConceptSet: {name}",
                detail=(
                    f"{len(non_std)} non-standard concept(s) without includeMapped: "
                    f"{'; '.join(non_std[:3])}"
                    + (f"... (+{len(non_std)-3} more)" if len(non_std) > 3 else "")
                )
            ))
    return findings


def cross_trial_check(all_data: dict[str, dict]) -> list[Finding]:
    findings = []
    # Compare DPP-4 trial-specific comparator arms across trials
    dpp4_trial_files = {}
    for path, data in all_data.items():
        pname = Path(path).name
        if "DPP-4" in pname and "(" in pname:
            trial = Path(path).parent.name
            dpp4_trial_files[f"{trial}: {pname}"] = set(
                r.get("name", "") for r in data.get("InclusionRules", [])
            )
    
    paths = sorted(dpp4_trial_files.keys())
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            p1, p2 = paths[i], paths[j]
            only1 = dpp4_trial_files[p1] - dpp4_trial_files[p2]
            only2 = dpp4_trial_files[p2] - dpp4_trial_files[p1]
            if only1 or only2:
                parts = []
                if only1:
                    parts.append(f"Only in {p1}: {sorted(only1)[:3]}")
                if only2:
                    parts.append(f"Only in {p2}: {sorted(only2)[:3]}")
                findings.append(Finding(
                    severity="INFO",
                    category="cross_trial_diff",
                    rule_name="DPP-4 comparator",
                    detail="; ".join(parts),
                    file="cross-trial"
                ))
    return findings


def print_report(all_results: list[AuditResult], cross_findings: list[Finding]):
    tc = tw = ti = 0
    
    print("=" * 80)
    print("  TROY Data Quality Audit Report")
    print("=" * 80)
    
    for result in all_results:
        cs = [f for f in result.findings if f.severity == "CRITICAL"]
        ws = [f for f in result.findings if f.severity == "WARNING"]
        is_ = [f for f in result.findings if f.severity == "INFO"]
        tc += len(cs); tw += len(ws); ti += len(is_)
        
        print(f"\n{'─' * 80}")
        print(f"📁 {result.trial} / {Path(result.file).name}")
        print(f"   ConceptSets: {result.total_concept_sets} | InclusionRules: {result.total_inclusion_rules}")
        
        if not result.findings:
            print(f"   ✅ No issues found")
            continue
        
        print(f"   🔴 {len(cs)} | 🟡 {len(ws)} | ℹ️  {len(is_)}")
        
        for f in cs:
            print(f"\n   🔴 [{f.category}] {f.rule_name}")
            print(f"      → {f.detail}")
        for f in ws:
            print(f"\n   🟡 [{f.category}] {f.rule_name}")
            print(f"      → {f.detail}")
        for f in is_:
            print(f"\n   ℹ️  [{f.category}] {f.rule_name}")
            print(f"      → {f.detail}")
    
    if cross_findings:
        print(f"\n{'─' * 80}")
        print("🔗 Cross-Trial Consistency")
        for f in cross_findings:
            icon = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "ℹ️ "}.get(f.severity, "?")
            print(f"\n   {icon} [{f.category}]")
            print(f"      → {f.detail}")
    
    print(f"\n{'=' * 80}")
    print(f"  SUMMARY: {len(all_results)} TROY files audited")
    print(f"  🔴 Critical: {tc}  |  🟡 Warning: {tw}  |  ℹ️  Info: {ti}")
    if cross_findings:
        print(f"  🔗 Cross-trial: {len(cross_findings)}")
    print(f"{'=' * 80}")


def main():
    sample_dir = Path(__file__).parent.parent / "data" / "sample"
    
    if not sample_dir.exists():
        print(f"ERROR: {sample_dir} does not exist")
        sys.exit(1)
    
    # Find TROY files by checking filename starts with "[TROY]"
    troy_files = []
    for f in sorted(sample_dir.rglob("*.json")):
        if f.name.startswith("[TROY]"):
            troy_files.append(f)
    
    if not troy_files:
        print(f"No [TROY] JSON files found in {sample_dir}")
        sys.exit(1)
    
    print(f"Found {len(troy_files)} [TROY] JSON files to audit")
    for f in troy_files:
        print(f"  • {f.parent.name}/{f.name}")
    print()
    
    all_results = []
    all_data = {}
    
    for filepath in troy_files:
        trial = filepath.parent.name
        data = parse_troy_json(filepath)
        all_data[str(filepath)] = data
        
        cs_map = extract_concept_set_ids(data)
        
        result = AuditResult(
            file=str(filepath),
            trial=trial,
            cohort_name=filepath.stem,
            total_concept_sets=len(cs_map),
            total_inclusion_rules=len(data.get("InclusionRules", []))
        )
        
        result.findings.extend(audit_concept_sets(data))
        result.findings.extend(audit_primary_criteria(data, cs_map))
        result.findings.extend(audit_inclusion_rules(data, cs_map))
        
        for f in result.findings:
            if not f.file:
                f.file = str(filepath)
        
        all_results.append(result)
    
    cross_findings = cross_trial_check(all_data)
    print_report(all_results, cross_findings)


if __name__ == "__main__":
    main()
