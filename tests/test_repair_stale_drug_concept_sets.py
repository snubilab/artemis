"""The stale-drug concept-set repair may not rewrite a set it cannot justify rewriting.

``TTEService._repair_stale_drug_concept_sets`` re-maps any concept set whose NAME is
exactly one standard RxNorm Ingredient onto that ingredient. It matched on the name
alone, and on the 2026-09-06 delivery store that produced two measured defects:

1. A DOMAIN it never looked at. Studies 1/4/5/6 carry a set named ``Calcitonin`` read by
   a ``Measurement`` criterion with ``ValueAsNumber >= 50`` -- LEADER's medullary-thyroid-
   carcinoma screen. The repair replaced it with RxNorm Drug ingredient 42900359
   ``calcitonin``, so the emitted rule joined ``measurement.measurement_concept_id``
   against a drug product and matched nothing; the screen became vacuously true. A scan
   of the store finds 0 domain-mismatched criteria and every emitted file finds exactly
   1, so the export introduced it.

2. A CLOSURE it never checked. Studies 4/5/6 hold ``liraglutide`` =
   ``[842602, 842604, 40170911]`` -- the ingredient plus the Saxenda and Victoza Marketed
   Products. The repair collapsed it to the ingredient alone, and neither 842602 nor
   842604 is among the ingredient's 248 ``concept_ancestor`` descendants (RxNorm Extension
   products are not linked to the RxNorm ingredient there), so the emitted set resolved
   strictly narrower than the stored one.

Neither rule subsumes the other, which is why both are here. The domain gate alone still
narrows liraglutide (its criterion really is ``DrugEra``); the closure gate alone still
wrecks studies 4/5/6's ``Calcitonin``, whose single SNOMED concept 4147378 shares nothing
with the drug ingredient and so reads as wholly stale.

The closure gate declines exactly the ambiguous middle. Measured against
``concept_ancestor`` over the whole store, a matched set falls into one of three cases:

* every stored concept is the ingredient or one of its descendants -- the rewrite is
  provably lossless, so it proceeds (PLATO's ``Reteplase``, ``Factor VIII``,
  ``Fibrinogen``; unchanged from before this gate existed);
* no stored concept is -- the set is provably not about the drug it is named after, which
  is the stale shape the repair exists for (a set named ``linagliptin`` holding
  sitagliptin), so it proceeds;
* some are and some are not -- both readings are live, a curated superset or a half-stale
  set, and the repair cannot tell them apart from the file. It declines and warns.

The five sets the repair narrowed on this store are all in the third case: ``liraglutide``
(studies 4/5/6) and PLATO's ``Alteplase``, ``Tenecteplase``, ``Streptokinase`` and
``Factor IX`` each already carried the ingredient's own concepts alongside products
outside its ``concept_ancestor`` closure.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from src.services.tte_service import TTEService

# Real ids, from tmp/tte_six_deliver_20260906/studies.json and synthea23m.concept.
CALCITONIN_INGREDIENT = 42900359          # RxNorm Ingredient, domain Drug
CALCITONIN_MEASUREMENT = 4147378          # SNOMED 'Calcitonin measurement', domain Measurement
CALCITONIN_LOINC = [3010989, 3018840]     # two of study 1's 15 LOINC lab tests
LIRAGLUTIDE = 40170911                    # RxNorm Ingredient
SAXENDA = 842602                          # RxNorm Extension Marketed Product, NOT a descendant
VICTOZA = 842604                          # RxNorm Extension Marketed Product, NOT a descendant
RETEPLASE = 19024191                      # RxNorm Ingredient
RETEPLASE_PRODUCTS = [1593772, 1593774, 1593775]   # all inside the ingredient closure
LINAGLIPTIN = 40239216
SITAGLIPTIN = 1580747


def _item(concept_id: int, domain: str, name: str = "c", excluded: bool = False) -> dict[str, Any]:
    return {
        "concept": {
            "CONCEPT_ID": concept_id,
            "CONCEPT_NAME": name,
            "CONCEPT_CODE": str(concept_id),
            "DOMAIN_ID": domain,
            "VOCABULARY_ID": "RxNorm",
            "CONCEPT_CLASS_ID": "Ingredient",
        },
        "includeDescendants": True,
        "isExcluded": excluded,
    }


def _base(concept_sets: list[dict[str, Any]], references: dict[int, list[str]]) -> dict[str, Any]:
    """A CIRCE base whose InclusionRules reference each codeset under the given types."""
    rules = []
    for codeset_id, criteria_types in references.items():
        for criteria_type in criteria_types:
            rules.append(
                {
                    "name": f"rule-{codeset_id}-{criteria_type}",
                    "expression": {
                        "Type": "ALL",
                        "CriteriaList": [
                            {
                                "Criteria": {criteria_type: {"CodesetId": codeset_id}},
                                "StartWindow": {
                                    "Start": {"Days": 365, "Coeff": -1},
                                    "End": {"Days": 0, "Coeff": 1},
                                },
                                "Occurrence": {"Type": 2, "Count": 1},
                            }
                        ],
                        "DemographicCriteriaList": [],
                        "Groups": [],
                    },
                }
            )
    return {
        "ConceptSets": concept_sets,
        "PrimaryCriteria": {
            "CriteriaList": [],
            "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": rules,
    }


@pytest.fixture
def service(monkeypatch):
    """A service whose three vocabulary lookups answer from fixtures, not from psycopg2.

    ``subsumed`` is the real ``concept_ancestor`` answer for the ids used here: the
    Reteplase products are descendants of their ingredient, the Saxenda/Victoza products
    are not descendants of liraglutide, and sitagliptin is not a descendant of
    linagliptin.
    """
    svc = TTEService.__new__(TTEService)
    ingredients = {
        "calcitonin": CALCITONIN_INGREDIENT,
        "liraglutide": LIRAGLUTIDE,
        "reteplase": RETEPLASE,
        "linagliptin": LINAGLIPTIN,
    }
    subsumed = {(RETEPLASE, d) for d in RETEPLASE_PRODUCTS}

    monkeypatch.setattr(
        svc,
        "_unique_ingredient_ids_by_name",
        lambda names: {k: v for k, v in ingredients.items() if k in names},
    )
    monkeypatch.setattr(
        svc,
        "_subsumed_concept_pairs",
        lambda pairs: {p for p in pairs if p in subsumed},
    )
    built: list[tuple[int, str]] = []

    def _rollup(concept_id: int, name: str) -> dict[str, Any]:
        built.append((concept_id, name))
        return {"items": [_item(concept_id, "Drug", name)]}

    monkeypatch.setattr(svc, "_ingredient_rollup_expression", _rollup)
    svc._test_built = built  # type: ignore[attr-defined]
    return svc


def _ids(concept_set: dict[str, Any]) -> list[int]:
    return sorted(
        item["concept"]["CONCEPT_ID"]
        for item in concept_set.get("expression", {}).get("items") or []
    )


class TestTheCriterionDomainGate:
    def test_should_leave_the_set_alone_when_a_measurement_criterion_reads_it(self, service):
        """LEADER's Calcitonin screen: study 4/5/6's shape, one SNOMED measurement concept."""
        base = _base(
            [{"id": 33, "name": "Calcitonin",
              "expression": {"items": [_item(CALCITONIN_MEASUREMENT, "Measurement")]}}],
            {33: ["Measurement"]},
        )
        service._repair_stale_drug_concept_sets(base)
        assert _ids(base["ConceptSets"][0]) == [CALCITONIN_MEASUREMENT]

    def test_should_leave_the_set_alone_when_a_measurement_criterion_reads_lab_tests(self, service):
        """Study 1's shape: the same name over 15 LOINC lab tests (two of them here)."""
        base = _base(
            [{"id": 24, "name": "Calcitonin",
              "expression": {"items": [_item(c, "Measurement") for c in CALCITONIN_LOINC]}}],
            {24: ["Measurement"]},
        )
        service._repair_stale_drug_concept_sets(base)
        assert _ids(base["ConceptSets"][0]) == sorted(CALCITONIN_LOINC)

    def test_should_decline_when_two_criteria_read_the_same_set_from_different_tables(
        self, service
    ):
        """A set read by both a Drug table and a non-Drug one has no rewrite that is right
        for both, so it is left as stored rather than made right for one of them."""
        base = _base(
            [{"id": 7, "name": "Calcitonin",
              "expression": {"items": [_item(CALCITONIN_MEASUREMENT, "Measurement")]}}],
            {7: ["DrugExposure", "Measurement"]},
        )
        service._repair_stale_drug_concept_sets(base)
        assert _ids(base["ConceptSets"][0]) == [CALCITONIN_MEASUREMENT]

    def test_should_decline_when_no_criterion_references_the_set(self, service):
        """No referencing criterion is no evidence about which table the set is read from."""
        base = _base(
            [{"id": 9, "name": "Calcitonin",
              "expression": {"items": [_item(CALCITONIN_MEASUREMENT, "Measurement")]}}],
            {},
        )
        service._repair_stale_drug_concept_sets(base)
        assert _ids(base["ConceptSets"][0]) == [CALCITONIN_MEASUREMENT]


