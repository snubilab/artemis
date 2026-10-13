"""A reranker that answers "no candidate fits" refuses the criterion; the RAG fallback stays out.

When Agent 2 came back empty, ``_recommend_seeded_concept_set`` ran the RAG fallback
whatever the reason. Measured on the 2026-10-12 runs, every fallback start followed a
reranker no-match (14 in the delivery candidate's ``rebuild.log``, 8 in P3 arm A's
``driver.log``), and the three that reached delivered files all shipped a wrong or mostly
wrong concept set:

* delivery candidate ``output/site_gap/2026-10-12_prompt_f2``, CARMELINA inclusion #9
  'Insulin dose change': 60 offered, none selected (``rebuild.log`` 48479); codeset 6 holds
  two of the very LOINC dose tests the reranker had been shown and rejected.
* same run, CAROLINA exclusion #49 'Pre-menopausal woman': 20 offered, none selected
  (``rebuild.log`` 60551); codeset 62 is climacteric state, perimenopausal disorder,
  premature menopause and a family history of early menopause.
* P3 arm A ``output/site_gap/2026-10-12_p3_dry/arm_a``, LEADER exclusion #27 'awaiting
  solid organ transplant': 60 offered, none selected (``driver.log`` 1475); codeset 39
  is completed-transplant procedures, a transplant pharmacist and a device.

Now the reranker's verdict stands: the mapper refuses with code ``reranker-no-match``
(the stage, the candidate count and the query in its reason), the build records it under
``_unmappedCriteria``, and gate check (i) reports it as criterion loss. Every other empty
cause -- Agent 2 raising, a failed reranker, an answer that did not hydrate -- still goes
to the fallback with the records it had.

The store rows below are the three criteria as those runs hold them, and each fallback
pick is the concept set the delivered file shipped. No LLM, database or graph is
contacted: Agent 2 and the RAG recommender are replaced by what they returned in the run.
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from src.agents.agent2.retriever import CandidateConcept
from src.models.ir import MappingResult

#: The refusal code the three cases must carry. Spelled here rather than imported so that
#: a tree without it fails each assertion instead of failing collection.
CODE = "reranker-no-match"


class Case(NamedTuple):
    target: str
    role: str
    offered: int
    row: dict[str, Any]
    #: (id, name, domain, vocabulary, class) of the set the delivered file shipped.
    fallback_pick: list[tuple[int, str, str, str, str]]


CARMELINA_INCLUSION_9 = Case(
    target="Linagliptin",
    role="inclusion",
    offered=60,
    row={
        "id": 9, "description": "Insulin dose change percentage", "domain": "Measurement",
        "valueConstraint": {"op": "gt", "value": 10.0, "valueHigh": None, "unitText": "%",
                            "referenceBound": "absolute", "unitConceptId": 8554},
        "sourceText": "Insulin dose change",
        "protocolLine": (
            "Stable antidiabetic background medication (unchanged daily dose) for at least 8 "
            "weeks prior to randomization. If insulin is part of the background therapy, the "
            "average daily insulin dose should not have changed by more than 10% within the 8 "
            "weeks prior to randomization compared with the daily insulin dose at "
            "randomization."
        ),
        "protocolSpan": "Insulin", "window": {"start": -56, "end": 0}, "conceptSetId": 6,
        "conceptSetName": "Insulin dose change", "logicType": "ABSENCE",
        "groupId": "a1990ffe-ff3c-47c1-a670-48fd0cbeeffe", "groupType": "ALL",
        "parentGroupId": None, "isGroupLabel": False, "mappable": True,
    },
    fallback_pick=[
        (40486005, "Change in insulin dose", "Procedure", "SNOMED", "Procedure"),
        (45766743, "Insulin dose changed", "Observation", "SNOMED", "Context-dependent"),
        (37170144, "Mean total daily insulin dose delivered by continuous subcutaneous "
                   "infusion of insulin", "Measurement", "SNOMED", "Observable Entity"),
        (3027380, "Insulin ultralente [Mass] of Dose", "Measurement", "LOINC", "Lab Test"),
        (3007380, "Insulin regular [Mass] of Dose", "Measurement", "LOINC", "Lab Test"),
    ],
)

CAROLINA_EXCLUSION_49 = Case(
    target="linagliptin",
    role="exclusion",
    offered=20,
    row={
        "id": 49, "description": "Pre-menopausal status", "domain": "Demographics",
        "valueConstraint": None, "sourceText": "Pre-menopausal woman",
        "protocolLine": (
            "Pre-menopausal women (last menstruation # 1 year prior to informed consent) who "
            "are nursing or pregnant, or are of child-bearing potential and are not practicing "
            "an acceptable method of birth control (acceptable methods of birth control "
            "include tubal ligation, transdermal patch, intra uterine devices/systems "
            "(IUDs/IUSs), oral, implantable or injectable contraceptives, sexual abstinence "
            "(if allowed by local authorities), double barrier method and vasectomised "
            "partner) or do not plan to continue using acceptable method of birth control "
            "throughout the study and do not agree to submit to periodic pregnancy testing "
            "during participation in the trial"
        ),
        "protocolSpan": "Pre-menopausal women", "window": {"start": -9999, "end": 0},
        "conceptSetId": 62, "conceptSetName": "pre-menopausal woman", "logicType": "ABSENCE",
        "groupId": "8aae2531-81f4-46ee-8443-4fc6c4cbcea3", "groupType": "ALL",
        "parentGroupId": None, "isGroupLabel": False, "mappable": True,
    },
    fallback_pick=[
        (4113665, "Female climacteric state", "Observation", "SNOMED", "Observable Entity"),
        (4141640, "Perimenopausal disorder", "Condition", "SNOMED", "Disorder"),
        (198715, "Premature menopause", "Observation", "SNOMED", "Clinical Finding"),
        (4050823, "FH: Early menopause", "Observation", "SNOMED", "Context-dependent"),
    ],
)

LEADER_EXCLUSION_27 = Case(
    target="liraglutide",
    role="exclusion",
    offered=60,
    row={
        "id": 27, "description": "Awaiting solid organ transplant", "domain": "Procedure",
        "valueConstraint": None, "sourceText": "awaiting solid organ transplant",
        "protocolLine": "History of solid organ transplant or awaiting solid organ transplant",
        "protocolSpan": "awaiting solid organ transplant", "window": {"start": -9999, "end": 0},
        "conceptSetId": 39, "conceptSetName": "solid organ transplant", "logicType": "ABSENCE",
        "groupId": "ca71820d-1302-44ad-b8b9-9b34d6896433", "groupType": "ALL",
        "parentGroupId": None, "isGroupLabel": False, "mappable": True,
        "annotation": {
            "promptVersion": "rfc016-steps1-4-v1", "model": "vllm/google/gemma-4-E4B-it",
            "record_requirement": "forbidden", "conditional_span": None,
            "excepted_entities": [], "base_span": None, "relation": None,
            "relation_span": None, "cardinality": None, "timing": "at_index",
            "window_span": None, "route": ["any"], "route_span": None, "specimen": "any",
            "specimen_span": None, "no_entity": "none", "no_entity_span": None,
            "threshold_span": None, "quantity_kind": None, "reference_bound": None,
        },
    },
    fallback_pick=[
        (2721126, "Solid organ(s), complete or segmental, single organ or combination of "
                  "organs; deceased or living donor(s), procurement, transplantation, and "
                  "related complications", "Procedure", "HCPCS", "HCPCS"),
        (4208341, "Solid organ transplant to recipient", "Procedure", "SNOMED", "Procedure"),
        (42537955, "Discussion about solid organ transplantation", "Procedure", "SNOMED",
         "Procedure"),
        (700289, "Solid Organ Transplant Pharmacist", "Provider", "NUCC", "Provider"),
        (4227684, "Transplant solid organ", "Device", "SNOMED", "Substance"),
    ],
)

CASES = pytest.mark.parametrize(
    "case",
    [CARMELINA_INCLUSION_9, CAROLINA_EXCLUSION_49, LEADER_EXCLUSION_27],
    ids=["carmelina-inclusion-9", "carolina-exclusion-49", "leader-exclusion-27"],
)


def _seed(case: Case) -> str:
    return case.row["sourceText"]


def _no_match(case: Case) -> MappingResult:
    """What Agent 2 returned for the seed in the run: the reranker selected none."""
    return MappingResult(concept_ids=[], route_path="slow", reranker_no_match=case.offered)


def _fallback_answer(case: Case):
    """The RAG fallback, answering with the set the delivered file shipped."""
    from src.api.models.tte import CriterionMappingMetadata

    def answer(seed: str, expected_domain: str | None = None) -> dict[str, Any]:
        items = [
            {"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": name, "CONCEPT_CODE": str(cid),
                         "DOMAIN_ID": domain, "VOCABULARY_ID": vocab,
                         "CONCEPT_CLASS_ID": concept_class, "STANDARD_CONCEPT": "S"},
             "includeDescendants": True, "isExcluded": False, "includeMapped": False}
            for cid, name, domain, vocab, concept_class in case.fallback_pick
        ]
        return {"name": seed, "expression": {"items": items}, "domain": case.row["domain"],
                "mapping_metadata": CriterionMappingMetadata(
                    rerankMethod="rag_fallback", queryUsed=seed,
                    selectedConceptIds=[cid for cid, *_ in case.fallback_pick])}

    return MagicMock(side_effect=answer)


def _recommend(svc, seed: str, agent2, fallback, **kwargs) -> dict[str, Any]:
    """The real ``_recommend_seeded_concept_set``, Agent 2 answering ``agent2``.

    ``agent2`` is the MappingResult Agent 2 returns, or an exception it raises. The two
    ingredient tiers answer None, as they did for these seeds in the run.
    """
    from src.services.tte_service import TTEService

    answer = {"side_effect": agent2} if isinstance(agent2, BaseException) else {
        "return_value": agent2}
    with patch("src.agents.agent2.workflow.Agent2Workflow.process_with_details", **answer), \
            patch.object(TTEService, "_recommend_seeded_concept_set_rag_fallback",
                         side_effect=fallback), \
            patch.object(TTEService, "_exact_ingredient_mapping", return_value=None), \
            patch.object(TTEService, "_alias_ingredient_mapping", return_value=None), \
            patch.dict("os.environ", {"CRITERION_CACHE_ENABLED": "false"}):
        return TTEService._recommend_seeded_concept_set(svc, seed, **kwargs)


def _service():
    from src.services.tte_service import TTEService

    return TTEService(store=MagicMock())


# ── the workflow keeps the verdict ───────────────────────────


TOP5 = [  # CARMELINA's top 5 of the 60, as rebuild.log 47964 printed them
    (3027380, "Insulin ultralente [Mass] of Dose", 78.320),
    (3007380, "Insulin regular [Mass] of Dose", 78.952),
    (3017224, "Insulin Lente [Mass] of Dose", 80.722),
    (3005732, "Insulin semilente [Mass] of Dose", 81.562),
    (3004211, "Insulin NPH [Mass] of Dose", 83.158),
]


def _process(reply: str) -> MappingResult:
    """Agent2Workflow.process_with_details on CARMELINA's seed, its reranker answering ``reply``."""
    from src.agents.agent2 import reranker as reranker_mod
    from src.agents.agent2 import workflow as wf

    with patch.object(reranker_mod, "get_llm",
                      lambda *_a, **_k: RunnableLambda(lambda _p: AIMessage(content=reply))):
        reranker = reranker_mod.ConceptReranker()
    workflow = wf.Agent2Workflow()
    workflow._reranker = reranker
    seed = _seed(CARMELINA_INCLUSION_9)
    candidates = [
        CandidateConcept(concept_id=cid, concept_name=name, domain_id="Measurement",
                         vocabulary_id="LOINC", concept_class_id="Lab Test", distance=dist)
        for cid, name, dist in TOP5
    ]
    with patch.object(wf, "expand_abbreviation", return_value=(seed, False)), \
            patch.object(wf, "expand_in_context", side_effect=lambda q: q), \
            patch.object(wf.logician, "decompose_combination", side_effect=lambda cid: [cid]), \
            patch.object(wf.logician, "prune_empty_concepts", side_effect=lambda ids: ids), \
            patch.object(wf.logician, "drop_qualitative_findings", side_effect=lambda ids: ids), \
            patch.object(wf.Agent2Workflow, "_kg_expand_and_critique",
                         side_effect=lambda ids, *a, **k: (ids, [], True)), \
            patch.object(wf, "get_kg_expander"):
        return workflow.process_with_details(
            seed, domain_hint="Measurement", pre_fetched_candidates=candidates,
        )


