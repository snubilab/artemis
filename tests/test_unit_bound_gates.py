"""Two unit defects that made a criterion match the wrong population.

Both were measured against ``postgres.synthea_cdm`` (7,834,306 measurements, units
populated, NOT generated from ``data/gold/``) and against the three delivery-site
CDMs ``ajou_cdm`` / ``donga_cdm`` / ``keimyung_cdm``. Every number quoted below is
from a read-only ``SELECT``; none of it is reasoned.

Defect A -- a threshold transcribed WITHOUT its unit.
    ARISTOTLE exclusion 23 ("Platelet count <= 100,000/ mm") reached Circe as a bare
    ``ValueAsNumber {Value: 100000.0, Op: "lte"}``. ``unitText`` was ``"/ mm"`` -- the
    superscript of ``/mm3`` was lost upstream -- and ``normalize_unit`` correctly
    refused to guess, so the ``Unit`` sibling was dropped and the NUMBER was emitted
    alone. In ``synthea_cdm`` every one of the 41,114 platelet rows (concept 3024929,
    unit 8848 ``10*3/uL``, min 99.0 / median 287.3 / max 450.0) satisfies
    ``value_as_number <= 100000``, so the exclusion removed every patient who has ever
    had a platelet count. Gold's ``<= 100`` matches 75 of them (0.18%).

    A bound whose unit could not be stated is not a narrower bound -- it is a bound in
    an unknown unit, which is a different claim. The builder keeps emitting the
    fragment it always did; the CALLER now refuses the criterion, the same division
    ``refuse_unreadable_value_filter`` already uses.

Defect B -- declaring a unit no CDM records.
    Circe emits ``AND unit_concept_id IN (...)``, so a declared unit the CDM never
    wrote zeroes the criterion. EMPA-REG exclusion 8 and CAROLINA inclusion 25 declare
    720870 ``mL/min/(173.10*-2.m2)`` over eGFR, and 720870 matches 0 rows in all four
    CDMs. 720870 is NOT the wrong concept: it is the CURRENT standard, valid from
    2022-04-07, and it REPLACES 9117 ``mL/min/1.73.m2`` (invalid_reason 'U', valid_end
    2022-03-28). The three sites' ETLs still write the predecessor -- ajou 4,266,
    donga 2,331, keimyung 7,248 eGFR rows all carry 9117 -- so the emitted filter
    excluded exactly the rows it was written to select.

    The fix is the vocabulary's own equivalence, not a per-analyte conversion table:
    a declared unit is emitted together with the deprecated UCUM spellings that map to
    it. Three rows across the whole unit table, every one a matter of vocabulary
    record and re-derivable by ``verify_unit_table_against_database``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.value_constraint import (
    absolute_unit_concept_id,
    build_measurement_value_filter,
)
from src.utils.criterion_refusal import REFUSAL_CODES, CriterionRefused

# Verbatim from `output/site_gap/2026-09-13/store/studies.json`, study 3 exclusion 23.
ARISTOTLE_PLATELET_VC: dict[str, Any] = {
    "op": "lte",
    "value": 100000.0,
    "valueHigh": None,
    "unitText": "/ mm",
    "referenceBound": "absolute",
    "unitConceptId": None,
}


def _production_service() -> Any:
    """A TTEService whose only stubbed seam is concept-set recommendation.

    Copied deliberately from ``tests/test_value_constraint.py``: that file already
    established this as the offline-reachable production path, and a second way of
    reaching it would be a second thing to keep in step.
    """
    from src.services.tte_service import TTEService

    service = TTEService(store=MagicMock())
    service._recommend_seeded_concept_set = lambda *args, **kwargs: {
        "name": "Platelet count",
        "domain": "Measurement",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 3024929}}]},
    }
    return service


def _build(value_constraint: dict[str, Any] | None, source_text: str) -> dict[str, Any]:
    built = _production_service()._build_seeded_eligibility_rule(
        criterion={
            "sourceText": source_text,
            "domain": "Measurement",
            "valueConstraint": value_constraint,
            "window": {"start": -180, "end": 0},
            "logicType": "ABSENCE",
        },
        codeset_id=25,
        exclusion=True,
    )
    return built["rule"]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]


# ---------------------------------------------------------------------------
# Defect A -- a bound whose declared unit did not resolve
# ---------------------------------------------------------------------------


class TestUnstatedUnitBound:
    def test_should_name_the_unresolved_unit_when_an_absolute_bound_declares_one(self):
        from src.services.value_constraint import unstated_absolute_unit

        assert unstated_absolute_unit(ARISTOTLE_PLATELET_VC) == "/ mm"

    def test_should_stay_silent_when_the_constraint_declares_no_unit_at_all(self):
        """The blast radius is bounds that DECLARED a unit and lost it, not bounds
        that never carried one. LEADER's ``HbA1c >= 7.0`` and PLATO's ST-segment
        criteria carry ``unitText: ""``; nothing was dropped from them, so nothing
        here may refuse them -- 12 of the store's 22 bare bounds are that shape."""
        from src.services.value_constraint import unstated_absolute_unit

        assert unstated_absolute_unit({"op": "gte", "value": 7.0, "unitText": ""}) is None
        assert unstated_absolute_unit({"op": "gte", "value": 7.0}) is None

    def test_should_stay_silent_when_the_declared_unit_resolves(self):
        from src.services.value_constraint import unstated_absolute_unit

        assert unstated_absolute_unit({"op": "gt", "value": 2.5, "unitText": "mg/dL"}) is None

    def test_should_stay_silent_for_a_reference_relative_bound(self):
        """"3 x ULN" is unit-free by construction -- it emits ``RangeHighRatio``, which
        Circe divides by the row's own ``range_high``. There is no unit to state."""
        from src.services.value_constraint import unstated_absolute_unit

        assert unstated_absolute_unit({"op": "gt", "value": 3.0, "unitText": "x ULN"}) is None

    def test_should_stay_silent_when_the_constraint_emits_no_value_at_all(self):
        """Half a range emits ``{}``; there is no bound to refuse."""
        from src.services.value_constraint import unstated_absolute_unit

        assert unstated_absolute_unit({"op": "bt", "value": 30.0, "unitText": "furlongs"}) is None

    def test_should_carry_a_refusal_code_the_vocabulary_knows(self):
        from src.utils.criterion_refusal import REFUSAL_UNSTATED_UNIT_BOUND

        assert REFUSAL_UNSTATED_UNIT_BOUND in REFUSAL_CODES

    def test_should_refuse_the_aristotle_platelet_criterion_at_emission(self):
        """The delivered rule matched 41,114 of 41,114 ``synthea_cdm`` platelet rows.
        Refusing leaves the claim honestly absent; emitting it left an ABSENCE rule
        that removed every patient carrying the lab."""
        with pytest.raises(CriterionRefused) as excinfo:
            _build(ARISTOTLE_PLATELET_VC, "Platelet count ≤ 100,000/ mm")

        from src.utils.criterion_refusal import REFUSAL_UNSTATED_UNIT_BOUND

        assert excinfo.value.code == REFUSAL_UNSTATED_UNIT_BOUND
        assert "/ mm" in str(excinfo.value)

    def test_should_still_emit_a_bound_whose_unit_resolves(self):
        """Paired with the row above so the refusal cannot pass by refusing everything."""
        criteria = _build(
            {"op": "gt", "value": 2.5, "unitText": "mg/dL"}, "Creatinine > 2.5 mg/dL"
        )
        assert criteria["ValueAsNumber"] == {"Value": 2.5, "Op": "gt"}
        assert [u["CONCEPT_ID"] for u in criteria["Unit"]] == [8840]

    def test_should_still_emit_a_bound_that_declared_no_unit(self):
        criteria = _build({"op": "gte", "value": 7.0, "unitText": ""}, "HbA1c >= 7.0")
        assert criteria["ValueAsNumber"] == {"Value": 7.0, "Op": "gte"}
        assert "Unit" not in criteria

    def test_should_leave_the_emitted_fragment_unchanged(self):
        """The builder's contract is the fragment; the refusal is the caller's.
        Folding the refusal into ``build_measurement_value_filter`` would make it
        return ``{}``, and ``{}`` is what every caller reads as "no filter" -- the
        criterion would then emit UNFILTERED, which is the worse half of this defect."""
        assert build_measurement_value_filter(ARISTOTLE_PLATELET_VC) == {
            "ValueAsNumber": {"Value": 100000.0, "Op": "lte"}
        }