class TestTheClosureGate:
    def test_should_keep_products_the_ingredient_does_not_subsume_when_the_set_is_drug_read(
        self, service
    ):
        """Studies 4/5/6's entry set. Saxenda and Victoza are liraglutide products that
        ``concept_ancestor`` does not link to the ingredient; collapsing to the ingredient
        drops them and resolves strictly narrower than the store."""
        base = _base(
            [{"id": 1, "name": "liraglutide",
              "expression": {"items": [
                  _item(c, "Drug") for c in (SAXENDA, VICTOZA, LIRAGLUTIDE)
              ]}}],
            {1: ["DrugEra"]},
        )
        service._repair_stale_drug_concept_sets(base)
        assert _ids(base["ConceptSets"][0]) == sorted([SAXENDA, VICTOZA, LIRAGLUTIDE])

    def test_should_roll_up_to_the_ingredient_when_the_set_shares_nothing_with_its_name(
        self, service
    ):
        """The defect the repair exists for: a set named for one ingredient holding
        another drug entirely. Nothing in it belongs to linagliptin, so it is replaced."""
        base = _base(
            [{"id": 1, "name": "linagliptin",
              "expression": {"items": [_item(SITAGLIPTIN, "Drug")]}}],
            {1: ["DrugEra"]},
        )
        service._repair_stale_drug_concept_sets(base)
        assert _ids(base["ConceptSets"][0]) == [LINAGLIPTIN]
        assert service._test_built == [(LINAGLIPTIN, "linagliptin")]

    def test_should_roll_up_when_every_stored_concept_is_inside_the_ingredient_closure(
        self, service
    ):
        """PLATO's Reteplase set: three products, all inside the ingredient's closure, so
        the roll-up cannot lose a concept. This is the case the repair already handled and
        the gate must not take away."""
        base = _base(
            [{"id": 11, "name": "Reteplase",
              "expression": {"items": [_item(c, "Drug") for c in RETEPLASE_PRODUCTS]}}],
            {11: ["DrugExposure"]},
        )
        service._repair_stale_drug_concept_sets(base)
        assert _ids(base["ConceptSets"][0]) == [RETEPLASE]
        assert service._test_built == [(RETEPLASE, "Reteplase")]

    def test_should_decline_when_the_set_carries_an_excluded_item(self, service):
        """A flat ingredient roll-up cannot express a subtraction, so replacing a set that
        carries one would silently re-include the route it excluded."""
        base = _base(
            [{"id": 1, "name": "linagliptin",
              "expression": {"items": [
                  _item(SITAGLIPTIN, "Drug"),
                  _item(1580748, "Drug", excluded=True),
              ]}}],
            {1: ["DrugEra"]},
        )
        service._repair_stale_drug_concept_sets(base)
        assert _ids(base["ConceptSets"][0]) == sorted([SITAGLIPTIN, 1580748])


