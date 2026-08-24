"""SPEC-INFRA-003 REQ-001 / REQ-007: collapse restated demographics to one criterion.

The §2.5 stem signal (`restated_clusters.py`) *measures* duplication. It cannot fix
EMPA-REG, whose pair shares no stem -- `spec.md` §2.5.2 records that as its one known
false negative. This module supplies a second, independent signal that does not read
descriptions at all.

**The signal: restated-demographics collapse.** Within one study and one role, among
top-level criteria satisfying all four structural gates

1. `domain == "Demographics"`, **and**
2. `valueConstraint is None`, **and**
3. `groupId is None`, **and**
4. `isGroupLabel` falsy

-- if two or more such criteria exist, they collapse to exactly one survivor: the first
in document order.

**Why this is a cardinality invariant, not a similarity match.** It never compares two
descriptions. A Demographics criterion carrying no numeric constraint has no attribute
to bind two different facts to, so two of them in the same (study, role) are restating
one fact *by construction*, however differently they are worded. That is what lets this
reach EMPA-REG {27, 28} -- `Pre-menopausal women criteria` and `Pre-menopausal women
contraception/pregnancy status` share no stem, and the stem signal correctly abstains,
but the cardinality argument does not depend on their wording.

`plan.md` §G forbids deduping on description similarity, and this does not: there is no
threshold, no edit distance, no embedding, and no id or study special case. Gate 2 is
still the load-bearing one -- CARMELINA's ALT/AST/AP triple each carry
`{op: gte, value: 3.0, unitText: "x ULN"}` bound to a different named analyte, so gate 2
excludes them without judgment, and gate 1 excludes them a second time over
(`domain: Measurement`). AC-004 is guarded here explicitly rather than reasoned about.

**Fixture provenance.** Field shapes and the three firing groups reproduce the live
reference store `tmp/tte_six_20260823_patternG_v2/studies.json`, scanned over all
10 studies / 506 criteria: exactly three (study, role) groups reach
n >= 2 -- CARMELINA exclusion {11, 12, 18}, CAROLINA exclusion {21, 53}, and EMPA-REG
exclusion {27, 28}. Every other group in the gated class is a singleton. These are
synthetic reconstructions of that shape, not the store itself.
"""
from __future__ import annotations

from typing import Any

from src.services.restated_demographics import (
    collapse_all_restated_demographics,
    is_restatable_demographic,
)

# ---------------------------------------------------------------------------
# Fixture helpers -- field shape per spec.md §2.1
# ---------------------------------------------------------------------------


def _criterion(
    *,
    id: int,
    description: str,
    domain: str = "Demographics",
    value_constraint: dict[str, Any] | None = None,
    group_id: str | None = None,
    is_group_label: bool = False,
) -> dict[str, Any]:
    return {
        "id": id,
        "description": description,
        "domain": domain,
        "valueConstraint": value_constraint,
        "groupId": group_id,
        "groupType": "ALL",
        "logicType": "ABSENCE",
        "isGroupLabel": is_group_label,
        "sourceText": "",
    }


# The three groups that fire on the reference store.
CARMELINA_PREGNANCY = [
    _criterion(id=11, description="Pregnancy/Nursing/Uncontrolled Contraception"),
    _criterion(id=12, description="Pregnancy/Nursing/Uncontrolled Contraception (<= 1 year)"),
    _criterion(id=18, description="Pregnancy/Nursing/Uncontrolled Contraception (General)"),
]

CAROLINA_PREGNANCY = [
    _criterion(id=21, description="Pre-menopausal women/Nursing/Pregnant/Not using contraception"),
    _criterion(id=53, description="Pre-menopausal women/Nursing/Pregnant/Not using contraception"),
]

# The stem signal's known false negative (`spec.md` §2.5.2): no shared stem, so it
# forms no cluster there. The cardinality signal does not read the descriptions.
EMPA_REG_PREGNANCY = [
    _criterion(id=27, description="Pre-menopausal women criteria"),
    _criterion(id=28, description="Pre-menopausal women contraception/pregnancy status"),
]

