"""SPEC-INFRA-003 REQ-004: a grouped exclusion means absence from the union.

Exclusion criteria are emitted with `Occurrence {Type: 0, Count: 0}` -- "exactly zero
occurrences". CIRCE AND-combines top-level `InclusionRules`, so N separate ABSENCE rules
mean *absent from A and absent from B and absent from C*, which by De Morgan is **absent
from the union**. That is what a protocol sentence listing OR'd exclusion conditions
actually asks for.

Grouping does not preserve it. `_build_grouped_inclusion_rule` wrote `"Type": group_type`
verbatim from the value read at the call site, with no exclusion-side inversion, so a
group of ABSENCE criteria typed `ANY` meant *at least one is absent* -- **absent from the
intersection**, strictly looser than the protocol states. A person matching only A was
retained by a rule that should have excluded them.

This is an active defect rather than a prospective risk: `spec.md` §2.3.1 counted 18 such
group instances in the reference store, group sizes 3 to 17.

The fix inverts `ANY` to `ALL` when every contributing member carries
`logicType: "ABSENCE"`, which reproduces the semantics of the equivalent separate
top-level rules -- the bar REQ-004 states. It is applied where the type is written rather
than where it is read, so the single writer stays the single point of truth and the
demographic-only call site is covered by the same change.

Direction matters both ways, so both are asserted: `TestPresenceGroupsUnchanged`
(AC-012) guards the inclusion side, which must not move.

**Fixture provenance.** These fixtures reproduce the criterion field shape documented in
`spec.md` §2.1 and follow the construction pattern in
`tests/test_infra_002_demographics_grouping.py`. They are not the reference store; the
18 live instances there are counted from the container and are out of scope here.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers -- field shape per spec.md §2.1
# ---------------------------------------------------------------------------

def _criterion(
    *,
    id: int,
    description: str,
    domain: str = "Condition",
    logic_type: str = "ABSENCE",
    group_id: str | None = None,
    group_type: str = "ALL",
    value_constraint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a top-level IR criterion.

    Args:
        id: Criterion id, unique within a (study, role) scope.
        description: The criterion's paraphrased description.
        domain: OMOP-ish domain label; non-demographic by default so the criterion
            takes the concept-set mapping path rather than the demographic one.
        logic_type: "PRESENCE" or "ABSENCE".
        group_id: Non-null puts the criterion in a group.
        group_type: CIRCE group type as agent1 declared it, "ALL" or "ANY".
        value_constraint: `{op, value}` when the criterion carries one.

    Returns:
        A criterion dict.
    """
    crit: dict[str, Any] = {
        "id": id,
        "description": description,
        "domain": domain,
        "groupId": group_id,
        "groupType": group_type,
        "logicType": logic_type,
    }
    if value_constraint:
        crit["valueConstraint"] = value_constraint
    return crit


def _age_criterion(
    id: int, *, op: str, value: int, logic_type: str, group_id: str, group_type: str,
) -> dict[str, Any]:
    return _criterion(
        id=id,
        description=f"Age {op} {value}",
        domain="Demographics",
        logic_type=logic_type,
        group_id=group_id,
        group_type=group_type,
        value_constraint={"op": op, "value": value},
    )


def _stub_recommend(name: str, expected_domain: str | None = None, workflow=None, **kwargs):
    """Return a minimal concept-set recommendation stub."""
    return {
        "name": name,
        "domain": "Condition",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 99999}}]},
    }


def _stub_eligibility_rule(criterion, *, codeset_id, exclusion):
    """Return a minimal eligibility-rule result stub carrying the exclusion Occurrence."""
    label = criterion.get("description", "rule")
    absent = exclusion or criterion.get("logicType") == "ABSENCE"
    return {
        "conceptSet": {"id": codeset_id, "name": label, "expression": {"items": []}},
        "rule": {
            "name": label,
            "expression": {
                "Type": "ALL",
                "CriteriaList": [{
                    "Criteria": {"ConditionOccurrence": {"CodesetId": codeset_id}},
                    "Occurrence": {"Type": 0, "Count": 0} if absent else {"Type": 2, "Count": 1},
                }],
                "DemographicCriteriaList": [],
                "Groups": [],
            },
        },
    }


