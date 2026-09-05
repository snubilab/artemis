"""A mapper answer that contradicts the criterion's own domain is refused, not emitted.

``_build_seeded_eligibility_rule`` takes the criterion's declared ``domain`` as the CDM
table to read (``Condition`` -> ``ConditionOccurrence``) and, separately, asks the mapper
for a concept set. Nothing compared the two, so a mapper answer from a different domain
was written into a criterion that cannot read it.

CAROLINA is the measured case. Store study 10, ``exclusionCriteria`` id 25:

    description = "Hypersensitivity to investigational product or glimepiride"
    domain      = "Condition"
    sourceText  = "Glimepiride"

The mapper is seeded from ``sourceText``, which had already lost the head noun, so it
answered with glimepiride Drug products (``_ruleIndexMeta["22"]``: ``rerankMethod:
"rag_fallback"``, ``queryUsed: "Glimepiride"``). The emitted rule is a
``ConditionOccurrence`` criterion over a Drug concept set; measured against WebAPI it
returns 0 persons where the same criterion over a Condition set returns 5,975 out of
10,093 (``output/site_gap/2026-09-06/plan048_domain_repair/``). It is an ABSENCE rule, so
matching nothing means the exclusion is never applied to anyone.

``src.utils.circe_lint.domain_mismatched_criteria`` already refuses to deliver that shape.
This is the same test applied one step earlier, so the generator stops producing what the
delivery gate will reject. A criterion that fails it is recorded in ``_unmappedCriteria``
and dropped -- honestly absent rather than present and vacuous.

The seed itself is left alone. Preferring ``description`` over ``sourceText`` globally
would change the seed for 264 of the 560 criteria in the store, and the examples show why
that is the wrong lever: ``sourceText`` is the concept phrase ("Ankle-brachial index",
"Myocardial Infarction") while ``description`` carries the value qualifier the concept
mapper must not see ("Ankle-brachial index < 0.9", "HbA1c >= 7.0%"), which
``build_measurement_value_filter`` already handles separately. CAROLINA's is an upstream
extraction defect -- a dropped head noun, not a dropped value -- and is surfaced here
rather than papered over.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.services.tte_service import TTEService

GLIMEPIRIDE_PRODUCTS = [43011498, 2012308, 2012309]
GINGIVITIS = 4192700


def _mapping(concept_ids: list[int], domain: str, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": cid,
                        "CONCEPT_NAME": name,
                        "CONCEPT_CODE": str(cid),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "RxNorm",
                        "CONCEPT_CLASS_ID": "Branded Drug",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
                for cid in concept_ids
            ]
        },
        "mapping_metadata": None,
    }


def _service(monkeypatch, mapping: dict[str, Any]) -> TTEService:
    svc = TTEService.__new__(TTEService)
    monkeypatch.setattr(
        svc, "_recommend_seeded_concept_set", lambda seed, **kwargs: mapping
    )
    return svc


CAROLINA_CRITERION = {
    "id": 25,
    "description": "Hypersensitivity to investigational product or glimepiride",
    "sourceText": "Glimepiride",
    "domain": "Condition",
}


class TestTheGeneratorRefusesAContradiction:
    def test_should_raise_when_the_mapped_set_shares_no_domain_with_the_criterion_table(
        self, monkeypatch
    ):
        service = _service(
            monkeypatch, _mapping(GLIMEPIRIDE_PRODUCTS, "Drug", "Glimepiride")
        )
        with pytest.raises(ValueError) as excinfo:
            service._build_seeded_eligibility_rule(
                criterion=CAROLINA_CRITERION, codeset_id=56, exclusion=True
            )
        message = str(excinfo.value)
        assert "ConditionOccurrence" in message
        assert "Drug" in message

    def test_should_build_the_rule_when_the_mapped_set_matches_the_criterion_table(
        self, monkeypatch
    ):
        """The control that makes the refusal mean something: the same criterion type over
        a Condition-domain set is built exactly as before."""
        service = _service(monkeypatch, _mapping([GINGIVITIS], "Condition", "Hypersensitivity"))
        rule = service._build_seeded_eligibility_rule(
            criterion=CAROLINA_CRITERION, codeset_id=56, exclusion=True
        )
        criteria = rule["rule"]["expression"]["CriteriaList"][0]["Criteria"]
        assert list(criteria) == ["ConditionOccurrence"]
        assert criteria["ConditionOccurrence"]["CodesetId"] == 56

    def test_should_build_the_rule_when_the_criterion_declares_no_domain(self, monkeypatch):
        """With no declared domain the mapper's own domain picks the table, so there are
        never two answers to disagree about."""
        service = _service(monkeypatch, _mapping(GLIMEPIRIDE_PRODUCTS, "Drug", "Glimepiride"))
        rule = service._build_seeded_eligibility_rule(
            criterion={"id": 25, "sourceText": "Glimepiride", "domain": ""},
            codeset_id=56,
            exclusion=True,
        )
        criteria = rule["rule"]["expression"]["CriteriaList"][0]["Criteria"]
        assert list(criteria) == ["DrugExposure"]

    def test_should_build_the_rule_when_the_mapped_set_carries_no_readable_domain(
        self, monkeypatch
    ):
        """No ``DOMAIN_ID`` is an unknown, not a contradiction; the gate stays silent for
        the same reason ``domain_mismatched_criteria`` does."""
        mapping = _mapping([GINGIVITIS], "Condition", "Hypersensitivity")
        mapping["expression"]["items"][0]["concept"].pop("DOMAIN_ID")
        service = _service(monkeypatch, mapping)
        rule = service._build_seeded_eligibility_rule(
            criterion=CAROLINA_CRITERION, codeset_id=56, exclusion=True
        )
        assert "ConditionOccurrence" in rule["rule"]["expression"]["CriteriaList"][0]["Criteria"]
