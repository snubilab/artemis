"""A concept set the RAG fallback chose after the reranker said no candidate fits is recorded.

When Agent 2 comes back empty, ``_recommend_seeded_concept_set`` runs the RAG fallback.
A reranker that *failed* was already carried onto the fallback's mapping (stage
``reranker``), so gate (ab) saw it. A reranker that *answered* "none of these fit" was
not: ``MappingResult`` kept no trace of the verdict beyond a gap reason it shares with
an empty retrieval, and the fallback's mapping reached the delivered file as an ordinary
criterion.

The real case, from the delivery candidate ``output/site_gap/2026-10-12_prompt_f2``:
CARMELINA (NCT01897532, store study 9) inclusion #9, seed 'Insulin dose change', domain
Measurement. ``rebuild.log`` line 48479: ``[Reranker] 'Insulin dose change': no candidate
denotes the term (60 offered) -- selecting none``; line 48484: ``FINAL 'Insulin dose
change' -> []``; then the RAG recommender ran on the same seed, and both delivered
CARMELINA files carry its pick as codeset 6, with no failure record. Two of the five are
the retriever's #1 and #2 -- candidates the reranker had been shown and rejected.

Now the workflow keeps how many candidates the reranker turned down, and the seeded
mapping records it as stage ``reranker_no_match`` on whatever the fallback returns, so
the build lists the criterion under ``_mappingFailureCriteria`` and gate (ab) FAILS it.

No LLM, database or graph is contacted: the reranker's model is a stub returning the
answer the output contract defines for "none fit", and Agent 2 / the RAG recommender are
replaced by what they returned in that run.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from src.agents.agent2.retriever import CandidateConcept
from src.models.ir import MappingResult

SEED = "Insulin dose change"
DOMAIN = "Measurement"
#: ``Using 60 pre-fetched candidates for 'Insulin dose change'`` (rebuild.log 47963).
OFFERED_IN_THE_RUN = 60

#: The retriever's top 5 of those 60, as rebuild.log printed them (id, name, distance).
TOP5 = [
    (3027380, "Insulin ultralente [Mass] of Dose", 78.320),
    (3007380, "Insulin regular [Mass] of Dose", 78.952),
    (3017224, "Insulin Lente [Mass] of Dose", 80.722),
    (3005732, "Insulin semilente [Mass] of Dose", 81.562),
    (3004211, "Insulin NPH [Mass] of Dose", 83.158),
]

#: What the RAG fallback put in CARMELINA codeset 6 (id, name, domain, vocabulary).
FALLBACK_PICK = [
    (40486005, "Change in insulin dose", "Procedure", "SNOMED"),
    (45766743, "Insulin dose changed", "Observation", "SNOMED"),
    (37170144, "Mean total daily insulin dose delivered by continuous subcutaneous "
               "infusion of insulin", "Measurement", "SNOMED"),
    (3027380, "Insulin ultralente [Mass] of Dose", "Measurement", "LOINC"),
    (3007380, "Insulin regular [Mass] of Dose", "Measurement", "LOINC"),
]

#: The store row for CARMELINA inclusion #9, as the delivery candidate holds it.
CRITERION = {
    "id": 9,
    "description": "Insulin dose change percentage",
    "domain": DOMAIN,
    "valueConstraint": {"op": "gt", "value": 10.0, "valueHigh": None, "unitText": "%",
                        "referenceBound": "absolute", "unitConceptId": 8554},
    "sourceText": SEED,
    "protocolLine": (
        "Stable antidiabetic background medication (unchanged daily dose) for at least 8 "
        "weeks prior to randomization. If insulin is part of the background therapy, the "
        "average daily insulin dose should not have changed by more than 10% within the 8 "
        "weeks prior to randomization compared with the daily insulin dose at randomization."
    ),
    "protocolSpan": "Insulin",
    "window": {"start": -56, "end": 0},
    "logicType": "ABSENCE",
    "isGroupLabel": False,
    "mappable": True,
}


def _candidates() -> list[CandidateConcept]:
    return [
        CandidateConcept(concept_id=cid, concept_name=name, domain_id=DOMAIN,
                         vocabulary_id="LOINC", concept_class_id="Lab Test", distance=dist)
        for cid, name, dist in TOP5
    ]


# ── the workflow keeps the verdict ───────────────────────────


def _workflow_answering(reply: str):
    """An Agent2Workflow whose reranker's model answers ``reply``."""
    from src.agents.agent2 import reranker as reranker_mod
    from src.agents.agent2 import workflow as wf

    with patch.object(reranker_mod, "get_llm",
                      lambda *_a, **_k: RunnableLambda(lambda _p: AIMessage(content=reply))):
        reranker = reranker_mod.ConceptReranker()
    workflow = wf.Agent2Workflow()
    workflow._reranker = reranker
    return workflow


