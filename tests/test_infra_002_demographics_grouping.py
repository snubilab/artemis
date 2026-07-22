"""
SPEC-INFRA-002: Demographics groupId preservation in CIRCE builder.

Tests that _build_seeded_target_circe correctly groups demographic criteria
that share a groupId with non-demographic siblings, instead of flattening
them into separate InclusionRules.
"""
import pytest
from copy import deepcopy
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_criterion(
    *,
    id: int,
    description: str,
    domain: str,
    group_id: str | None = None,
    group_type: str = "ALL",
    value_constraint: dict | None = None,
    window: dict | None = None,
) -> dict:
    """Build a criterion dict matching the shape used by _build_seeded_target_circe."""
    crit: dict = {
        "id": id,
        "description": description,
        "domain": domain,
        "groupId": group_id,
        "groupType": group_type,
    }
    if value_constraint:
        crit["valueConstraint"] = value_constraint
    if window:
        crit["window"] = window
    return crit


def _age_criterion(
    id: int, *, op: str, value: int, group_id: str | None = None, group_type: str = "ALL",
) -> dict:
    return _make_criterion(
        id=id,
        description=f"Age {op} {value}",
        domain="Demographics",
        group_id=group_id,
        group_type=group_type,
        value_constraint={"op": op, "value": value},
    )


def _condition_criterion(
    id: int, description: str, *, group_id: str | None = None, group_type: str = "ALL",
) -> dict:
    return _make_criterion(
        id=id,
        description=description,
        domain="Condition",
        group_id=group_id,
        group_type=group_type,
        window={"start": -365, "end": 0},
    )


def _stub_recommend(name: str, expected_domain: str | None = None, workflow=None):
    """Return a minimal concept set recommendation stub."""
    return {
        "name": name,
        "domain": "Condition",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 99999}}]},
    }


def _stub_eligibility_rule(criterion, *, codeset_id, exclusion):
    """Return a minimal eligibility rule result stub."""
    label = criterion.get("description", "rule")
    return {
        "conceptSet": {
            "id": codeset_id,
            "name": label,
            "expression": {"items": []},
        },
        "rule": {
            "name": label,
            "expression": {
                "Type": "ALL",
                "CriteriaList": [
                    {"ConditionOccurrence": {"CodesetId": codeset_id}}
                ],
                "DemographicCriteriaList": [],
                "Groups": [],
            },
        },
    }


# ---------------------------------------------------------------------------
# Fixture: patched TTEService instance
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    """Create a TTEService with stubs for the expensive mapping methods."""
    # Import here so module-level import failures don't mask test collection
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    # Stub the methods that call Agent2 / vector search
    svc._recommend_seeded_concept_set = MagicMock(side_effect=_stub_recommend)
    svc._build_seeded_eligibility_rule = MagicMock(side_effect=lambda **kw: _stub_eligibility_rule(
        kw["criterion"], codeset_id=kw["codeset_id"], exclusion=kw["exclusion"],
    ))
    svc._seeded_primary_criteria_key = MagicMock(return_value="ConditionOccurrence")
    svc._patch_codeset_id_in_rule = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Test 1: Simple demographics (null groupId) -- unchanged behavior
# ---------------------------------------------------------------------------

class TestSimpleDemographics:
    """REQ-05: Demographics with null groupId remain as separate InclusionRules."""

    def test_null_group_id_produces_separate_rules(self, service):
        eligibility = {
            "targetCohortName": "T2DM cohort",
            "inclusionCriteria": [
                _age_criterion(1, op="gte", value=18),
            ],
            "exclusionCriteria": [],
        }
        result = service._build_seeded_target_circe(eligibility)
        rules = result["InclusionRules"]

        # Should have exactly 1 inclusion rule for the age criterion
        assert len(rules) == 1
        rule = rules[0]
        assert rule["expression"]["DemographicCriteriaList"] != []
        assert rule["expression"]["DemographicCriteriaList"][0]["Age"]["Value"] == 18
        assert rule["expression"]["DemographicCriteriaList"][0]["Age"]["Op"] == "gte"

    def test_multiple_ungrouped_demographics(self, service):
        eligibility = {
            "targetCohortName": "T2DM cohort",
            "inclusionCriteria": [
                _age_criterion(1, op="gte", value=18),
                _age_criterion(2, op="lte", value=65),
            ],
            "exclusionCriteria": [],
        }
        result = service._build_seeded_target_circe(eligibility)
        rules = result["InclusionRules"]

        # Each ungrouped demographic should be its own rule
        assert len(rules) == 2
        assert rules[0]["expression"]["DemographicCriteriaList"][0]["Age"]["Value"] == 18
        assert rules[1]["expression"]["DemographicCriteriaList"][0]["Age"]["Value"] == 65


# ---------------------------------------------------------------------------
# Test 2: Grouped demographics (same groupId) -- REQ-01
# ---------------------------------------------------------------------------

