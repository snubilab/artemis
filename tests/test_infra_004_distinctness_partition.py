"""SPEC-INFRA-004 M2: the distinctness key and the per-class partition.

This file tests the *measurement* — the key, the partition, and the per-group verdict —
independently of any collapse decision. `plan.md` §F orders it before M3 so the fix has a
measurement to move.

The load-bearing property is that the partition is **per class, never per group**
(`plan.md` B-3). A group holding N distinct classes yields N survivors. Reducing a group
to one survivor is the single most likely implementation error, and it re-creates exactly
the regression `SPEC-INFRA-003` `AC-004` exists to prevent.
"""
from __future__ import annotations

from typing import Any

from src.services.restated_distinctness import (
    WITHHELD_DEMOGRAPHICS_PATH,
    WITHHELD_EMPTY_SOURCE_TEXT,
    WITHHELD_KEY_DISTINCT,
    analyze_restated_groups,
    distinctness_key,
    partition_by_distinctness,
)


def _criterion(
    id: Any,
    *,
    description: str,
    source_text: str = "",
    domain: str = "Condition",
    value_constraint: dict[str, Any] | None = None,
    logic_type: str = "ABSENCE",
    group_id: str | None = None,
    is_group_label: bool = False,
) -> dict[str, Any]:
    return {
        "id": id,
        "description": description,
        "sourceText": source_text,
        "domain": domain,
        "valueConstraint": value_constraint,
        "logicType": logic_type,
        "groupId": group_id,
        "isGroupLabel": is_group_label,
    }


class TestTheDistinctnessKey:
    def test_should_key_on_source_text_constraint_and_logic_type(self):
        key = distinctness_key(
            _criterion(
                "1",
                description="d",
                source_text="Alanine aminotransferase",
                value_constraint={"op": "gt", "value": 3.0},
                logic_type="ABSENCE",
            )
        )
        assert key[0] == "Alanine aminotransferase"
        assert key[2] == "ABSENCE"

    def test_should_treat_two_identical_criteria_as_one_class(self):
        members = [
            _criterion("1", description="Alcohol Use Disorder", source_text="Alcohol Use Disorder"),
            _criterion("2", description="Alcohol Use Disorder", source_text="Alcohol Use Disorder"),
        ]
        assert len(partition_by_distinctness(members)) == 1

    def test_should_separate_members_whose_source_text_differs(self):
        """REQ-002: what protects every Category 2 cluster."""
        members = [
            _criterion("1", description="Cardiovascular Disease", source_text="Hypertension"),
            _criterion(
                "2", description="Cardiovascular Disease", source_text="Myocardial Infarction"
            ),
        ]
        assert len(partition_by_distinctness(members)) == 2

    def test_should_separate_members_whose_constraint_differs_only_in_unit_concept_id(self):
        """Decision Point 2, resolved as recommended: strict equality, no normalization.

        EMPA-REG `eGFR` {41,42} is the corpus instance. Normalizing `unitConceptId` away
        would collapse them; strict equality leaves them intact and reported.
        """
        members = [
            _criterion(
                "41",
                description="eGFR < 30",
                source_text="Estimated glomerular filtration rate",
                value_constraint={"op": "lt", "value": 30.0, "unitConceptId": 720870},
            ),
            _criterion(
                "42",
                description="eGFR < 30",
                source_text="Estimated glomerular filtration rate",
                value_constraint={"op": "lt", "value": 30.0, "unitConceptId": None},
            ),
        ]
        assert len(partition_by_distinctness(members)) == 2

    def test_should_not_depend_on_key_ordering_within_the_constraint(self):
        """Two constraints equal as mappings are one class however their keys are ordered."""
        members = [
            _criterion(
                "1", description="d", source_text="s", value_constraint={"op": "gt", "value": 3.0}
            ),
            _criterion(
                "2", description="d", source_text="s", value_constraint={"value": 3.0, "op": "gt"}
            ),
        ]
        assert len(partition_by_distinctness(members)) == 1

    def test_should_preserve_document_order_within_each_class(self):
        """REQ-005 depends on this: the survivor is the class's first member."""
        members = [
            _criterion("10", description="d", source_text="A"),
            _criterion("28", description="d", source_text="A"),
            _criterion("34", description="d", source_text="A"),
        ]
        (only_class,) = partition_by_distinctness(members).values()
        assert [c["id"] for c in only_class] == ["10", "28", "34"]