class TestTheSubsumptionLookupFailing:
    def test_should_rewrite_nothing_when_the_subsumption_lookup_cannot_answer(
        self, service, monkeypatch, caplog
    ):
        """A database error is "not established", not "nothing is subsumed". Treating it
        as the latter would send every matched set down the wholly-stale branch and
        rewrite them all, which is the destructive direction to fail in."""
        monkeypatch.setattr(service, "_subsumed_concept_pairs", lambda pairs: None)
        base = _base(
            [{"id": 1, "name": "linagliptin",
              "expression": {"items": [_item(SITAGLIPTIN, "Drug")]}}],
            {1: ["DrugEra"]},
        )
        with caplog.at_level(logging.WARNING):
            service._repair_stale_drug_concept_sets(base)
        assert _ids(base["ConceptSets"][0]) == [SITAGLIPTIN]
        assert service._test_built == []
        assert any("subsumption lookup" in r.getMessage() for r in caplog.records)


class TestTheDeclineIsReported:
    def test_should_warn_when_a_drug_read_set_is_declined_for_partial_overlap(
        self, service, caplog
    ):
        """A decline that left a possibly-stale set in place must be legible afterwards."""
        base = _base(
            [{"id": 1, "name": "liraglutide",
              "expression": {"items": [
                  _item(c, "Drug") for c in (SAXENDA, VICTOZA, LIRAGLUTIDE)
              ]}}],
            {1: ["DrugEra"]},
        )
        with caplog.at_level(logging.WARNING):
            service._repair_stale_drug_concept_sets(base)
        messages = [r.getMessage() for r in caplog.records]
        assert any("liraglutide" in m and "842602" in m for m in messages), messages