@pytest.fixture
def service():
    """A TTEService with the expensive Agent2 / vector-search methods stubbed out."""
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = MagicMock(side_effect=_stub_recommend)
    svc._build_seeded_eligibility_rule = MagicMock(side_effect=lambda **kw: _stub_eligibility_rule(
        kw["criterion"], codeset_id=kw["codeset_id"], exclusion=kw["exclusion"],
    ))
    svc._seeded_primary_criteria_key = MagicMock(return_value="ConditionOccurrence")
    svc._patch_codeset_id_in_rule = MagicMock()
    return svc


def _grouped_rule(result: dict[str, Any]) -> dict[str, Any]:
    """Return the single InclusionRule a one-group eligibility shell produced."""
    rules = result["InclusionRules"]
    assert len(rules) == 1, f"expected exactly one grouped rule, got {len(rules)}"
    return rules[0]


def _absence_group(group_type: str) -> dict[str, Any]:
    """An eligibility shell holding one all-ABSENCE exclusion group."""
    return {
        "targetCohortName": "T2DM cohort",
        "inclusionCriteria": [],
        "exclusionCriteria": [
            _criterion(id=1, description="Alcohol Use Disorder", logic_type="ABSENCE",
                       group_id="g1", group_type=group_type),
            _criterion(id=2, description="Opioid Use Disorder", logic_type="ABSENCE",
                       group_id="g1", group_type=group_type),
        ],
    }


# ---------------------------------------------------------------------------
# Characterization: behavior that must be preserved
# ---------------------------------------------------------------------------

class TestCharacterizeGroupGeometry:
    """SPEC-INFRA-002 owns the Groups[] merge. REQ-004 must not disturb it."""

    def test_characterize_absence_group_keeps_one_group_entry_per_member(self, service):
        rule = _grouped_rule(service._build_seeded_target_circe(_absence_group("ANY")))
        expr = rule["expression"]

        assert len(expr["Groups"]) == 2
        assert expr["CriteriaList"] == []
        assert expr["DemographicCriteriaList"] == []
        for group in expr["Groups"]:
            assert group["Type"] == "ALL"
            assert len(group["CriteriaList"]) == 1

    def test_characterize_absence_members_keep_the_zero_occurrence_axis(self, service):
        rule = _grouped_rule(service._build_seeded_target_circe(_absence_group("ANY")))

        occurrences = [
            entry["Occurrence"]
            for group in rule["expression"]["Groups"]
            for entry in group["CriteriaList"]
        ]
        # "exactly zero occurrences" -- the axis the De Morgan argument rests on.
        assert occurrences == [{"Type": 0, "Count": 0}, {"Type": 0, "Count": 0}]

    def test_characterize_group_label_joins_member_descriptions(self, service):
        rule = _grouped_rule(service._build_seeded_target_circe(_absence_group("ANY")))

        assert rule["name"] == "Alcohol Use Disorder + Opioid Use Disorder"


class TestPresenceGroupsUnchanged:
    """AC-012: grouped inclusion semantics are untouched."""

    def test_should_keep_any_when_grouped_members_carry_presence(self, service):
        eligibility = {
            "targetCohortName": "CV cohort",
            "inclusionCriteria": [
                _criterion(id=1, description="Prior MI", logic_type="PRESENCE",
                           group_id="g1", group_type="ANY"),
                _criterion(id=2, description="Prior stroke", logic_type="PRESENCE",
                           group_id="g1", group_type="ANY"),
            ],
            "exclusionCriteria": [],
        }

        rule = _grouped_rule(service._build_seeded_target_circe(eligibility))

        assert rule["expression"]["Type"] == "ANY"

    def test_should_keep_any_when_a_group_mixes_presence_and_absence(self, service):
        # The predicate is "members **all** carry ABSENCE". One PRESENCE member and
        # the De Morgan argument no longer applies to the group as a whole.
        eligibility = {
            "targetCohortName": "CV cohort",
            "inclusionCriteria": [
                _criterion(id=1, description="Prior MI", logic_type="PRESENCE",
                           group_id="g1", group_type="ANY"),
                _criterion(id=2, description="No prior stroke", logic_type="ABSENCE",
                           group_id="g1", group_type="ANY"),
            ],
            "exclusionCriteria": [],
        }

        rule = _grouped_rule(service._build_seeded_target_circe(eligibility))

        assert rule["expression"]["Type"] == "ANY"

    def test_should_keep_any_for_a_grouped_presence_demographic_group(self, service):
        # Guards tests/test_infra_002_demographics_grouping.py TestGroupedDemographics
        # from this side too: a demographic group that never declared ABSENCE keeps
        # its declared type.
        eligibility = {
            "targetCohortName": "CV cohort",
            "inclusionCriteria": [
                _age_criterion(1, op="gte", value=50, logic_type="PRESENCE",
                               group_id="g1", group_type="ANY"),
                _age_criterion(2, op="gte", value=60, logic_type="PRESENCE",
                               group_id="g1", group_type="ANY"),
            ],
            "exclusionCriteria": [],
        }

        rule = _grouped_rule(service._build_seeded_target_circe(eligibility))

        assert rule["expression"]["Type"] == "ANY"


