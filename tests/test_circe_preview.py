"""Tests for CIRCE preview parsing and hash computation.

Following the project's "extracted pure function" pattern — tests call
standalone functions that mirror the TTEService methods but without KO/ORM deps.
"""

from __future__ import annotations

import hashlib
import json


# ---------------------------------------------------------------------------
# Pure-function copies of the service helpers (mirrors tte_service.py impl)
# ---------------------------------------------------------------------------

DOMAIN_MAP = {
    "DrugExposure": "Drug",
    "DrugEra": "Drug",
    "ConditionOccurrence": "Condition",
    "ConditionEra": "Condition",
    "ProcedureOccurrence": "Procedure",
    "Measurement": "Measurement",
    "Observation": "Observation",
    "VisitOccurrence": "Visit",
    "DeviceExposure": "Device",
}


def parse_circe_for_preview(circe: dict, arm_name: str, role: str) -> dict:
    concept_sets = []
    for cs in circe.get("ConceptSets", []):
        items = cs.get("expression", {}).get("items", [])
        concept_sets.append({
            "id": cs["id"],
            "name": cs["name"],
            "conceptIds": [item["concept"]["CONCEPT_ID"] for item in items if not item.get("isExcluded")],
            "includeDescendants": items[0].get("includeDescendants", False) if items else False,
        })

    inclusion_rules = []
    for idx, rule in enumerate(circe.get("InclusionRules", []), start=1):
        expr = rule.get("expression", {})
        criteria_list = expr.get("CriteriaList", [])
        demo_list = expr.get("DemographicCriteriaList", [])

        domain = "Demographics"
        time_window = None

        if criteria_list:
            criteria = criteria_list[0].get("Criteria", {})
            for key, mapped in DOMAIN_MAP.items():
                if key in criteria:
                    domain = mapped
                    break
            sw = criteria_list[0].get("StartWindow")
            if sw:
                start_days = sw.get("Start", {}).get("Days", 0)
                end_days = sw.get("End", {}).get("Days", 0)
                time_window = f"-{start_days}d ~ {end_days}d"
        elif demo_list:
            domain = "Demographics"

        inclusion_rules.append({
            "index": idx,
            "name": rule["name"],
            "domain": domain,
            "timeWindow": time_window,
        })

    return {
        "armName": arm_name,
        "role": role,
        "conceptSets": concept_sets,
        "inclusionRules": inclusion_rules,
    }


def compute_preview_hash(circe_by_arm: dict) -> str:
    serialized = json.dumps(circe_by_arm, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def make_circe(concept_sets=None, inclusion_rules=None):
    """Build minimal CIRCE JSON for testing."""
    return {
        "ConceptSets": concept_sets or [],
        "InclusionRules": inclusion_rules or [],
        "PrimaryCriteria": {
            "CriteriaList": [],
            "ObservationWindow": {},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
    }


def make_concept_set(cs_id, name, concept_id, include_descendants=True):
    return {
        "id": cs_id,
        "name": name,
        "expression": {
            "items": [{
                "concept": {"CONCEPT_ID": concept_id, "CONCEPT_NAME": name},
                "includeDescendants": include_descendants,
                "isExcluded": False,
            }]
        },
    }


def make_drug_rule(name, codeset_id, start_days=365, end_days=0):
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [{
                "Criteria": {"DrugExposure": {"CodesetId": codeset_id}},
                "StartWindow": {
                    "Start": {"Days": start_days, "Coeff": -1},
                    "End": {"Days": end_days, "Coeff": 1},
                },
                "Occurrence": {"Type": 2, "Count": 1},
            }],
            "DemographicCriteriaList": [],
            "Groups": [],
        },
    }


def make_condition_rule(name, codeset_id):
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [{
                "Criteria": {"ConditionOccurrence": {"CodesetId": codeset_id}},
            }],
            "DemographicCriteriaList": [],
            "Groups": [],
        },
    }