class TestTheGroupAnalysis:
    def test_should_group_by_domain_and_stem(self):
        groups = analyze_restated_groups(
            [
                _criterion("1", description="Liver disease (ALT)", source_text="A"),
                _criterion("2", description="Liver disease (AST)", source_text="B"),
                _criterion("3", description="Unrelated", source_text="C"),
            ],
            role="exclusion",
        )
        assert len(groups) == 1
        assert groups[0]["stem"] == "Liver disease"
        assert groups[0]["criterionIds"] == ["1", "2"]

    def test_should_never_group_one_stem_across_two_domains(self):
        groups = analyze_restated_groups(
            [
                _criterion("1", description="Shared", source_text="A", domain="Condition"),
                _criterion("2", description="Shared", source_text="A", domain="Drug"),
            ],
            role="exclusion",
        )
        assert groups == []

    def test_should_not_report_a_singleton_group(self):
        groups = analyze_restated_groups(
            [_criterion("1", description="Alone", source_text="A")], role="exclusion"
        )
        assert groups == []

    def test_should_partition_an_interleaved_six_member_group_into_three_classes(self):
        """AC-006's constructed fixture, at the partition layer.

        Class membership is interleaved rather than adjacent: an implementation that
        scans adjacent runs passes an adjacent-order fixture and fails this one.
        """
        members = [
            _criterion("1", description="Liver disease", source_text="ALT"),
            _criterion("2", description="Liver disease", source_text="AST"),
            _criterion("3", description="Liver disease", source_text="ALP"),
            _criterion("4", description="Liver disease", source_text="ALT"),
            _criterion("5", description="Liver disease", source_text="AST"),
            _criterion("6", description="Liver disease", source_text="ALP"),
        ]
        (group,) = analyze_restated_groups(members, role="exclusion")
        assert group["collapses"] is True
        assert [cls["survivorId"] for cls in group["classes"] if len(cls["criterionIds"]) >= 2] == [
            "1",
            "2",
            "3",
        ]


class TestTheWithheldReason:
    def test_should_report_key_distinct_when_every_class_is_a_singleton(self):
        (group,) = analyze_restated_groups(
            [
                _criterion(
                    "13", description="Cardiovascular Disease", source_text="Hypertension"
                ),
                _criterion(
                    "14", description="Cardiovascular Disease", source_text="Myocardial Infarction"
                ),
            ],
            role="exclusion",
        )
        assert group["collapses"] is False
        assert group["reason"] == WITHHELD_KEY_DISTINCT

    def test_should_report_empty_source_text_when_a_class_of_two_is_withheld(self):
        """REQ-004 / AC-008's constructed case: key-identical under a naive reading."""
        (group,) = analyze_restated_groups(
            [
                _criterion("1", description="Shared", source_text=""),
                _criterion("2", description="Shared", source_text=""),
            ],
            role="exclusion",
        )
        assert group["collapses"] is False
        assert group["reason"] == WITHHELD_EMPTY_SOURCE_TEXT

    def test_should_prefer_key_distinct_over_empty_source_text_where_both_apply(self):
        """`spec.md` §2.6.1 precedence, and AC-007 asserts it on CARMELINA {1,2,3} / {10,11}.

        `key-distinct` is the store-independent ground: it survives the `sourceText`
        population that `empty-sourceText` does not.
        """
        (group,) = analyze_restated_groups(
            [
                _criterion(
                    "1",
                    description="Age",
                    source_text="",
                    value_constraint={"op": "gte", "value": 18},
                ),
                _criterion(
                    "2",
                    description="Age",
                    source_text="",
                    value_constraint={"op": "gte", "value": 40},
                ),
            ],
            role="exclusion",
        )
        assert group["collapses"] is False
        assert group["reason"] == WITHHELD_KEY_DISTINCT

    def test_should_report_demographics_path_when_the_gate_admits_fewer_than_two(self):
        """REQ-013: the group is the other path's territory, not this path's failure."""
        (group,) = analyze_restated_groups(
            [
                _criterion("14", description="Pregnancy", source_text="", domain="Demographics"),
                _criterion("23", description="Pregnancy", source_text="", domain="Demographics"),
            ],
            role="exclusion",
        )
        assert group["collapses"] is False
        assert group["reason"] == WITHHELD_DEMOGRAPHICS_PATH


class TestTheReqThirteenGate:
    def test_should_exclude_criteria_the_demographics_predicate_claims(self):
        """Gate on the predicate, never on the domain — `plan.md` §G."""
        groups = analyze_restated_groups(
            [
                _criterion("1", description="Pregnancy", source_text="x", domain="Demographics"),
                _criterion("2", description="Pregnancy", source_text="x", domain="Demographics"),
            ],
            role="exclusion",
        )
        assert groups[0]["collapses"] is False

    def test_should_admit_a_demographics_criterion_the_predicate_rejects(self):
        """CAROLINA inclusion `Age >= 70 years` {4,33}: Demographics, but constrained.

        A `domain != "Demographics"` gate would orphan this genuine duplicate — the
        Demographics path rejects it on gate 2 and the generalized path would never see
        it. This is AC-016 fixture 3 at the analysis layer.
        """
        constrained = {"op": "gte", "value": 70}
        (group,) = analyze_restated_groups(
            [
                _criterion(
                    "4",
                    description="Age >= 70 years",
                    source_text="Age",
                    domain="Demographics",
                    value_constraint=constrained,
                ),
                _criterion(
                    "33",
                    description="Age >= 70 years",
                    source_text="Age",
                    domain="Demographics",
                    value_constraint=constrained,
                ),
            ],
            role="exclusion",
        )
        assert group["collapses"] is True