# ---------------------------------------------------------------------------
# REQ-004: the behavior that changes
# ---------------------------------------------------------------------------

class TestAbsenceGroupsMeanAbsenceFromTheUnion:
    """AC-011: a person matching only one member's set is excluded by the rule."""

    def test_should_and_combine_when_every_grouped_member_carries_absence(self, service):
        # ANY over two "exactly zero occurrences" members means "at least one is
        # absent" -- absent from the intersection, so a person matching only A
        # survives. ALL is what reproduces two equivalent separate top-level rules.
        rule = _grouped_rule(service._build_seeded_target_circe(_absence_group("ANY")))

        assert rule["expression"]["Type"] == "ALL"

    def test_should_leave_an_all_typed_absence_group_alone(self, service):
        # Already correct. Nothing to invert, and nothing to flip back.
        rule = _grouped_rule(service._build_seeded_target_circe(_absence_group("ALL")))

        assert rule["expression"]["Type"] == "ALL"

    def test_should_and_combine_a_demographic_only_absence_group(self, service):
        # The demographic path inverts the operator instead of the Occurrence axis,
        # so "Age < 18" excluded becomes "Age >= 18". Separate top-level rules would
        # still AND those, which is the bar REQ-004 states, so the same inversion
        # applies. Reached through the same writer, not a second code path.
        eligibility = {
            "targetCohortName": "T2DM cohort",
            "inclusionCriteria": [],
            "exclusionCriteria": [
                _age_criterion(1, op="lt", value=18, logic_type="ABSENCE",
                               group_id="g1", group_type="ANY"),
                _age_criterion(2, op="gt", value=80, logic_type="ABSENCE",
                               group_id="g1", group_type="ANY"),
            ],
        }

        rule = _grouped_rule(service._build_seeded_target_circe(eligibility))

        assert rule["expression"]["Type"] == "ALL"


class TestEffectiveGroupTypeUnit:
    """The predicate on its own, away from the mapping pipeline."""

    def test_should_return_all_when_every_member_is_absence_and_type_is_any(self):
        from src.services.tte_service import _effective_group_type

        members = [{"logicType": "ABSENCE"}, {"logicType": "ABSENCE"}]
        assert _effective_group_type("ANY", members) == "ALL"

    def test_should_return_the_declared_type_when_no_member_survived(self):
        from src.services.tte_service import _effective_group_type

        # Vacuous truth would flip an empty group; an empty group has no union to be
        # absent from, so the declared type stands.
        assert _effective_group_type("ANY", []) == "ANY"

    def test_should_return_the_declared_type_when_a_member_is_not_absence(self):
        from src.services.tte_service import _effective_group_type

        members = [{"logicType": "ABSENCE"}, {"logicType": "PRESENCE"}]
        assert _effective_group_type("ANY", members) == "ANY"

    def test_should_return_the_declared_type_when_logic_type_is_missing(self):
        from src.services.tte_service import _effective_group_type

        # An absent logicType is not evidence of ABSENCE. Failing to invert leaves the
        # pre-existing behavior in place; inverting on a guess would change a group
        # nobody established anything about.
        assert _effective_group_type("ANY", [{}, {}]) == "ANY"

    def test_should_ignore_case_and_padding_when_reading_the_declared_type(self):
        from src.services.tte_service import _effective_group_type

        members = [{"logicType": "absence"}, {"logicType": " ABSENCE "}]
        assert _effective_group_type(" any ", members) == "ALL"
