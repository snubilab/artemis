"""SPEC-INFRA-004 M2 / AC-007 / AC-011: the census and the report, over real stored criteria.

`plan.md` §F orders the measurement before the behavior change so the fix has something to
move, and `plan.md` §G names the hazard of verifying with a single regeneration: agent1
emission is run-to-run unstable, so a green count claim from one store is weak evidence. What
is asserted here is therefore the *structure* the SPEC establishes — which clusters collapse,
which stay intact, and why — pinned to the reference store the SPEC measured.

Both census bases are asserted, because `spec.md` §2.6.2 records that quoting either one alone
has already produced a wrong number in an earlier draft.
"""
from __future__ import annotations

from src.services.restated_distinctness import (
    WITHHELD_EMPTY_SOURCE_TEXT,
    WITHHELD_KEY_DISTINCT,
    analyze_restated_groups,
)
from tests.infra_004_store_fixture import ROLES, criteria, studies, study_by_nct

CAROLINA = "NCT01243424"
EMPA_REG = "NCT01131676"
CARMELINA = "NCT01897532"


def _all_groups() -> list[dict]:
    """Every stem group of two or more members, across all 10 studies and both roles."""
    out = []
    for study in studies():
        for role in ROLES:
            for group in analyze_restated_groups(criteria(study, role), role=role):
                out.append({**group, "nctId": study.get("nctId"), "studyId": study["studyId"]})
    return out


class TestTheCensusReproducesTheSpecFigures:
    """`spec.md` §2.6.2, Basis 1 — the generalized path alone."""

    def test_should_find_twenty_five_stem_groups_of_two_or_more(self):
        assert len(_all_groups()) == 25

    def test_should_collapse_thirteen_and_leave_twelve_intact(self):
        groups = _all_groups()
        collapsing = [g for g in groups if g["collapses"]]
        intact = [g for g in groups if not g["collapses"]]
        assert (len(collapsing), len(intact)) == (13, 12), (
            [(g["nctId"], g["role"], g["stem"]) for g in collapsing],
            [(g["nctId"], g["role"], g["stem"]) for g in intact],
        )

    def test_should_place_carmelina_pregnancy_in_the_intact_set_as_demographics_path(self):
        """Basis 2's hinge: the one group of the 25 the *other* path collapses.

        `spec.md` §2.6.2 records this as the correction an earlier draft got wrong — it is a
        §2.1 Category 1 row that the generalized key does not collapse, for a reason neither
        recorded false negative covers. It is collapsed, but by the Demographics path.
        """
        (group,) = [
            g
            for g in _all_groups()
            if g["nctId"] == CARMELINA
            and g["role"] == "exclusion"
            and g["stem"] == "Pregnancy/Nursing/Uncontrolled Contraception"
        ]
        assert group["collapses"] is False
        assert group["consideredIds"] == [], "REQ-013 must admit none of this group"


class TestEveryCategoryTwoClusterIsIntact:
    """`spec.md` §2.1 Category 2 — distinct entities sharing an invented category label.

    These carry no harm today. They are what a naive domain-gate relaxation would destroy, so
    their staying intact is the property the SPEC exists to guarantee.
    """

    def _group(self, stem: str) -> dict:
        (group,) = [
            g
            for g in _all_groups()
            if g["nctId"] == EMPA_REG and g["role"] == "exclusion" and g["stem"] == stem
        ]
        return group

    def test_should_leave_cardiovascular_disease_intact_as_three_classes(self):
        group = self._group("Cardiovascular Disease")
        assert group["collapses"] is False
        assert group["reason"] == WITHHELD_KEY_DISTINCT
        assert len(group["classes"]) == 3

    def test_should_leave_thyroid_disorders_intact_as_two_classes(self):
        group = self._group("Thyroid Disorders")
        assert group["collapses"] is False
        assert len(group["classes"]) == 2

    def test_should_leave_adrenal_disorders_intact_as_two_classes(self):
        group = self._group("Adrenal Disorders")
        assert group["collapses"] is False
        assert len(group["classes"]) == 2


class TestTheKnownFalseNegativesAreReportedNotAbsorbed:
    """REQ-011 / AC-007. The report is the deliverable here, not the collapse."""

    def test_should_report_carolina_participation_in_another_trial_as_key_distinct(self):
        """`spec.md` §2.0 Correction 2. Reaching it needs synonym matching, which REQ-010
        forbids and whose forbidding is what keeps ALT/AST/AP safe."""
        (group,) = [
            g
            for g in _all_groups()
            if g["nctId"] == CAROLINA and g["stem"] == "Participation in another trial"
        ]
        assert group["collapses"] is False
        assert group["reason"] == WITHHELD_KEY_DISTINCT
        sources = sorted(cls["distinctnessKey"]["sourceText"] for cls in group["classes"])
        assert sources == ["Investigational Medicinal/Medical Product", "Investigational drug"]

    def test_should_report_empa_reg_egfr_as_key_distinct_under_strict_constraint_equality(self):
        """Decision Point 2, resolved as recommended. Conditional on that ruling: were
        `unitConceptId` normalized away, this pair would become a collapsing class."""
        (group,) = [
            g
            for g in _all_groups()
            if g["nctId"] == EMPA_REG and g["stem"] == "eGFR < 30 ml/min/1.73 m2"
        ]
        assert group["collapses"] is False
        assert group["reason"] == WITHHELD_KEY_DISTINCT
        assert len(group["classes"]) == 2

    def test_should_carry_per_member_keys_on_every_intact_group(self):
        """AC-007: the keys that kept the members apart must be in the artifact, so the next
        investigation reads them rather than re-deriving them — which is how {22,59} reached
        this SPEC mis-classified in the first place."""
        for group in _all_groups():
            if group["collapses"]:
                continue
            for cls in group["classes"]:
                assert set(cls["distinctnessKey"]) == {"sourceText", "valueConstraint", "logicType"}