def make_demographic_rule(name):
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [],
            "DemographicCriteriaList": [{"Age": {"Op": "gte", "Value": 18}}],
            "Groups": [],
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseCirceForPreview:
    """Tests for the pure CIRCE -> ArmPreview parsing function."""

    def test_extracts_concept_sets(self):
        circe = make_circe(concept_sets=[
            make_concept_set(0, "Type 2 DM", 201826),
            make_concept_set(1, "liraglutide", 40170911),
        ])
        result = parse_circe_for_preview(circe, "liraglutide", "treatment")
        assert len(result["conceptSets"]) == 2
        assert result["conceptSets"][0]["name"] == "Type 2 DM"
        assert result["conceptSets"][1]["conceptIds"] == [40170911]

    def test_extracts_include_descendants(self):
        circe = make_circe(concept_sets=[
            make_concept_set(0, "test", 123, include_descendants=False),
        ])
        result = parse_circe_for_preview(circe, "test", "treatment")
        assert result["conceptSets"][0]["includeDescendants"] is False

    def test_drug_rule_domain_and_time_window(self):
        circe = make_circe(inclusion_rules=[make_drug_rule("liraglutide", 1)])
        result = parse_circe_for_preview(circe, "liraglutide", "treatment")
        assert result["inclusionRules"][0]["domain"] == "Drug"
        assert result["inclusionRules"][0]["timeWindow"] == "-365d ~ 0d"

    def test_condition_rule_domain(self):
        circe = make_circe(inclusion_rules=[make_condition_rule("T2DM dx", 0)])
        result = parse_circe_for_preview(circe, "test", "treatment")
        assert result["inclusionRules"][0]["domain"] == "Condition"

    def test_demographic_rule_domain_no_time_window(self):
        circe = make_circe(inclusion_rules=[make_demographic_rule("Age >= 18")])
        result = parse_circe_for_preview(circe, "test", "treatment")
        assert result["inclusionRules"][0]["domain"] == "Demographics"
        assert result["inclusionRules"][0]["timeWindow"] is None

    def test_multiple_concepts_in_set(self):
        cs = make_concept_set(0, "GLP-1", 40170911)
        cs["expression"]["items"].append({
            "concept": {"CONCEPT_ID": 1234567, "CONCEPT_NAME": "exenatide"},
            "includeDescendants": True,
            "isExcluded": False,
        })
        circe = make_circe(concept_sets=[cs])
        result = parse_circe_for_preview(circe, "test", "treatment")
        assert result["conceptSets"][0]["conceptIds"] == [40170911, 1234567]

    def test_empty_circe(self):
        circe = make_circe()
        result = parse_circe_for_preview(circe, "empty", "treatment")
        assert result["conceptSets"] == []
        assert result["inclusionRules"] == []

    def test_arm_name_and_role(self):
        circe = make_circe()
        result = parse_circe_for_preview(circe, "metformin", "comparator")
        assert result["armName"] == "metformin"
        assert result["role"] == "comparator"

    def test_rule_index_is_sequential(self):
        circe = make_circe(inclusion_rules=[
            make_demographic_rule("Age"),
            make_condition_rule("DM", 0),
            make_drug_rule("drug", 1),
        ])
        result = parse_circe_for_preview(circe, "test", "treatment")
        assert [r["index"] for r in result["inclusionRules"]] == [1, 2, 3]

    def test_procedure_domain(self):
        rule = {
            "name": "Surgery",
            "expression": {
                "Type": "ALL",
                "CriteriaList": [{"Criteria": {"ProcedureOccurrence": {"CodesetId": 2}}}],
                "DemographicCriteriaList": [],
                "Groups": [],
            },
        }
        circe = make_circe(inclusion_rules=[rule])
        result = parse_circe_for_preview(circe, "test", "treatment")
        assert result["inclusionRules"][0]["domain"] == "Procedure"


class TestPreviewHash:
    def test_same_circe_produces_same_hash(self):
        circe = make_circe(concept_sets=[make_concept_set(0, "test", 123)])
        h1 = compute_preview_hash({"arm0": circe})
        h2 = compute_preview_hash({"arm0": circe})
        assert h1 == h2

    def test_different_circe_produces_different_hash(self):
        c1 = make_circe(concept_sets=[make_concept_set(0, "a", 1)])
        c2 = make_circe(concept_sets=[make_concept_set(0, "b", 2)])
        assert compute_preview_hash({"arm0": c1}) != compute_preview_hash({"arm0": c2})