def _process(workflow) -> MappingResult:
    from src.agents.agent2 import workflow as wf

    with patch.object(wf, "expand_abbreviation", return_value=(SEED, False)), \
            patch.object(wf, "expand_in_context", side_effect=lambda q: q), \
            patch.object(wf.logician, "decompose_combination", side_effect=lambda cid: [cid]), \
            patch.object(wf.logician, "prune_empty_concepts", side_effect=lambda ids: ids), \
            patch.object(wf.logician, "drop_qualitative_findings", side_effect=lambda ids: ids), \
            patch.object(wf.Agent2Workflow, "_kg_expand_and_critique",
                         side_effect=lambda ids, *a, **k: (ids, [], True)), \
            patch.object(wf, "get_kg_expander"):
        return workflow.process_with_details(
            SEED, domain_hint=DOMAIN, pre_fetched_candidates=_candidates(),
        )


def test_should_keep_how_many_candidates_were_offered_when_the_reranker_answers_no_match():
    result = _process(_workflow_answering(
        json.dumps({"query_has_match": False, "selected_ids": []})
    ))

    assert result.concept_ids == []
    assert result.reranker_no_match == len(TOP5)
    # Still a judgement, not a failure: nothing is booked under mapping_failures().
    assert result.reranker_failure is None and result.mapping_failures() == []


def test_should_keep_no_verdict_when_the_reranker_selects_a_candidate():
    result = _process(_workflow_answering(
        json.dumps({"query_has_match": True, "selected_ids": [3027380]})
    ))

    assert result.concept_ids == [3027380]
    assert result.reranker_no_match is None


# ── the seeded mapping carries it past the RAG fallback ──────


def _fallback_mapping(seed: str, expected_domain: str | None = None) -> dict[str, Any]:
    """What ``_recommend_seeded_concept_set_rag_fallback`` returned for the seed in the run."""
    from src.api.models.tte import CriterionMappingMetadata, MappingCandidateItem

    items = [
        {"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": name, "CONCEPT_CODE": str(cid),
                     "DOMAIN_ID": domain, "VOCABULARY_ID": vocab,
                     "CONCEPT_CLASS_ID": "Clinical Finding", "STANDARD_CONCEPT": "S"},
         "includeDescendants": True, "isExcluded": False, "includeMapped": False}
        for cid, name, domain, vocab in FALLBACK_PICK
    ]
    return {
        "name": seed,
        "expression": {"items": items},
        "domain": DOMAIN,
        "mapping_metadata": CriterionMappingMetadata(
            allCandidates=[
                MappingCandidateItem(conceptId=cid, conceptName=name, score=1.0,
                                     source="rag", included=True)
                for cid, name, _d, _v in FALLBACK_PICK
            ],
            rerankMethod="rag_fallback",
            queryUsed=seed,
            selectedConceptIds=[cid for cid, *_ in FALLBACK_PICK],
        ),
    }


def _recommend(rag, agent2: MappingResult) -> dict[str, Any]:
    """``_recommend_seeded_concept_set`` with Agent 2 returning ``agent2``."""
    from src.services import tte_service

    with patch("src.agents.agent2.workflow.Agent2Workflow.process_with_details",
               return_value=agent2), \
            patch.object(tte_service.TTEService, "_recommend_seeded_concept_set_rag_fallback",
                         side_effect=rag), \
            patch.dict("os.environ", {"CRITERION_CACHE_ENABLED": "false"}):
        return tte_service.TTEService(store=MagicMock())._recommend_seeded_concept_set(
            SEED, expected_domain=DOMAIN
        )


#: What Agent 2 returned for the seed in the run.
NO_MATCH = MappingResult(concept_ids=[], route_path="slow",
                         reranker_no_match=OFFERED_IN_THE_RUN)