def test_should_keep_how_many_candidates_were_offered_when_the_reranker_answers_no_match():
    result = _process(json.dumps({"query_has_match": False, "selected_ids": []}))

    assert result.concept_ids == []
    assert result.reranker_no_match == len(TOP5)
    # Still a judgement, not a failure: nothing is booked under mapping_failures().
    assert result.reranker_failure is None and result.mapping_failures() == []


def test_should_keep_no_verdict_when_the_reranker_selects_a_candidate():
    result = _process(json.dumps({"query_has_match": True, "selected_ids": [3027380]}))

    assert result.concept_ids == [3027380]
    assert result.reranker_no_match is None


# ── the mapper refuses, and the fallback is not asked ────────


@CASES
def test_should_refuse_without_asking_the_rag_fallback_when_the_reranker_answers_no_match(case):
    from src.utils.criterion_refusal import CriterionRefused

    fallback = _fallback_answer(case)

    with pytest.raises(CriterionRefused) as raised:
        _recommend(_service(), _seed(case), _no_match(case), fallback,
                   expected_domain=None if case.row["domain"] == "Demographics"
                   else case.row["domain"])

    fallback.assert_not_called()
    assert raised.value.code == CODE
    message = str(raised.value)
    assert "reranker_no_match" in message, message
    assert f"none of the {case.offered} candidates" in message, message
    assert repr(_seed(case)) in message, message