# CARMELINA exclusion ids 1, 2, 3 verbatim from the reference store: domain
# Measurement, groupId None, each carrying the same threshold bound to a different
# named analyte. AC-004's negative case.
ALT_AST_AP = [
    _criterion(
        id=1,
        description="Active Liver Disease/Impaired Hepatic Function",
        domain="Measurement",
        value_constraint={"op": "gte", "value": 3.0, "unitText": "x ULN"},
    ),
    _criterion(
        id=2,
        description="Active Liver Disease/Impaired Hepatic Function (AST)",
        domain="Measurement",
        value_constraint={"op": "gte", "value": 3.0, "unitText": "x ULN"},
    ),
    _criterion(
        id=3,
        description="Active Liver Disease/Impaired Hepatic Function (AP)",
        domain="Measurement",
        value_constraint={"op": "gte", "value": 3.0, "unitText": "x ULN"},
    ),
]


class TestTheFourGates:
    def test_should_admit_a_demographics_criterion_carrying_none_of_the_disqualifiers(self):
        assert is_restatable_demographic(_criterion(id=11, description="Pregnancy")) is True

    def test_should_reject_a_non_demographics_domain(self):
        """Gate 1. Domain alone excludes the Measurement triple."""
        assert (
            is_restatable_demographic(
                _criterion(id=4, description="Acute Coronary Syndrome", domain="Condition")
            )
            is False
        )

    def test_should_reject_a_criterion_carrying_a_value_constraint(self):
        """Gate 2, the load-bearing one.

        A numeric constraint is an attribute two different facts can bind to, so the
        cardinality argument does not apply. This is what keeps ALT/AST/AP out, and it
        is independent of domain -- a future constrained Demographics criterion (an age
        band, say) is excluded by the same gate.
        """
        assert (
            is_restatable_demographic(
                _criterion(
                    id=2,
                    description="Age >= 50",
                    value_constraint={"op": "gte", "value": 50.0},
                )
            )
            is False
        )

    def test_should_reject_a_grouped_criterion(self):
        """Gate 3. A criterion inside a group is the group's business, not this signal's."""
        assert (
            is_restatable_demographic(
                _criterion(id=7, description="Age and risk factors", group_id="abc-123")
            )
            is False
        )

    def test_should_reject_a_group_label(self):
        """Gate 4. A heading declared as one states no condition of its own."""
        assert (
            is_restatable_demographic(
                _criterion(id=1, description="Age (region-conditional)", is_group_label=True)
            )
            is False
        )

    def test_should_treat_an_absent_value_constraint_key_as_null(self):
        """An absent key and an explicit null are the same thing here."""
        bare = {"id": 11, "description": "Pregnancy", "domain": "Demographics"}
        assert is_restatable_demographic(bare) is True


class TestCollapseFiresOnTheVerifiedGroups:
    def test_should_collapse_carmelina_three_to_one_survivor(self):
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[], exclusion_criteria=CARMELINA_PREGNANCY
        )
        assert drop_keys == {("exclusion", "12"), ("exclusion", "18")}
        assert len(records) == 1
        assert records[0]["survivorId"] == 11
        assert records[0]["droppedIds"] == [12, 18]
        assert records[0]["role"] == "exclusion"
        assert records[0]["domain"] == "Demographics"

    def test_should_collapse_carolina_byte_identical_pair(self):
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[], exclusion_criteria=CAROLINA_PREGNANCY
        )
        assert drop_keys == {("exclusion", "53")}
        assert records[0]["survivorId"] == 21

    def test_should_collapse_empa_reg_which_the_stem_signal_cannot_reach(self):
        """`spec.md` §2.5.2's known false negative.

        The two descriptions share no stem, so `detect_restated_clusters` reports
        nothing for them. The cardinality invariant does not read descriptions, so it
        reaches this pair -- the whole reason this second signal exists.
        """
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[], exclusion_criteria=EMPA_REG_PREGNANCY
        )
        assert len(records) == 1
        assert len(drop_keys) == 1
        assert records[0]["survivorId"] == 27
        assert records[0]["droppedIds"] == [28]

    def test_should_keep_the_first_in_document_order_regardless_of_input_id_order(self):
        """Survivor selection is positional, not by id value -- no sort, no scoring."""
        reversed_order = [
            _criterion(id=18, description="Pregnancy/Nursing/Uncontrolled Contraception (General)"),
            _criterion(id=11, description="Pregnancy/Nursing/Uncontrolled Contraception"),
        ]
        _drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[], exclusion_criteria=reversed_order
        )
        assert records[0]["survivorId"] == 18
        assert records[0]["droppedIds"] == [11]

    def test_should_record_the_survivor_rule_so_the_choice_is_visible_in_the_artifact(self):
        _drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[], exclusion_criteria=CAROLINA_PREGNANCY
        )
        assert records[0]["survivorRule"] == "first-in-document-order"