class TestTheWithheldReasonPrecedence:
    """AC-007's second clause: `key-distinct` outranks `empty-sourceText` where both apply."""

    def _carmelina_inclusion_group(self, stem_prefix: str) -> dict:
        matches = [
            g
            for g in _all_groups()
            if g["nctId"] == CARMELINA
            and g["role"] == "inclusion"
            and g["stem"].startswith(stem_prefix)
        ]
        assert len(matches) == 1, [g["stem"] for g in matches]
        return matches[0]

    def test_should_report_carmelina_inclusion_age_as_key_distinct(self):
        group = self._carmelina_inclusion_group("Age")
        assert group["collapses"] is False
        assert group["reason"] == WITHHELD_KEY_DISTINCT

    def test_should_report_carmelina_inclusion_drug_naive_as_key_distinct(self):
        group = self._carmelina_inclusion_group("Drug-na")
        assert group["collapses"] is False
        assert group["reason"] == WITHHELD_KEY_DISTINCT

    def test_should_never_report_empty_source_text_where_the_keys_already_differ(self):
        """The precedence, stated as a property over the whole corpus rather than two cases."""
        for group in _all_groups():
            if group["reason"] != WITHHELD_EMPTY_SOURCE_TEXT:
                continue
            assert any(
                len(cls["criterionIds"]) >= 2 for cls in group["classes"]
            ), f"{group['stem']!r} reported empty-sourceText but every class is a singleton"


class TestTheReportIsIndependentOfTrialIdentity:
    """AC-011: a verdict for every stem group, without reference to trial identity."""

    def test_should_produce_a_verdict_for_every_group_including_unnamed_studies(self):
        groups = _all_groups()
        assert all(
            (g["collapses"] is True and g["reason"] is None)
            or (g["collapses"] is False and g["reason"] is not None)
            for g in groups
        )

    def test_should_reach_studies_carrying_no_nct_identifier(self):
        """Four of the ten studies carry `nctId: None`. The analysis must not depend on it."""
        unnamed = [s for s in studies() if s.get("nctId") is None]
        assert unnamed, "the fixture no longer exercises the unnamed-study path"
        for study in unnamed:
            for role in ROLES:
                analyze_restated_groups(criteria(study, role), role=role)


class TestTheCollapsingSetMatchesTheSpecEnumeration:
    def test_should_collapse_every_carolina_sibling_cluster(self):
        """AC-005, conditional on Decision Point 1 resolving as recommended (fold in)."""
        expected = {
            ("exclusion", "Alcohol Use Disorder"),
            ("exclusion", "Alcohol or drug abuse"),
            ("exclusion", "Opioid Use Disorder"),
            ("exclusion", "Cannabis Use Disorder"),
            ("exclusion", "Cocaine Use Disorder"),
            ("exclusion", "Other antidiabetic drugs"),
            ("exclusion", "GLP-1 Receptor Agonists"),
            ("exclusion", "SGLT2 Inhibitors"),
            ("exclusion", "DPP-4 Inhibitors"),
            ("exclusion", "Thiazolidinediones"),
            ("inclusion", "Age >= 70 years"),
        }
        observed = {
            (g["role"], g["stem"])
            for g in _all_groups()
            if g["nctId"] == CAROLINA and g["collapses"]
        }
        assert expected <= observed, expected - observed

    def test_should_collapse_the_carolina_age_seventy_group_despite_its_demographics_domain(self):
        """AC-016 fixture 3 at the analysis layer: a `domain != "Demographics"` gate would
        orphan this genuine duplicate — the Demographics path rejects it on gate 2."""
        (group,) = [
            g
            for g in _all_groups()
            if g["nctId"] == CAROLINA
            and g["role"] == "inclusion"
            and g["stem"] == "Age >= 70 years"
        ]
        assert group["domain"] == "Demographics"
        assert group["collapses"] is True
        assert len(group["consideredIds"]) == 2


class TestTheStoreExtractIsWhatTheSpecMeasured:
    def test_should_carry_all_ten_studies(self):
        assert len(studies()) == 10

    def test_should_carry_populated_source_text_on_the_collapsing_clusters(self):
        """`plan.md` B-1: `sourceText` changed status between SPECs and this SPEC depends on
        the inversion. Re-verified here rather than assumed."""
        carolina = study_by_nct(CAROLINA)
        alcohol = [
            c
            for c in criteria(carolina, "exclusion")
            if (c.get("description") or "").startswith("Alcohol Use Disorder")
        ]
        assert len(alcohol) == 2
        assert all((c.get("sourceText") or "").strip() for c in alcohol)
