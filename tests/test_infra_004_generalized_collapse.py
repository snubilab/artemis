"""SPEC-INFRA-004 AC-001 – AC-008, AC-013: the generalized collapse over real stored criteria.

The negative criteria come first, because they are what the SPEC exists for. `spec.md` §2.3
establishes that broadening `restated_demographics.py`'s domain gate would leave `groupId is
None` as the only thing standing between the collapse and EMPA-REG's Category 2 clusters, and
that grouping state moves between regenerations of identical input. A run that passes AC-001
but fails AC-002 has not implemented this SPEC — it has implemented the unsafe generalization
the SPEC was written to prevent.

AC-006 is the criterion that separates a correct implementation from a plausible one, and it
guards two failure modes in opposite directions. Six survivors means the fix never fired on
the largest single harm in the corpus. **One** survivor means the collapse reduced a stem
group rather than partitioning it, destroying three distinct analytes. Only three is correct.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.restated_distinctness import (
    COLLAPSE_REASON,
    SURVIVOR_RULE,
    WITHHELD_EMPTY_SOURCE_TEXT,
    collapse_all_restated_criteria,
    collapse_restated_criteria,
)
from tests.infra_004_store_fixture import (
    criteria,
    stem_group,
    study_by_nct,
    ungrouped,
)

CAROLINA = "NCT01243424"
EMPA_REG = "NCT01131676"


def _collapse(members: list[dict[str, Any]], role: str = "exclusion"):
    return collapse_restated_criteria(members, role=role)


def _record_ids(records: list[dict[str, Any]]) -> set[str]:
    return {str(i) for r in records for i in ([r["survivorId"]] + list(r["droppedIds"]))}


# --------------------------------------------------------------------------------------
# Negative criteria — verified before the positive ones, per `plan.md` M3.
# --------------------------------------------------------------------------------------


class TestCategoryTwoClustersNeverCollapseAsStored:
    """AC-001. Distinct entities sharing a pipeline-invented category label."""

    @pytest.mark.parametrize(
        "stem,members",
        [
            ("Cardiovascular Disease", 3),
            ("Thyroid Disorders", 2),
            ("Adrenal Disorders", 2),
        ],
    )
    def test_should_emit_no_record_naming_any_member(self, stem, members):
        group = stem_group(study_by_nct(EMPA_REG), "exclusion", "Condition", stem)
        assert len(group) == members
        _, records, _ = _collapse(group)
        assert records == []

    def test_should_leave_every_member_surviving(self):
        group = stem_group(
            study_by_nct(EMPA_REG), "exclusion", "Condition", "Cardiovascular Disease"
        )
        drops, _, _ = _collapse(group)
        assert drops == set()


class TestCardiovascularDiseaseNeverCollapsesWhenUngrouped:
    """AC-002 — the criterion the SPEC exists to satisfy.

    Under a naive domain-gate relaxation the only gate standing between this cluster and a
    first-in-document-order collapse is `groupId is None`. With that gate satisfied,
    `Myocardial Infarction` and `Heart Failure` would be silently and permanently deleted
    while `Hypertension` survived — admitting patients with a history of either into a trial
    that excludes them.
    """

    def test_should_emit_no_record_when_every_member_is_ungrouped(self):
        group = ungrouped(
            stem_group(study_by_nct(EMPA_REG), "exclusion", "Condition", "Cardiovascular Disease")
        )
        assert all(c["groupId"] is None for c in group)
        _, records, _ = _collapse(group)
        assert records == [], [r["stem"] for r in records]

    def test_should_keep_all_three_members(self):
        group = ungrouped(
            stem_group(study_by_nct(EMPA_REG), "exclusion", "Condition", "Cardiovascular Disease")
        )
        drops, _, _ = _collapse(group)
        assert drops == set()

    def test_should_report_the_cluster_as_intact_rather_than_silently_dropping_it(self):
        group = ungrouped(
            stem_group(study_by_nct(EMPA_REG), "exclusion", "Condition", "Cardiovascular Disease")
        )
        _, _, intact = _collapse(group)
        (report,) = [g for g in intact if g["stem"] == "Cardiovascular Disease"]
        assert len(report["classes"]) == 3


class TestThyroidAndAdrenalNeverCollapseWhenUngrouped:
    """AC-003. Held separately from AC-002 because these two share a single `groupId` in the
    stored state while `Cardiovascular Disease` has its own. Their surviving must not depend
    on which of those two shapes they happen to be in."""

    @pytest.mark.parametrize("stem", ["Thyroid Disorders", "Adrenal Disorders"])
    def test_should_emit_no_record_when_ungrouped(self, stem):
        group = ungrouped(stem_group(study_by_nct(EMPA_REG), "exclusion", "Condition", stem))
        drops, records, _ = _collapse(group)
        assert (drops, records) == (set(), [])

    def test_should_keep_all_four_members_across_both_clusters(self):
        study = study_by_nct(EMPA_REG)
        both = ungrouped(
            stem_group(study, "exclusion", "Condition", "Thyroid Disorders")
            + stem_group(study, "exclusion", "Condition", "Adrenal Disorders")
        )
        assert len(both) == 4
        drops, _, _ = _collapse(both)
        assert drops == set()


class TestTheGeneralizedCollapseWithholdsOnEmptySourceText:
    """AC-008 / REQ-004. Refusing to collapse where the discriminating evidence is absent is
    the fail-closed direction: a wrong collapse deletes clinical criteria silently, while a
    missed collapse leaves a defect the report keeps visible."""

    def test_should_not_collapse_two_key_identical_criteria_carrying_no_source_text(self):
        """The constructed case: key-identical under a naive reading."""
        members = [
            {
                "id": id_,
                "description": "Shared stem",
                "sourceText": "",
                "domain": "Condition",
                "valueConstraint": {"op": "gt", "value": 3.0},
                "logicType": "ABSENCE",
                "groupId": None,
                "isGroupLabel": False,
            }
            for id_ in ("1", "2")
        ]
        drops, records, intact = _collapse(members)
        assert (drops, records) == (set(), [])
        assert intact[0]["reason"] == WITHHELD_EMPTY_SOURCE_TEXT

    def test_should_withhold_when_only_one_member_of_a_pair_lacks_source_text(self):
        members = [
            {
                "id": "1",
                "description": "Shared stem",
                "sourceText": "Alanine aminotransferase",
                "domain": "Measurement",
                "valueConstraint": None,
                "logicType": "ABSENCE",
                "groupId": None,
                "isGroupLabel": False,
            },
            {
                "id": "2",
                "description": "Shared stem",
                "sourceText": "",
                "domain": "Measurement",
                "valueConstraint": None,
                "logicType": "ABSENCE",
                "groupId": None,
                "isGroupLabel": False,
            },
        ]
        drops, records, _ = _collapse(members)
        assert (drops, records) == (set(), [])


# --------------------------------------------------------------------------------------
# Positive criteria.
# --------------------------------------------------------------------------------------


class TestAlcoholUseDisorderCollapsesToOne:
    """AC-004. The two members sit in *different* groups, which is incidental and must not be
    load-bearing: the collapse is justified by key equality, and REQ-003 forbids the inverse
    rule ("different groups implies collapsible"), which would be as unsafe as the gate this
    SPEC replaces."""

    def test_should_emit_exactly_one_record_naming_one_survivor_and_one_dropped(self):
        group = stem_group(study_by_nct(CAROLINA), "exclusion", "Condition", "Alcohol Use Disorder")
        _, records, _ = _collapse(group)
        assert len(records) == 1
        assert len(records[0]["droppedIds"]) == 1

    def test_should_not_rest_on_the_two_members_sitting_in_different_groups(self):
        group = stem_group(study_by_nct(CAROLINA), "exclusion", "Condition", "Alcohol Use Disorder")
        assert len({c.get("groupId") for c in group}) == 2, "fixture no longer exercises this"
        _, from_stored, _ = _collapse(group)
        _, from_ungrouped, _ = _collapse(ungrouped(group))
        assert len(from_stored) == len(from_ungrouped) == 1


class TestTheCarolinaSiblingClustersCollapse:
    """AC-005, conditional on Decision Point 1 resolving as recommended (fold in)."""

    @pytest.mark.parametrize(
        "role,domain,stem",
        [
            ("exclusion", "Observation", "Alcohol or drug abuse"),
            ("exclusion", "Condition", "Opioid Use Disorder"),
            ("exclusion", "Condition", "Cannabis Use Disorder"),
            ("exclusion", "Condition", "Cocaine Use Disorder"),
            ("exclusion", "Drug", "Other antidiabetic drugs"),
            ("exclusion", "Drug", "SGLT2 Inhibitors"),
            ("exclusion", "Drug", "DPP-4 Inhibitors"),
            ("exclusion", "Drug", "Thiazolidinediones"),
            ("inclusion", "Demographics", "Age >= 70 years"),
        ],
    )
    def test_should_yield_one_record_and_one_survivor(self, role, domain, stem):
        group = stem_group(study_by_nct(CAROLINA), role, domain, stem)
        _, records, _ = collapse_restated_criteria(group, role=role)
        assert len(records) == 1
        assert len(records[0]["droppedIds"]) == len(group) - 1

    def test_should_yield_one_survivor_and_two_dropped_for_the_three_member_glp_one_cluster(self):
        group = stem_group(study_by_nct(CAROLINA), "exclusion", "Drug", "GLP-1 Receptor Agonists")
        assert len(group) == 3
        _, records, _ = _collapse(group)
        assert len(records) == 1
        assert len(records[0]["droppedIds"]) == 2


class TestTheLiverDiseaseGroupYieldsExactlyThreeSurvivors:
    """AC-006 — the sharpest test of the design.

    Six criteria where three are correct: EMPA-REG's ALT / AST / ALP triple emitted twice.
    All six carry `valueConstraint` non-null, placing them entirely outside
    `SPEC-INFRA-003`'s gate 2, and collapsing them to one survivor would re-create precisely
    the regression `SPEC-INFRA-003` `AC-004` exists to prevent.
    """

    def _group(self) -> list[dict[str, Any]]:
        return stem_group(study_by_nct(EMPA_REG), "exclusion", "Measurement", "Liver disease")

    def test_should_start_from_six_stored_members(self):
        assert len(self._group()) == 6

    def test_should_emit_exactly_three_records_one_per_analyte_pair(self):
        _, records, _ = _collapse(self._group())
        assert len(records) == 3, [r["distinctnessKey"]["sourceText"] for r in records]

    def test_should_leave_exactly_three_survivors(self):
        group = self._group()
        drops, records, _ = _collapse(group)
        survivors = [c for c in group if (("exclusion", str(c["id"])) not in drops)]
        assert len(survivors) == 3, [c["sourceText"] for c in survivors]
        assert len(drops) == 3

    def test_should_keep_one_survivor_per_analyte_never_merging_across_analytes(self):
        group = self._group()
        drops, _, _ = _collapse(group)
        survivors = [c for c in group if (("exclusion", str(c["id"])) not in drops)]
        assert sorted(c["sourceText"] for c in survivors) == [
            "Alanine aminotransferase",
            "Alkaline phosphatase",
            "Aspartate aminotransferase",
        ]

    def test_should_yield_three_survivors_on_a_constructed_interleaved_fixture(self):
        """AC-006's second clause. The `Liver disease` group is currently the corpus's only
        multi-class partition, and `plan.md` §G names the hazard of resting a count claim on
        a single regeneration — a future store in which the triple emits once would reduce
        this criterion to a no-op while still reporting PASS.

        Interleaved document order is deliberate: an implementation that partitions correctly
        but selects survivors by scanning adjacent runs passes an adjacent-order fixture and
        fails this one.
        """
        constraint = {"op": "gt", "value": 3.0, "unitText": "x ULN"}
        members = [
            {
                "id": str(i),
                "description": "Liver disease (constructed)",
                "sourceText": analyte,
                "domain": "Measurement",
                "valueConstraint": constraint,
                "logicType": "ABSENCE",
                "groupId": None,
                "isGroupLabel": False,
            }
            for i, analyte in enumerate(["ALT", "AST", "ALP", "ALT", "AST", "ALP"], start=1)
        ]
        drops, records, _ = _collapse(members)
        survivors = [c for c in members if ("exclusion", c["id"]) not in drops]
        assert len(records) == 3
        assert len(survivors) == 3
        assert [c["id"] for c in survivors] == ["1", "2", "3"], (
            "each survivor must be its class's first member in document order"
        )


class TestCollapseRecordsCarryTheFullDecision:
    """AC-013. Sufficient to reconstruct why the collapse fired without re-running it."""

    def test_should_carry_every_field_the_criterion_names(self):
        group = stem_group(study_by_nct(CAROLINA), "exclusion", "Condition", "Alcohol Use Disorder")
        _, (record,), _ = _collapse(group)
        assert set(record) == {
            "role",
            "domain",
            "stem",
            "distinctnessKey",
            "survivorId",
            "droppedIds",
            "survivorRule",
            "reason",
        }
        assert record["survivorRule"] == SURVIVOR_RULE
        assert record["reason"] == COLLAPSE_REASON

    def test_should_select_the_survivor_first_in_document_order_not_by_id_value(self):
        """REQ-005's first clause, verified against the **input sequence** rather than
        against the declared `survivorRule` string.

        An implementation selecting the last member, or the lowest-valued id, while still
        emitting `survivorRule: "first-in-document-order"` satisfied every other criterion in
        the SPEC. Here the input is deliberately ordered so document order and id order
        disagree, so only a document-order implementation passes.
        """
        members = [
            {
                "id": id_,
                "description": "Shared stem",
                "sourceText": "Same entity",
                "domain": "Condition",
                "valueConstraint": None,
                "logicType": "ABSENCE",
                "groupId": None,
                "isGroupLabel": False,
            }
            for id_ in ("90", "12", "45")
        ]
        _, (record,), _ = _collapse(members)
        assert record["survivorId"] == "90"
        assert sorted(record["droppedIds"]) == ["12", "45"]

    def test_should_name_survivor_ten_and_dropped_twenty_eight_and_thirty_four_for_glp_one(self):
        """AC-013's third clause, on the named three-member fixture. The expected survivor is
        recomputed from the input sequence rather than assumed from the id values, so a store
        emitting them in a different order still asserts document order."""
        group = stem_group(study_by_nct(CAROLINA), "exclusion", "Drug", "GLP-1 Receptor Agonists")
        expected_survivor = group[0]["id"]
        expected_dropped = sorted(str(c["id"]) for c in group[1:])
        _, (record,), _ = _collapse(group)
        assert record["survivorId"] == expected_survivor
        assert sorted(str(i) for i in record["droppedIds"]) == expected_dropped
        assert (str(expected_survivor), expected_dropped) == ("10", ["28", "34"]), (
            "the reference store's document order no longer matches acceptance.md's fixture"
        )


class TestBothRolesAreCollapsedIndependently:
    def test_should_never_collapse_across_roles(self):
        shared = {
            "description": "Shared stem",
            "sourceText": "Same entity",
            "domain": "Condition",
            "valueConstraint": None,
            "logicType": "ABSENCE",
            "groupId": None,
            "isGroupLabel": False,
        }
        drops, records, _ = collapse_all_restated_criteria(
            inclusion_criteria=[{**shared, "id": "1"}],
            exclusion_criteria=[{**shared, "id": "2"}],
        )
        assert (drops, records) == (set(), [])

    def test_should_key_drops_by_role_so_equal_ids_in_two_roles_do_not_collide(self):
        carolina = study_by_nct(CAROLINA)
        drops, _, _ = collapse_all_restated_criteria(
            inclusion_criteria=criteria(carolina, "inclusion"),
            exclusion_criteria=criteria(carolina, "exclusion"),
        )
        assert all(isinstance(k, tuple) and k[0] in ("inclusion", "exclusion") for k in drops)
        assert any(k[0] == "inclusion" for k in drops)
        assert any(k[0] == "exclusion" for k in drops)
