"""Check (m) reads only concept sets the cohort reads.

A ``_restatedRuleCollapse`` record keeps the removed rule's concept set in ``ConceptSets`` so the
gate can re-derive the collapse; nothing in the cohort reads it. P8 MAIN (2026-10-20)
``carmelina_treatment``: codesets 5 and 7 'Exclusion of GLP-1 RA, DPP-4i, SGLT-2i if recent
(repetition)' are such sets, each byte-identical to the referenced codeset 3, and check (m) failed
the file on the pair. A set no criterion reads selects nobody, so its name describes nothing.
"""
from __future__ import annotations

from typing import Any


def _set(codeset_id: int, name: str, concept_ids: list[int]) -> dict[str, Any]:
    return {
        "id": codeset_id,
        "name": name,
        "expression": {
            "items": [
                {"concept": {"CONCEPT_ID": cid}, "includeDescendants": True, "isExcluded": False}
                for cid in concept_ids
            ]
        },
    }


def _absence(codeset_id: int) -> dict[str, Any]:
    return {
        "Criteria": {"DrugExposure": {"CodesetId": codeset_id}},
        "StartWindow": {"Start": {"Days": 7, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}},
        "Occurrence": {"Type": 0, "Count": 0},
    }


#: Three members of CARMELINA codeset 3 as delivered (teplizumab, tirzepatide, semaglutide).
INCRETIN_LIKE = [741995, 779705, 793143]
#: Three members of CARMELINA codesets 8 and 18 (ertugliflozin, bexagliflozin, luseogliflozin).
SGLT2 = [793293, 1301517, 35198021]


def _rule(name: str, codeset_id: int) -> dict[str, Any]:
    return {"name": name, "expression": {"Type": "ALL", "CriteriaList": [_absence(codeset_id)]}}


def _expression() -> dict[str, Any]:
    return {
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "ConceptSets": [
            _set(1, "Linagliptin", [40239216]),
            _set(3, "Exclusion of GLP-1 RA, DPP-4i, SGLT-2i if recent", INCRETIN_LIKE),
            _set(5, "Exclusion of GLP-1 RA, DPP-4i, SGLT-2i if recent (repetition)", INCRETIN_LIKE),
            _set(8, "Sodium Glucose Linked Transporter 2 (SGLT-2) inhibitors", SGLT2),
            _set(18, "SGLT-2 inhibitors", SGLT2),
        ],
        "InclusionRules": [
            _rule("GLP-1 receptor agonists", 3),
            _rule("SGLT-2 (incl. 4)", 8),
            _rule("SGLT-2 (excl. 2)", 18),
        ],
        "_restatedRuleCollapse": [{**_rule("SGLT-2 inhibitors", 5), "rule": "SGLT-2 inhibitors"}],
    }


def test_should_not_report_a_pair_whose_second_set_no_criterion_reads():
    from scripts.verify_circe_delivery import cohort_aliased_concept_sets

    findings = cohort_aliased_concept_sets(_expression())

    assert not any("(repetition)" in finding for finding in findings), findings


def test_should_still_report_two_read_sets_with_identical_members_under_two_names():
    from scripts.verify_circe_delivery import cohort_aliased_concept_sets

    findings = cohort_aliased_concept_sets(_expression())

    assert len(findings) == 1, findings
    assert "8 'Sodium Glucose Linked Transporter 2 (SGLT-2) inhibitors'" in findings[0]
    assert "18 'SGLT-2 inhibitors'" in findings[0]