def test_should_record_the_no_match_on_the_mapping_when_the_rag_fallback_maps_the_seed():
    out = _recommend(_fallback_mapping, NO_MATCH)

    assert [cid for cid, *_ in FALLBACK_PICK] == out["mapping_metadata"].selectedConceptIds
    [record] = out["mapping_metadata"].mappingFailures
    assert record["stage"] == "reranker_no_match"
    assert record["query"] == SEED
    assert record["seedsOnly"] is False
    assert f"none of the {OFFERED_IN_THE_RUN} candidates" in record["reason"], record


def test_should_record_nothing_new_when_agent2_returned_no_reranker_verdict():
    """An empty Agent 2 answer the reranker never judged is not a no-match."""
    out = _recommend(_fallback_mapping, MappingResult(concept_ids=[], route_path="slow"))

    assert out["mapping_metadata"].mappingFailures == []


def test_should_name_the_no_match_when_the_rag_fallback_refuses_too():
    from src.services.tte_service import CriterionRefused

    def rag(seed, expected_domain=None):
        raise CriterionRefused(f"No concept mapping found for '{seed}'", code="no-concept-mapping")

    with pytest.raises(CriterionRefused) as raised:
        _recommend(rag, NO_MATCH)

    assert "reranker_no_match: " in str(raised.value), raised.value
    assert raised.value.code == "no-concept-mapping"


# ── the build lists it and gate (ab) fails it ────────────────


TARGET = "linagliptin"


def _clean_target_mapping() -> dict[str, Any]:
    """The entry drug, mapped with no failure: the build needs one and it is not under test."""
    from src.api.models.tte import CriterionMappingMetadata

    return {
        "name": TARGET,
        "domain": "Drug",
        "expression": {"items": [{
            "concept": {"CONCEPT_ID": 40239216, "CONCEPT_NAME": TARGET, "CONCEPT_CODE": "x",
                        "DOMAIN_ID": "Drug", "VOCABULARY_ID": "RxNorm",
                        "CONCEPT_CLASS_ID": "Ingredient", "STANDARD_CONCEPT": "S"},
            "includeDescendants": True, "isExcluded": False,
        }]},
        "mapping_metadata": CriterionMappingMetadata(queryUsed=TARGET,
                                                     selectedConceptIds=[40239216]),
    }


@pytest.fixture
def carmelina_circe(monkeypatch):
    """The CARMELINA build of inclusion #9, its seed running the mapper's real fallback branch."""
    from src.services.tte_service import TTEService

    svc = TTEService(store=MagicMock())
    real = TTEService._recommend_seeded_concept_set

    def mapper(seed, **kwargs):
        if seed.strip() == TARGET:
            return _clean_target_mapping()
        with patch("src.agents.agent2.workflow.Agent2Workflow.process_with_details",
                   return_value=NO_MATCH), \
                patch.object(TTEService, "_recommend_seeded_concept_set_rag_fallback",
                             side_effect=_fallback_mapping), \
                patch.dict("os.environ", {"CRITERION_CACHE_ENABLED": "false"}):
            return real(svc, seed, **kwargs)

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", mapper)
    return svc._build_seeded_target_circe({
        "targetCohortName": TARGET,
        "inclusionCriteria": [json.loads(json.dumps(CRITERION))],
        "exclusionCriteria": [],
    })


def test_should_list_the_criterion_under_the_mapping_failure_record(carmelina_circe):
    from src.utils.circe_lint import MAPPING_FAILURE_CRITERIA_KEY

    rows = [row for row in carmelina_circe[MAPPING_FAILURE_CRITERIA_KEY]
            if row["criterionId"] == "9"]

    assert [(row["role"], row["label"]) for row in rows] == [("inclusion", SEED)]
    assert [f["stage"] for f in rows[0]["failures"]] == ["reranker_no_match"]


def test_should_fail_the_gate_on_the_criterion_mapped_over_a_no_match(carmelina_circe):
    from scripts.verify_circe_delivery import mapping_failure_findings

    failures, clause = mapping_failure_findings(carmelina_circe)

    assert clause == ""
    [finding] = failures
    assert finding.startswith("mapped with a recorded failure (")
    assert f"inclusion #9 '{SEED}' [reranker_no_match: " in finding, finding