# ---------------------------------------------------------------------------
# Defect B -- a declared unit the CDM records under its deprecated predecessor
# ---------------------------------------------------------------------------


class TestDeprecatedUnitForms:
    def test_should_emit_the_deprecated_ucum_spellings_beside_the_standard_one(self):
        """``Unit IN (720870)`` matched 0 of the 13,845 eGFR rows across the three
        delivery sites; all of them carry 9117, which 720870 replaced in 2022."""
        emitted = build_measurement_value_filter(
            {"op": "lt", "value": 30.0, "unitText": "mL/min/1.73 m2"}
        )

        ids = [u["CONCEPT_ID"] for u in emitted["Unit"]]
        assert ids[0] == 720870, "the standard concept stays first"
        assert 9117 in ids
        assert set(ids) == {720870, 9117, 9062}

    def test_should_keep_the_gold_unit_item_shape_on_every_element(self):
        emitted = build_measurement_value_filter(
            {"op": "lt", "value": 30.0, "unitText": "mL/min/1.73 m2"}
        )
        expected = set(emitted["Unit"][0])
        for item in emitted["Unit"]:
            assert set(item) == expected
            assert item["DOMAIN_ID"] == "Unit"
            assert item["VOCABULARY_ID"] == "UCUM"

    def test_should_not_widen_a_unit_that_has_no_deprecated_predecessor(self):
        """8876 ``mm[Hg]`` matches 0 rows at all three sites too -- their SBP rows carry
        ``unit_concept_id = 0``. That is a site ETL gap, not a vocabulary one, and
        nothing in ``concept_relationship`` may be stretched to cover it."""
        emitted = build_measurement_value_filter(
            {"op": "gt", "value": 180.0, "unitText": "mm Hg"}
        )
        assert [u["CONCEPT_ID"] for u in emitted["Unit"]] == [8876]

    def test_should_agree_with_the_check_that_approved_the_bound(self):
        """``absolute_unit_concept_id`` is what ``check_analyte_unit`` reasons about.
        The expansion must not make the emitted filter disagree with it: the STANDARD
        concept is still the one answer, the rest are spellings of it."""
        constraint = {"op": "lt", "value": 30.0, "unitText": "mL/min/1.73 m2"}
        assert build_measurement_value_filter(constraint)["Unit"][0]["CONCEPT_ID"] == (
            absolute_unit_concept_id(constraint)
        )

    def test_should_only_ever_add_deprecated_ucum_units_of_the_same_concept(self):
        """A guard on the table rather than on one row: every added spelling must be a
        UCUM concept the vocabulary marks invalid, never a second live unit. Adding a
        LIVE concept here would widen the filter to a different quantity."""
        from src.services.value_constraint import _UNIT_CONCEPTS, _UNIT_DEPRECATED_FORMS

        for standard_id, forms in _UNIT_DEPRECATED_FORMS.items():
            assert standard_id in _UNIT_CONCEPTS, standard_id
            for concept_id, _code, _name in forms:
                assert concept_id not in _UNIT_CONCEPTS, (
                    f"{concept_id} is a live unit in _UNIT_CONCEPTS; a deprecated form "
                    f"must never be one"
                )