def test_should_name_the_reranker_no_match_code_in_the_refusal_vocabulary():
    from src.utils.criterion_refusal import REFUSAL_CODES, SEED_CAUSED_REFUSAL_CODES

    assert CODE in REFUSAL_CODES
    # A verdict on the seed: asked a different text, the reranker can answer differently.
    assert CODE in SEED_CAUSED_REFUSAL_CODES


# ── every other empty cause still reaches the fallback ───────


def test_should_still_run_the_rag_fallback_when_agent2_raises():
    case = CARMELINA_INCLUSION_9
    fallback = _fallback_answer(case)

    out = _recommend(_service(), _seed(case), TimeoutError("read timeout"), fallback,
                     expected_domain="Measurement")

    fallback.assert_called_once()
    assert out["mapping_metadata"].rerankMethod == "rag_fallback"
    assert out["mapping_metadata"].selectedConceptIds == [c for c, *_ in case.fallback_pick]


def test_should_still_run_the_rag_fallback_with_the_failure_when_the_reranker_failed():
    case = CARMELINA_INCLUSION_9
    fallback = _fallback_answer(case)
    reason = "OutputParserException: Invalid json output"

    out = _recommend(_service(), _seed(case),
                     MappingResult(concept_ids=[], route_path="slow", reranker_failure=reason),
                     fallback, expected_domain="Measurement")

    fallback.assert_called_once()
    assert out["mapping_metadata"].mappingFailures == [
        {"stage": "reranker", "reason": reason, "seedsOnly": False, "query": _seed(case)}
    ]


