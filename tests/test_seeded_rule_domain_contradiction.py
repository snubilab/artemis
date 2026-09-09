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
from src.utils.criterion_refusal import (
    REFUSAL_DOMAIN_CONTRADICTION,
    REFUSAL_UNMAPPABLE_PLACEHOLDER,
    CriterionRefused,
)

GLIMEPIRIDE_PRODUCTS = [43011498, 2012308, 2012309]
GINGIVITIS = 4192700

#: The wrong-domain answer the vocabulary actually returned for "Investigational Drug"
#: on 2026-09-10 (``empa-reg_treatment.circe.json``, ``_unmappedCriteria[1]``:
#: ``"DrugExposure vs Meas Value, Measurement, Observation, Procedure"``). Concept ids
#: are stand-ins; the DOMAIN_IDs are what the refusal reads.
WRONG_DOMAIN_ANSWER_DOMAINS = ["Meas Value", "Measurement", "Observation", "Procedure"]


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


def _multi_domain_mapping(domains: list[str], name: str) -> dict[str, Any]:
    """One concept per domain, in the seeded-concept-set shape the refusal reads."""
    return {
        "name": name,
        "domain": domains[0],
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": 9_000_000 + index,
                        "CONCEPT_NAME": f"{name} ({domain})",
                        "CONCEPT_CODE": str(9_000_000 + index),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
                for index, domain in enumerate(domains)
            ]
        },
        "mapping_metadata": None,
    }


#: Both rows verbatim from ``output/site_gap/2026-09-10/store/studies.json``. Note that
#: they disagree about which field carries the seed: #31 has an empty ``sourceText`` and
#: is seeded from its ``description``, #41 is seeded from its ``sourceText`` while its
#: ``description`` says "Prior investigational drug trial" -- which is a trial, names a
#: mappable entity, and must NOT be permitted. The classifier reads the SEED, so the
#: two answers come out right for opposite reasons.
ARISTOTLE_EXCLUSION_31 = {
    "id": 31,
    "description": "Investigational drug use",
    "sourceText": "",
    "domain": "Drug",
    "window": {"start": -30, "end": 0},
}
EMPA_REG_EXCLUSION_41 = {
    "id": 41,
    "description": "Prior investigational drug trial",
    "sourceText": "Investigational Drug",
    "domain": "Drug",
    "window": {"start": -30, "end": 0},
}


class TestADrugCategoryNamingNoIngredientIsIrreducible:
    """The two rows the 2026-09-10 delivery blocked on, at the raise site itself.

    ``domain-contradiction`` describes the MECHANISM -- the vocabulary answered from the
    wrong domain -- and the delivery gate does not permit it, correctly: a wrong-domain
    answer usually means a better seed or a better mapper would find the right one.
    These two are the case where it does not. "Investigational drug" names a role in the
    study, not a substance, so there is no RxNorm ingredient to find and the off-domain
    concepts are the vocabulary reaching for the nearest thing it has. The loss is
    IRREDUCIBLE, which is the axis ``PERMITTED_REFUSAL_CODES`` permits on.

    The message and ``detail`` are kept verbatim, so the mechanism stays legible in the
    delivered artifact; only the classification key moves.
    """

    @pytest.mark.parametrize(
        ("criterion", "seed"),
        [
            (ARISTOTLE_EXCLUSION_31, "Investigational drug use"),
            (EMPA_REG_EXCLUSION_41, "Investigational Drug"),
        ],
        ids=["aristotle-exclusion-31", "empa-reg-exclusion-41"],
    )
    def test_should_carry_the_irreducible_code_when_the_seed_is_a_drug_category(
        self, monkeypatch, criterion, seed
    ):
        service = _service(
            monkeypatch, _multi_domain_mapping(WRONG_DOMAIN_ANSWER_DOMAINS, seed)
        )

        with pytest.raises(CriterionRefused) as excinfo:
            service._build_seeded_eligibility_rule(
                criterion=criterion, codeset_id=41, exclusion=True
            )

        refused = excinfo.value
        assert refused.code == REFUSAL_UNMAPPABLE_PLACEHOLDER
        # The mechanism survives the re-coding: a reader of the delivered record can
        # still see WHICH domains came back and which table could not read them.
        assert "criterion domain contradiction: DrugExposure reads Drug" in str(refused)
        assert f"mapped for {seed!r}" in str(refused)
        assert refused.detail == "DrugExposure vs Meas Value, Measurement, Observation, Procedure"

    def test_should_keep_the_contradiction_code_when_the_seed_names_a_substance(
        self, monkeypatch
    ):
        """The control. CAROLINA's 'Glimepiride' is the same mechanism and the opposite
        verdict: a real substance in the wrong domain is a mapping the pipeline can fix,
        so it must keep failing the delivery gate."""
        service = _service(
            monkeypatch, _mapping(GLIMEPIRIDE_PRODUCTS, "Drug", "Glimepiride")
        )

        with pytest.raises(CriterionRefused) as excinfo:
            service._build_seeded_eligibility_rule(
                criterion=CAROLINA_CRITERION, codeset_id=56, exclusion=True
            )

        assert excinfo.value.code == REFUSAL_DOMAIN_CONTRADICTION

    def test_should_keep_the_contradiction_code_when_the_category_names_an_entity_too(
        self, monkeypatch
    ):
        """'Prior investigational drug trial' carries the category AND a trial, which
        has an Observation concept. Reading the criterion's description instead of its
        seed would permit this one, so the seed is what is read."""
        seed = "Prior investigational drug trial"
        service = _service(
            monkeypatch, _multi_domain_mapping(WRONG_DOMAIN_ANSWER_DOMAINS, seed)
        )

        with pytest.raises(CriterionRefused) as excinfo:
            service._build_seeded_eligibility_rule(
                criterion={
                    "id": 41,
                    "description": seed,
                    "sourceText": seed,
                    "domain": "Drug",
                },
                codeset_id=41,
                exclusion=True,
            )

        assert excinfo.value.code == REFUSAL_DOMAIN_CONTRADICTION