# ---------------------------------------------------------------------------
# Defect C -- a REAL UCUM unit the table simply did not carry
# ---------------------------------------------------------------------------

# Verbatim from `output/site_gap/2026-09-14/store/studies.json`, study 10
# (CAROLINA) inclusion 26. The mu is U+03BC, which is what NFKC folds U+00B5 onto.
CAROLINA_UACR_VC: dict[str, Any] = {
    "op": "gte",
    "value": 30.0,
    "valueHigh": None,
    "unitText": "μg/mg",
    "referenceBound": "absolute",
    "unitConceptId": None,
}


class TestUnitTheTableDidNotCarry:
    """Defect A's refusal is right for prose in the unit field and wrong for a real
    unit we happened not to list. ``μg/mg`` is UCUM 8838, a valid standard concept
    in the live vocabulary, and CAROLINA's whole albuminuria inclusion was thrown away
    for it -- on both arms, in every delivery through 2026-09-14."""

    def test_should_emit_the_carolina_uacr_bound_instead_of_refusing_it(self):
        emitted = _build(CAROLINA_UACR_VC, "Urinary albumin creatinine ratio")
        assert emitted["ValueAsNumber"] == {"Value": 30.0, "Op": "gte"}
        assert emitted["Unit"][0]["CONCEPT_ID"] == 8838

    def test_should_accept_the_same_quantity_written_at_the_same_scale(self):
        """Circe emits ``AND unit_concept_id IN (...)`` with no fallback, so a CDM that
        wrote 8723 ``mg/g`` matches nothing against a filter naming only 8838
        ``ug/mg``. 1 mg/g == 1 μg/mg, so both spellings belong in the one filter."""
        emitted = _build(CAROLINA_UACR_VC, "Urinary albumin creatinine ratio")
        assert 8723 in [u["CONCEPT_ID"] for u in emitted["Unit"]]

    def test_should_resolve_both_code_points_of_micro_to_one_concept(self):
        from src.services.value_constraint import normalize_unit

        assert normalize_unit("μg/mg") == normalize_unit("µg/mg") == 8838
        assert normalize_unit("ug/mg") == 8838