def test_should_still_run_the_rag_fallback_when_agent2_returned_nothing_it_judged():
    """Empty without a reranker verdict (ids that did not hydrate, an empty expression)."""
    case = CARMELINA_INCLUSION_9
    fallback = _fallback_answer(case)

    out = _recommend(_service(), _seed(case), MappingResult(concept_ids=[], route_path="slow"),
                     fallback, expected_domain="Measurement")

    fallback.assert_called_once()
    assert out["mapping_metadata"].mappingFailures == []


# ── the build records the refusal and gate check (i) reports it ──


def _clean_target_mapping(name: str) -> dict[str, Any]:
    """The entry drug, mapped with no failure: the build needs one and it is not under test."""
    from src.api.models.tte import CriterionMappingMetadata

    return {
        "name": name, "domain": "Drug",
        "expression": {"items": [{
            "concept": {"CONCEPT_ID": 40239216, "CONCEPT_NAME": name, "CONCEPT_CODE": "x",
                        "DOMAIN_ID": "Drug", "VOCABULARY_ID": "RxNorm",
                        "CONCEPT_CLASS_ID": "Ingredient", "STANDARD_CONCEPT": "S"},
            "includeDescendants": True, "isExcluded": False,
        }]},
        "mapping_metadata": CriterionMappingMetadata(queryUsed=name, selectedConceptIds=[40239216]),
    }