class TestGroupedDemographics:
    """REQ-01: Demographics with non-null groupId form one grouped InclusionRule."""

    def test_same_group_id_produces_single_rule_with_groups(self, service):
        eligibility = {
            "targetCohortName": "CV cohort",
            "inclusionCriteria": [
                _age_criterion(1, op="gte", value=50, group_id="g1", group_type="ANY"),
                _age_criterion(2, op="gte", value=60, group_id="g1", group_type="ANY"),
            ],
            "exclusionCriteria": [],
        }
        result = service._build_seeded_target_circe(eligibility)
        rules = result["InclusionRules"]

        # Should produce ONE rule, not two separate rules
        assert len(rules) == 1
        rule = rules[0]
        expr = rule["expression"]

        # The top-level Type should be the groupType ("ANY")
        assert expr["Type"] == "ANY"

        # Should have Groups, each containing a DemographicCriteriaList
        assert len(expr["Groups"]) == 2
        for group in expr["Groups"]:
            assert len(group["DemographicCriteriaList"]) == 1

        ages = sorted(
            g["DemographicCriteriaList"][0]["Age"]["Value"]
            for g in expr["Groups"]
        )
        assert ages == [50, 60]


# ---------------------------------------------------------------------------
# Test 3: Mixed group -- REQ-03
# ---------------------------------------------------------------------------

class TestMixedGroup:
    """REQ-03: Group containing both Demographics and Condition criteria."""

    def test_mixed_group_has_both_criteria_types(self, service):
        eligibility = {
            "targetCohortName": "CV risk cohort",
            "inclusionCriteria": [
                _age_criterion(1, op="gte", value=50, group_id="g1", group_type="ALL"),
                _condition_criterion(2, "CVD history", group_id="g1", group_type="ALL"),
            ],
            "exclusionCriteria": [],
        }
        result = service._build_seeded_target_circe(eligibility)
        rules = result["InclusionRules"]

        # Should be exactly 1 grouped rule
        assert len(rules) == 1
        rule = rules[0]
        expr = rule["expression"]

        # The group should contain both a DemographicCriteriaList and CriteriaList
        # At least one of these should be non-empty
        has_demo = any(
            g.get("DemographicCriteriaList", []) for g in expr.get("Groups", [])
        ) or bool(expr.get("DemographicCriteriaList"))
        has_condition = any(
            g.get("CriteriaList", []) for g in expr.get("Groups", [])
        ) or bool(expr.get("CriteriaList"))

        assert has_demo, "Mixed group must contain DemographicCriteriaList"
        assert has_condition, "Mixed group must contain CriteriaList"


# ---------------------------------------------------------------------------
# Test 4: Multiple groups -- REQ-01 + REQ-02
# ---------------------------------------------------------------------------

class TestMultipleGroups:
    """Different groupIds produce separate InclusionRules."""

    def test_two_groups_produce_two_rules(self, service):
        eligibility = {
            "targetCohortName": "Multi group",
            "inclusionCriteria": [
                _age_criterion(1, op="gte", value=50, group_id="g1", group_type="ANY"),
                _age_criterion(2, op="gte", value=60, group_id="g1", group_type="ANY"),
                _age_criterion(3, op="lte", value=80, group_id="g2", group_type="ALL"),
                _age_criterion(4, op="gte", value=40, group_id="g2", group_type="ALL"),
            ],
            "exclusionCriteria": [],
        }
        result = service._build_seeded_target_circe(eligibility)
        rules = result["InclusionRules"]

        # Two distinct groups -> 2 inclusion rules
        assert len(rules) == 2

        # First group should be ANY
        assert rules[0]["expression"]["Type"] == "ANY"
        # Second group should be ALL
        assert rules[1]["expression"]["Type"] == "ALL"


# ---------------------------------------------------------------------------
# Test 5: No demographics -- REQ-05 regression
# ---------------------------------------------------------------------------

class TestNoDemographics:
    """All non-demographic criteria produce unchanged behavior."""

    def test_no_demographics_unchanged(self, service):
        eligibility = {
            "targetCohortName": "T2DM cohort",
            "inclusionCriteria": [
                _condition_criterion(1, "T2DM"),
                _condition_criterion(2, "CVD"),
            ],
            "exclusionCriteria": [],
        }
        result = service._build_seeded_target_circe(eligibility)
        rules = result["InclusionRules"]

        # Should have 2 separate rules (ungrouped conditions)
        assert len(rules) == 2
        for rule in rules:
            assert rule["expression"]["CriteriaList"] != []
            assert rule["expression"]["DemographicCriteriaList"] == []


# ---------------------------------------------------------------------------
# Test 6: Mixed ungrouped + grouped demographics
# ---------------------------------------------------------------------------

class TestMixedUngroupedAndGrouped:
    """REQ-01 + REQ-02: Ungrouped demographics stay separate, grouped ones merge."""

    def test_ungrouped_separate_grouped_merged(self, service):
        eligibility = {
            "targetCohortName": "Complex cohort",
            "inclusionCriteria": [
                _age_criterion(1, op="gte", value=18),  # ungrouped
                _age_criterion(2, op="gte", value=50, group_id="g1", group_type="ANY"),
                _age_criterion(3, op="gte", value=60, group_id="g1", group_type="ANY"),
            ],
            "exclusionCriteria": [],
        }
        result = service._build_seeded_target_circe(eligibility)
        rules = result["InclusionRules"]

        # 1 ungrouped demographic + 1 grouped demographic = 2 rules total
        assert len(rules) == 2

        # First rule: ungrouped age >= 18
        ungrouped = rules[0]
        assert ungrouped["expression"]["DemographicCriteriaList"][0]["Age"]["Value"] == 18

        # Second rule: grouped ANY with two sub-groups
        grouped = rules[1]
        assert grouped["expression"]["Type"] == "ANY"
        assert len(grouped["expression"]["Groups"]) == 2