class TestSameScaleEquivalenceNeverCrossesAScale:
    """The ARISTOTLE platelet error, stated as a table invariant. Gold writes ``100``
    thousands/uL and the protocol PDF writes ``100,000/mm3``; the two are the same
    DIMENSION a factor of 1000 apart, and merging them takes the cohort to 0."""

    def test_should_not_accept_a_thousandfold_neighbour_in_one_unit_filter(self):
        emitted = _build(
            {"op": "lte", "value": 100.0, "unitText": "/mm3"}, "Platelet count"
        )
        ids = [u["CONCEPT_ID"] for u in emitted["Unit"]]
        assert ids[0] == 8785
        assert 8647 in ids, "/uL is the same scale as /mm3 and must be accepted"
        assert 8848 not in ids, "10*3/uL is 1000x /mm3 -- the ARISTOTLE error"
        assert 8961 not in ids, "10*3/mm3 is 1000x /mm3 -- the ARISTOTLE error"

    def test_should_refuse_a_table_that_declares_a_thousandfold_pair_equivalent(self):
        """The gate a future reader hits when 'helpfully' merging them. Shown firing,
        because a guard that only ever passes is indistinguishable from one that does
        nothing."""
        from src.services.value_constraint import (
            _UNIT_NEVER_SAME_SCALE,
            _build_same_scale_index,
        )

        with pytest.raises(ValueError, match="1000"):
            _build_same_scale_index(
                (frozenset({8785, 8848}),), _UNIT_NEVER_SAME_SCALE
            )

    def test_should_refuse_a_pair_merged_only_through_a_third_unit(self):
        """The merge that does not look like one: ``/mm3 == /uL`` and
        ``/uL == 10*3/uL`` are each a single edge, and together they put 8785 and 8848
        in one class. The check is over the transitive closure for that reason."""
        from src.services.value_constraint import (
            _UNIT_NEVER_SAME_SCALE,
            _build_same_scale_index,
        )

        with pytest.raises(ValueError, match="1000"):
            _build_same_scale_index(
                (frozenset({8785, 8647}), frozenset({8647, 8848})),
                _UNIT_NEVER_SAME_SCALE,
            )


class TestProseInTheUnitFieldStillRefuses:
    """Narrowing the refusal, never removing it. Each spelling below is verbatim from
    the 2026-09-14 delivery's ``_unmappedCriteria``."""

    @pytest.mark.parametrize(
        "unit_text, source_text",
        [
            ("at Visit 1", "Body Mass Index"),
            ("mm (not known", "ST-segment elevation"),
            (
                "transient elevation >= 1 mm contiguous leads or new in two or more "
                "2 contiguous leads",
                "ST-segment depression",
            ),
            # A pdftotext superscript artifact, not a unit. The repair belongs in the
            # PDF-reading path; guessing `/mm3` here would be a guess, and `/mm` is
            # ambiguous between per-millimetre and per-cubic-millimetre.
            ("/ mm", "Platelet count"),
            ("ml/min/1.73 m", "eGFR"),
        ],
    )
    def test_should_keep_refusing(self, unit_text: str, source_text: str):
        with pytest.raises(CriterionRefused) as excinfo:
            _build({"op": "lte", "value": 1.0, "unitText": unit_text}, source_text)
        assert excinfo.value.code == "unstated-unit-bound"