def _eligibility(case: Case) -> dict[str, Any]:
    row = json.loads(json.dumps(case.row))
    return {
        "targetCohortName": case.target,
        "inclusionCriteria": [row] if case.role == "inclusion" else [],
        "exclusionCriteria": [row] if case.role == "exclusion" else [],
    }


def _build(case: Case, monkeypatch) -> tuple[dict[str, Any], MagicMock]:
    """The study's build of this one criterion, its seed running the mapper's real branch."""
    svc = _service()
    fallback = _fallback_answer(case)

    def mapper(seed: str, **kwargs):
        if seed.strip() == case.target:
            return _clean_target_mapping(seed.strip())
        return _recommend(svc, seed, _no_match(case), fallback, **kwargs)

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", mapper)
    # The specimen step reads LOINC System/Property from the vocabulary database; it runs
    # only on a mapped Measurement set, after the step under test.
    monkeypatch.setattr(svc, "_refine_measurement_specimen",
                        lambda expression, **_k: (expression, None))
    return svc._build_seeded_target_circe(_eligibility(case)), fallback


@CASES
def test_should_record_the_refusal_under_unmapped_criteria_when_the_reranker_answers_no_match(
    case, monkeypatch
):
    from src.utils.circe_lint import MAPPING_FAILURE_CRITERIA_KEY

    circe, fallback = _build(case, monkeypatch)

    fallback.assert_not_called()
    rows = [r for r in circe.get("_unmappedCriteria") or []
            if r.get("criterionId") == str(case.row["id"])]
    assert [(r["role"], r["refusalCode"]) for r in rows] == [(case.role, CODE)], rows
    assert f"none of the {case.offered} candidates" in rows[0]["reason"], rows[0]
    assert [r for r in circe[MAPPING_FAILURE_CRITERIA_KEY]
            if r["criterionId"] == str(case.row["id"])] == []


@CASES
def test_should_fail_gate_check_i_on_the_refused_criterion(case, monkeypatch):
    from scripts.verify_circe_delivery import criterion_accounting, unmapped_refusal_block_reason

    circe, _ = _build(case, monkeypatch)
    [row] = [r for r in circe.get("_unmappedCriteria") or []
             if r.get("criterionId") == str(case.row["id"])]
    study = {"id": 1, "eligibility": _eligibility(case)}

    block = unmapped_refusal_block_reason(row, case.row)
    violations, _summary = criterion_accounting(circe, study)

    assert block is not None and f"'{CODE}'" in block, block
    assert any(f"'{CODE}'" in v and str(case.row["id"]) in v for v in violations), violations