class TestCollapseDoesNotFire:
    def test_should_not_collapse_a_single_such_criterion(self):
        """n = 1 is not a duplication. EMPA-REG's inclusion side is exactly this shape."""
        lone = _criterion(id=15, description="Patient status and therapy history")
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[lone],
            exclusion_criteria=[],
        )
        assert drop_keys == set()
        assert records == []

    def test_should_not_collapse_the_alt_ast_ap_triple(self):
        """AC-004. Guarded explicitly rather than reasoned about.

        Two independent gates exclude these -- domain Measurement (gate 1) and a
        non-null `valueConstraint` (gate 2). Collapsing to fewer than three concept
        sets is the dedup-overreach regression AC-004 exists to catch.
        """
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[], exclusion_criteria=ALT_AST_AP
        )
        assert drop_keys == set()
        assert records == []

    def test_should_not_collapse_the_alt_ast_ap_triple_even_if_it_were_demographics(self):
        """Gate 2 alone must carry it, independent of domain.

        The domain gate is a second line of defence; if a future extraction ever
        labelled these Demographics, the constraint gate must still hold.
        """
        as_demographics = [dict(c, domain="Demographics") for c in ALT_AST_AP]
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[], exclusion_criteria=as_demographics
        )
        assert drop_keys == set()
        assert records == []

    def test_should_not_collapse_across_roles(self):
        """One criterion in each role is two singletons, not a pair."""
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[_criterion(id=1, description="Pregnancy")],
            exclusion_criteria=[_criterion(id=2, description="Pregnancy")],
        )
        assert drop_keys == set()
        assert records == []

    def test_should_not_collapse_two_grouped_criteria(self):
        """Gate 3. studyId 4 / 6 in the reference store carry exactly this shape."""
        grouped = [
            _criterion(id=7, description="Age >= 50 with CVD", group_id="238a942e"),
            _criterion(id=8, description="Age >= 60 with risk factors", group_id="238a942e"),
        ]
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=grouped, exclusion_criteria=[]
        )
        assert drop_keys == set()
        assert records == []

    def test_should_not_collapse_a_labelled_heading_with_its_member(self):
        """Gate 4 keeps a declared heading out of the count entirely."""
        mixed = [
            _criterion(id=1, description="Age (region-conditional)", is_group_label=True),
            _criterion(id=2, description="Pregnancy"),
        ]
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[], exclusion_criteria=mixed
        )
        assert drop_keys == set()
        assert records == []

    def test_should_report_empty_on_empty_input(self):
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=[], exclusion_criteria=[]
        )
        assert drop_keys == set()
        assert records == []


class TestBothRolesTogether:
    def test_should_detect_each_role_independently_and_report_inclusion_first(self):
        inclusion = [
            _criterion(id=1, description="Female of child-bearing potential"),
            _criterion(id=2, description="Women of reproductive age"),
        ]
        drop_keys, records = collapse_all_restated_demographics(
            inclusion_criteria=inclusion, exclusion_criteria=CAROLINA_PREGNANCY
        )
        assert [r["role"] for r in records] == ["inclusion", "exclusion"]
        assert drop_keys == {("inclusion", "2"), ("exclusion", "53")}
