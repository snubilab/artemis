"""A refusal that does not say why is not a refusal, it is a silence.

`_map_criterion` recorded ``"reason": str(e)``, and ``str(e)`` is the EMPTY STRING for
every exception carrying no message -- ``TimeoutError()`` chief among them. Measured over
the live study state of ``tmp/tte_cold6_20260908/studies.json``, 3 of its 11
``_unmappedCriteria`` rows carry ``reason: ""`` (PLATO 16, ARISTOTLE 26/27); they reach
the twelve delivered files as 6 rows, one per arm, and the delivery gate refuses all
twelve because of them. It is right to. (Pooling in the artifact proposal payloads gives
24 of 68 -- a different population, and not the one the gate judges.)

Measured cause, ``tmp/tte_cold6_20260908/cold6c.log`` lines 1013-1018 and 3415-3421:
Agent 2 returned no seeds (the reranker rejected all 60 candidates, exact concept_name
0 matches), the RAG fallback ran, and ``stage1_pipeline.search_sync``'s
``onto_future.result(timeout=5.0)`` raised ``TimeoutError()``. An infrastructure timeout,
recorded as if it were a mapping verdict, with no text at all.

Two things close it, and both are pinned here:

* the record carries the exception CLASS as well as its message, so the reason is
  non-empty even when ``str(e)`` is, and names the stage when the exception was
  explicitly chained;
* a DELIBERATE mapper refusal raises :class:`CriterionRefused` with a code from a
  closed vocabulary, so a consumer can tell "the mapper decided no" (``refusalCode``
  set) from "something failed" (``refusalCode is None``) without parsing prose.

No module globals and no import-order dependency: every fixture builds its own service.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.tte_service import TTEService
from src.utils.criterion_refusal import (
    REFUSAL_NO_CONCEPT_MAPPING,
    CriterionRefused,
)

UNMAPPABLE = "qqzzxx nonexistent clinical term"


def _stub_concept_set(name: str, concept_id: int, domain: str = "Condition") -> dict[str, Any]:
    return {
        "name": name,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": name,
                        "CONCEPT_CODE": str(concept_id),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
        "mapping_metadata": None,
    }


def _eligibility() -> dict[str, Any]:
    return {
        "targetCohortName": "empagliflozin",
        "inclusionCriteria": [
            {"id": "inc-1", "domain": "Condition", "sourceText": "Type 2 diabetes mellitus"},
        ],
        "exclusionCriteria": [
            {"id": "exc-1", "domain": "Condition", "sourceText": UNMAPPABLE},
        ],
    }


def _record_for(monkeypatch: pytest.MonkeyPatch, failure: BaseException) -> dict[str, Any]:
    """Map one study whose single exclusion raises ``failure``; return its record."""
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        if seed_text.strip() == UNMAPPABLE:
            raise failure
        if seed_text.strip() == "empagliflozin":
            return _stub_concept_set("empagliflozin", 1594973, "Drug")
        return _stub_concept_set(seed_text.strip(), 201826)

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    circe = svc._build_seeded_target_circe(_eligibility())
    unmapped = circe.get("_unmappedCriteria") or []
    assert len(unmapped) == 1, "the dropped criterion left no record at all"
    return unmapped[0]


class TestTheReasonIsNeverEmpty:
    def test_should_name_the_class_when_the_exception_carries_no_message(self, monkeypatch):
        """The real six rows: `str(TimeoutError())` is "" and said nothing."""
        record = _record_for(monkeypatch, TimeoutError())
        assert record["reason"].strip(), "a refusal recorded no reason at all"
        assert record["reason"] == "TimeoutError: TimeoutError()"
        assert record["exceptionType"] == "builtins.TimeoutError"

    def test_should_mark_an_infrastructure_failure_as_having_no_refusal_code(self, monkeypatch):
        """A timeout is not a verdict. Nothing may read it as one."""
        record = _record_for(monkeypatch, TimeoutError())
        assert record["refusalCode"] is None
        assert record["refusalDetail"] is None

    def test_should_carry_the_code_when_the_mapper_deliberately_refused(self, monkeypatch):
        record = _record_for(
            monkeypatch,
            CriterionRefused(
                f"No concept mapping found for '{UNMAPPABLE}'",
                code=REFUSAL_NO_CONCEPT_MAPPING,
            ),
        )
        assert record["refusalCode"] == "no-concept-mapping"
        assert "No concept mapping found" in record["reason"]
        assert record["exceptionType"] == "src.utils.criterion_refusal.CriterionRefused"

    def test_should_name_both_stages_when_the_failure_was_chained(self, monkeypatch):
        """The fallback failed AFTER Agent 2 did; a record naming one hides the other."""
        try:
            raise ValueError("boom") from RuntimeError("agent2 died")
        except ValueError as chained:
            record = _record_for(monkeypatch, chained)
        assert "ValueError: boom" in record["reason"]
        assert " — after RuntimeError: agent2 died" in record["reason"]

    def test_should_keep_the_census_balanced_with_the_new_fields_present(self, monkeypatch):
        """total == mapped + unmapped + demographicRules + skipped, unchanged."""
        svc = TTEService.__new__(TTEService)

        def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
            if seed_text.strip() == UNMAPPABLE:
                raise TimeoutError()
            if seed_text.strip() == "empagliflozin":
                return _stub_concept_set("empagliflozin", 1594973, "Drug")
            return _stub_concept_set(seed_text.strip(), 201826)

        monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
        circe = svc._build_seeded_target_circe(_eligibility())
        census = circe["_generationCensus"]
        assert census["total"] == (
            census["mapped"]
            + census["unmapped"]
            + census["demographicRules"]
            + census["skipped"]
        )
        assert census["unmapped"] == 1


class TestTheRefusalVocabularyIsClosed:
    def test_should_refuse_to_construct_a_refusal_with_no_message(self):
        """A `CriterionRefused` that says nothing would reintroduce the empty reason."""
        with pytest.raises(ValueError):
            CriterionRefused("   ", code=REFUSAL_NO_CONCEPT_MAPPING)

    def test_should_refuse_a_code_outside_the_vocabulary(self):
        """The code is a machine key, so a typo must fail here, not at the gate."""
        with pytest.raises(ValueError):
            CriterionRefused("a real message", code="made-up")

    def test_should_expose_the_code_and_detail_it_was_given(self):
        exc = CriterionRefused("m", code=REFUSAL_NO_CONCEPT_MAPPING, detail="router said no")
        assert exc.code == REFUSAL_NO_CONCEPT_MAPPING
        assert exc.detail == "router said no"
        assert isinstance(exc, ValueError)


class TestTheRealMechanism:
    """The five-second ontology timeout, reproduced through the real pipeline.

    Everything from `_map_criterion` down to `concurrent.futures.Future.result` is the
    shipped code here: the real `ConceptSetRecommender`, the real `Stage2Pipeline`, the
    real `Stage1Pipeline`, and a real `TimeoutError` raised by a real future that really
    did not finish in time. Only the two leaf searchers are stubs -- one slow, one fast --
    because a genuine timeout needs something genuinely slow to wait on.

    Nothing in this test constructs a `TimeoutError`, which is the point. A test that
    raises the exception itself proves the recording; only this one proves that what the
    pipeline raises when the ontology search hangs is an exception with an empty `str()`,
    which is the fact the whole defect rested on.
    """

    @staticmethod
    def _pipeline_that_times_out():
        import time

        from src.agents.conceptset.recommender import ConceptSetRecommender
        from src.agents.conceptset.stage1_pipeline import Stage1Pipeline
        from src.agents.conceptset.stage2_pipeline import Stage2Pipeline

        rag = type("_Rag", (), {"search": staticmethod(lambda *a, **k: [])})()
        onto = type(
            "_Onto",
            (),
            # Longer than the 5.0s deadline the pipeline itself sets, by enough that the
            # timeout is not a race, and short enough that the worker is finished a
            # couple of seconds after the test stops waiting on it.
            {"search_by_name": staticmethod(lambda *a, **k: time.sleep(7.0) or [])},
        )()
        stage1 = Stage1Pipeline(rag_search=rag, ontology_search=onto)
        stage2 = Stage2Pipeline(stage1=stage1, phoebe=MagicMock())

        router = MagicMock()
        router.route.return_value = SimpleNamespace(
            fallback_to=None, fallback_reason=None, include=["clopidogrel"], exclude=[]
        )
        cache = MagicMock()
        cache.get.return_value = None
        return ConceptSetRecommender(nlu_router=router, stage2=stage2, cache=cache)

    def test_the_shipped_pipeline_raises_an_exception_whose_str_is_empty(self):
        """The premise of the defect, measured rather than assumed."""
        recommender = self._pipeline_that_times_out()
        with pytest.raises(TimeoutError) as caught:
            recommender.recommend("Contraindication to clopidogrel", top_k=5)
        assert str(caught.value) == "", (
            "the diagnosis said this exception carries no message; it now does, so the "
            "reason for the fix has changed and this test should be re-read"
        )

    def test_should_record_a_reason_for_that_real_timeout(self, monkeypatch):
        """End to end: the real timeout, through the real fallback, into the record."""
        svc = TTEService.__new__(TTEService)
        recommender = self._pipeline_that_times_out()
        monkeypatch.setenv("CRITERION_CACHE_ENABLED", "false")
        monkeypatch.setattr(svc, "_get_seeded_concept_set_recommender", lambda: recommender)
        monkeypatch.setattr(
            svc,
            "_recommend_seeded_concept_set",
            lambda seed_text, **kw: (
                _stub_concept_set("empagliflozin", 1594973, "Drug")
                if seed_text.strip() == "empagliflozin"
                else svc._recommend_seeded_concept_set_rag_fallback(
                    " ".join(seed_text.split()).strip(),
                    expected_domain=kw.get("expected_domain"),
                )
            ),
        )

        eligibility = _eligibility()
        eligibility["inclusionCriteria"][0]["sourceText"] = "Contraindication to clopidogrel"
        eligibility["exclusionCriteria"] = []

        circe = svc._build_seeded_target_circe(eligibility)
        unmapped = circe.get("_unmappedCriteria") or []
        assert len(unmapped) == 1
        record = unmapped[0]
        assert record["reason"].strip(), "the real timeout recorded no reason again"
        assert record["exceptionType"] == "builtins.TimeoutError"
        assert record["refusalCode"] is None, "a timeout is not a mapping verdict"
