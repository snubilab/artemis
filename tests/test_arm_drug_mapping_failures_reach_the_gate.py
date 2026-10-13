"""A failure in the arm drug's own mapping reaches the arm file and gate (ab).

Every arm builder maps its drug with ``_recommend_seeded_concept_set`` and keeps only the
name, domain and expression of the answer: the ``mapping_metadata`` -- and with it
``mappingFailures`` -- was dropped at each site. The arm file inherits the eligibility's
``_mappingFailureCriteria`` from the stored expression, so a failure in the eligibility
mappings was seen by gate (ab), while a failure in the one mapping made for the arm
itself was not: an arm entering on, or excluding, a drug set built by a failed reranker,
KG lookup or critic shipped with a green (ab).

Measured on 1835b17: six builders, the five named in the brief plus the active comparator
(``_build_drug_anchored_comparator_circe``), each returned a file whose record did not
mention the failed arm mapping. Now each appends one ``{"criterionId": "_arm", "role",
"label", "failures"}`` row; a clean mapping leaves the record exactly as inherited.

Nothing here reaches a database or a model: the mapper is replaced by its answer.
"""

import json
from typing import Any
from unittest.mock import patch

import pytest

from src.api.models.tte import CriterionMappingMetadata
from src.services.tte_service import TTEService

KEY = "_mappingFailureCriteria"
FAILURE = {"stage": "reranker", "seedsOnly": False, "query": "empagliflozin",
           "reason": 'OutputParserException: Invalid json output: {"query_has_match": true, '
                     '"selected_ids": [45774751, 4577'}
ELIGIBILITY_ROW = {"criterionId": "7", "role": "exclusion", "label": "eGFR < 30",
                   "failures": [{"stage": "critic", "reason": "TimeoutError: read timeout",
                                 "seedsOnly": True, "query": "eGFR"}]}


def _mapped(failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": "empagliflozin",
        "domain": "Drug",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 45774751}, "isExcluded": False,
                                  "includeDescendants": True}]},
        "mapping_metadata": CriterionMappingMetadata(queryUsed="empagliflozin",
                                                     mappingFailures=failures),
    }


def _eligibility(record: list[dict[str, Any]] | None) -> dict[str, Any]:
    structured: dict[str, Any] = {
        "ConceptSets": [{"id": 1, "name": "empagliflozin", "expression": {"items": []}}],
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}],
                            "ObservationWindow": {"PriorDays": 365, "PostDays": 0}},
        "InclusionRules": [],
    }
    if record is not None:
        structured[KEY] = json.loads(json.dumps(record))
    return {"structuredExpression": structured}


def _service(failures):
    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = lambda seed, **_k: _mapped(failures)
    svc._drug_anchored_entry = lambda: False
    svc._swap_primary_to_disease = lambda base, *_a, **_k: base
    return svc


#: builder name -> (call, role, label)
BUILDERS = {
    "leader treatment only": (
        lambda svc, elig: svc._build_leader_treatment_only_circe("empagliflozin"),
        "treatment", "empagliflozin"),
    "benchmark compat drug primary": (
        lambda svc, elig: svc._build_benchmark_compat_drug_primary_circe(elig, "empagliflozin"),
        "treatment", "empagliflozin"),
    "combined treatment": (
        lambda svc, elig: svc._build_combined_treatment_circe(elig, "empagliflozin"),
        "treatment", "empagliflozin"),
    "disease-based treatment": (
        lambda svc, elig: svc._build_disease_based_treatment_circe(elig, "empagliflozin"),
        "treatment", "empagliflozin"),
    "disease-based comparator": (
        lambda svc, elig: svc._build_disease_based_comparator_circe(elig, "empagliflozin"),
        "comparator", "No empagliflozin"),
    "active comparator": (
        lambda svc, elig: svc._build_drug_anchored_comparator_circe(elig, "empagliflozin"),
        "comparator", "empagliflozin"),
}


@pytest.mark.parametrize("builder", sorted(BUILDERS))
def test_should_list_the_arm_drug_mapping_failure_in_the_arm_file(builder):
    from scripts.verify_circe_delivery import mapping_failure_findings

    build, role, label = BUILDERS[builder]

    circe = build(_service([FAILURE]), _eligibility([ELIGIBILITY_ROW]))

    arm_row = {"criterionId": "_arm", "role": role, "label": label, "failures": [FAILURE]}
    if builder == "leader treatment only":
        assert circe[KEY] == [arm_row]
    else:
        assert circe[KEY] == [ELIGIBILITY_ROW, arm_row]
    findings, _clause = mapping_failure_findings(circe)
    assert findings and f"{role} #_arm {label!r} [reranker: " in findings[0], findings


@pytest.mark.parametrize("builder", sorted(BUILDERS))
@pytest.mark.parametrize("record", [[], None], ids=["record empty", "record absent"])
def test_should_leave_the_record_as_inherited_when_the_arm_drug_mapped_clean(builder, record):
    build, _role, _label = BUILDERS[builder]

    circe = build(_service([]), _eligibility(record))

    if record is None or builder == "leader treatment only":
        assert KEY not in circe
    else:
        assert circe[KEY] == []


def test_should_not_touch_the_stored_eligibility_record():
    eligibility = _eligibility([ELIGIBILITY_ROW])

    TTEService._build_combined_treatment_circe(_service([FAILURE]), eligibility, "empagliflozin")

    assert eligibility["structuredExpression"][KEY] == [ELIGIBILITY_ROW]


def test_should_read_failures_from_a_metadata_dict_too():
    """The criterion cache replays mapping metadata as a model; a stub or older caller may
    hand a plain dict."""
    svc = _service([])
    mapped = _mapped([])
    mapped["mapping_metadata"] = {"mappingFailures": [FAILURE]}
    svc._recommend_seeded_concept_set = lambda seed, **_k: mapped

    with patch.object(TTEService, "_drug_anchored_entry", return_value=False):
        circe = svc._build_combined_treatment_circe(_eligibility([]), "empagliflozin")

    assert circe[KEY][-1]["failures"] == [FAILURE]


# ── the single-codeset cohort (outcomes), the same drop ──────


@pytest.mark.parametrize("failures", [[FAILURE], []], ids=["mapping failed", "mapping clean"])
def test_should_list_the_cohort_mapping_failure_in_the_outcome_expression(failures):
    """_build_seeded_single_codeset_circe kept only the answer's name, domain and expression,
    as the arm builders did: an outcome cohort built on a failed mapping carried no record."""
    circe = _service(failures)._build_seeded_condition_circe(
        "Stroke", expected_domain="Condition", capture_all_events=True)

    if failures:
        assert circe[KEY] == [{"criterionId": "_cohort", "role": "cohort", "label": "Stroke",
                               "failures": [FAILURE]}]
    else:
        assert KEY not in circe
