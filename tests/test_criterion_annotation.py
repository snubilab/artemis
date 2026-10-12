"""RFC-016 step 1: the annotation step and ``record_requirement``.

Every case is a real row: the 2026-10-12 prompt_f2 candidate store and ARISTOTLE's Agent 1
IR cache, copied verbatim into ``tests/fixtures/rfc016_store_rows.json`` (with the source
files' SHA-256). The model is a stub everywhere; the mapper is a stub, and Agent 2's
workflow, query expander and retriever raise on construction, so nothing here reaches an
LLM, ChromaDB, Postgres or Neo4j.

What is pinned:

* a fragment the model quotes is kept only when it is a substring of ``protocolLine``;
  otherwise the field is absent and the rejection is recorded on the row;
* the annotation runs inside ``process_eligibility`` before Agent 2 mapping, and its cache
  path is isolatable by env;
* a rule whose accepted annotation says ``conditional`` is not emitted and is recorded under
  ``conditional-on-existing-record`` with its span; without an accepted annotation the rule
  is emitted exactly as an ordinary presence rule (no word-list skip any more);
* a row Agent 1 flagged ``conditional`` reaches the store and is recorded as a skip instead of
  disappearing in ``_criteria_from_ir``.
"""
from __future__ import annotations

import json
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation_mod
from src.services.criterion_annotation import (
    ANNOTATION_KEY,
    ANNOTATION_REJECTED_KEY,
    CONDITIONAL_REASON,
    annotate_row,
    validate_annotation,
)
from src.services.tte_service import TTEService

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_store_rows.json").read_text()
)
CARMELINA_7 = FIXTURE["carmelina_inclusion_7"]
CAROLINA_37 = FIXTURE["carolina_inclusion_37"]
CAROLINA_38 = FIXTURE["carolina_inclusion_38"]
WOCBP_IR = FIXTURE["aristotle_ir_wocbp"]

#: A fragment of CARMELINA 7's own protocol line.
CARMELINA_SPAN = "Stable antidiabetic background medication (unchanged daily dose)"
#: A fragment of CAROLINA 37's own protocol line.
CAROLINA_SPAN = "Stable anti-diabetic background medication (unchanged daily dose)"
#: A fragment of the WOCBP line.
WOCBP_SPAN = "Women of childbearing potential (WOCBP)"


def _conditional(span: str) -> dict[str, Any]:
    return {"record_requirement": "conditional", "conditional_span": span, "excepted_entities": []}


def _annotated(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """``row`` carrying the annotation the step would store for ``payload``."""
    row = deepcopy(row)
    fields, rejected = validate_annotation(payload, row["protocolLine"])
    row[ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    if rejected:
        row[ANNOTATION_REJECTED_KEY] = rejected
    return row


class _StubLLM:
    """Answers every call with ``payload``; records each rendered message list."""

    def __init__(self, payload: Any, *, fail: Exception | None = None) -> None:
        self.payload = payload
        self.fail = fail
        self.calls: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append("\n\n".join(str(m.content) for m in messages))
        if self.fail is not None:
            raise self.fail
        return AIMessage(content=json.dumps(self.payload))


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation_mod.reset_for_tests()
    yield
    annotation_mod.reset_for_tests()


class TestTheSpanCheck:
    def test_should_accept_conditional_when_its_span_is_in_the_protocol_line(self):
        fields, rejected = validate_annotation(
            _conditional(CARMELINA_SPAN), CARMELINA_7["protocolLine"]
        )
        assert rejected == []
        assert fields["record_requirement"] == "conditional"
        assert fields["conditional_span"] == CARMELINA_SPAN

    def test_should_reject_conditional_when_its_span_is_not_in_the_protocol_line(self):
        fields, rejected = validate_annotation(
            _conditional("Stable antidiabetic background medication for 8 weeks"),
            CARMELINA_7["protocolLine"],
        )
        assert fields["record_requirement"] is None
        assert fields["conditional_span"] is None
        assert [r["field"] for r in rejected] == ["record_requirement"]

    def test_should_reject_an_excepted_entity_when_its_span_is_not_in_the_protocol_line(self):
        fields, rejected = validate_annotation(
            {
                "record_requirement": "required",
                "conditional_span": None,
                "excepted_entities": [{"text": "insulin", "span": "insulin"}],
            },
            CARMELINA_7["protocolLine"],
        )
        assert fields["record_requirement"] == "required"
        assert fields["excepted_entities"] == []
        assert [r["field"] for r in rejected] == ["excepted_entities"]

    def test_should_reject_a_value_outside_the_three_when_the_model_invents_one(self):
        fields, rejected = validate_annotation(
            {"record_requirement": "optional"}, CARMELINA_7["protocolLine"]
        )
        assert fields["record_requirement"] is None
        assert [r["field"] for r in rejected] == ["record_requirement"]


class TestAnnotatingARow:
    def test_should_store_the_annotation_when_the_model_answers_with_a_span_in_the_line(self):
        row = deepcopy(CARMELINA_7)
        llm = _StubLLM(_conditional(CARMELINA_SPAN))
        outcome = annotate_row(row, [], "inclusion", model="stub", llm=llm)
        assert outcome == "called"
        assert row[ANNOTATION_KEY]["record_requirement"] == "conditional"
        assert row[ANNOTATION_KEY]["conditional_span"] == CARMELINA_SPAN
        assert ANNOTATION_REJECTED_KEY not in row
        # The prompt carries the protocol line and the extracted fields.
        assert CARMELINA_7["protocolLine"] in llm.calls[0]
        assert CARMELINA_7["description"] in llm.calls[0]

    def test_should_record_the_rejection_on_the_row_when_the_span_is_not_in_the_line(self):
        row = deepcopy(CARMELINA_7)
        annotate_row(
            row, [], "inclusion", model="stub", llm=_StubLLM(_conditional("for 8 weeks prior"))
        )
        assert row[ANNOTATION_KEY]["record_requirement"] is None
        assert row[ANNOTATION_REJECTED_KEY][0]["field"] == "record_requirement"
        assert row[ANNOTATION_REJECTED_KEY][0]["value"]["conditional_span"] == "for 8 weeks prior"

    def test_should_not_call_the_model_again_when_the_cache_holds_the_answer(self, tmp_path):
        first, second = deepcopy(CARMELINA_7), deepcopy(CARMELINA_7)
        annotate_row(first, [], "inclusion", model="stub", llm=_StubLLM(_conditional(CARMELINA_SPAN)))
        again = _StubLLM(_conditional("unused"))
        assert annotate_row(second, [], "inclusion", model="stub", llm=again) == "cached"
        assert again.calls == []
        assert second[ANNOTATION_KEY] == first[ANNOTATION_KEY]
        assert (tmp_path / "annotations.jsonl").exists()

    def test_should_call_again_when_an_extracted_field_changes(self):
        row = deepcopy(CARMELINA_7)
        annotate_row(row, [], "inclusion", model="stub", llm=_StubLLM(_conditional(CARMELINA_SPAN)))
        changed = dict(deepcopy(CARMELINA_7), logicType="ABSENCE")
        llm = _StubLLM(_conditional(CARMELINA_SPAN))
        assert annotate_row(changed, [], "inclusion", model="stub", llm=llm) == "called"

    def test_should_write_the_cache_where_the_env_points(self, tmp_path, monkeypatch):
        elsewhere = tmp_path / "run_b" / "cache.jsonl"
        monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(elsewhere))
        annotate_row(
            deepcopy(CARMELINA_7), [], "inclusion", model="stub",
            llm=_StubLLM(_conditional(CARMELINA_SPAN)),
        )
        assert elsewhere.exists()
        assert not (tmp_path / "annotations.jsonl").exists()

    def test_should_record_the_error_and_cache_nothing_when_the_model_fails(self, tmp_path):
        row = deepcopy(CARMELINA_7)
        outcome = annotate_row(
            row, [], "inclusion", model="stub", llm=_StubLLM(None, fail=RuntimeError("down"))
        )
        assert outcome == "error"
        assert "down" in row[ANNOTATION_KEY]["error"]
        assert not (tmp_path / "annotations.jsonl").exists()

    def test_should_leave_a_row_alone_when_it_has_no_protocol_line(self):
        row = dict(deepcopy(CARMELINA_7), protocolLine="")
        llm = _StubLLM(_conditional(CARMELINA_SPAN))
        assert annotate_row(row, [], "inclusion", model="stub", llm=llm) == "no-line"
        assert llm.calls == []
        assert ANNOTATION_KEY not in row


# --------------------------------------------------------------------------- #
# The build
# --------------------------------------------------------------------------- #


def _stub_concept_set(seed: str, domain: str) -> dict[str, Any]:
    concept_id = zlib.crc32(seed.encode()) % 10**8
    return {
        "name": seed,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": seed,
                        "CONCEPT_CODE": str(concept_id),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "RxNorm" if domain == "Drug" else "SNOMED",
                        "CONCEPT_CLASS_ID": "Ingredient" if domain == "Drug" else "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
        "mapping_metadata": None,
    }


class _Agent2IsStubbed:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Agent 2 is stubbed out in this test")


@pytest.fixture
def service(monkeypatch) -> TTEService:
    monkeypatch.setattr("src.agents.agent2.workflow.Agent2Workflow", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.query_expander.QueryExpander", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.retriever.ConceptRetriever", _Agent2IsStubbed)
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        domain = kwargs.get("expected_domain") or "Drug"
        return _stub_concept_set(seed_text.strip(), domain)

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    return svc


def _eligibility(inclusion=(), exclusion=()) -> dict[str, Any]:
    return {
        "targetCohortName": "linagliptin",
        "inclusionCriteria": deepcopy(list(inclusion)),
        "exclusionCriteria": deepcopy(list(exclusion)),
    }


def _skips(circe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["criterionId"]: r for r in circe["_skippedCriteria"]}


class TestTheBuildReadsRecordRequirement:
    def test_should_record_a_conditional_skip_when_the_annotation_says_conditional(self, service):
        row = _annotated(CARMELINA_7, _conditional(CARMELINA_SPAN))
        circe = service._build_seeded_target_circe(_eligibility(inclusion=[row]))
        assert circe["InclusionRules"] == []
        skip = _skips(circe)["7"]
        assert skip["reason"] == CONDITIONAL_REASON
        assert skip["conditionalSpan"] == CARMELINA_SPAN
        assert skip["conditionalDecidedBy"] == "7"
        assert skip["conditionalSource"] == "annotation"
        assert circe["_generationCensus"]["skippedByReason"] == {CONDITIONAL_REASON: 1}

    def test_should_emit_the_rule_as_before_when_the_row_carries_no_annotation(self, service):
        """The default behaviour: no word list decides anything any more."""
        circe = service._build_seeded_target_circe(_eligibility(inclusion=[CARMELINA_7]))
        assert len(circe["InclusionRules"]) == 1
        assert circe["_skippedCriteria"] == []

    def test_should_emit_the_rule_and_keep_the_rejection_when_the_span_is_not_in_the_line(
        self, service
    ):
        row = _annotated(CARMELINA_7, _conditional("for at least 8 weeks prior to randomization"))
        assert row[ANNOTATION_REJECTED_KEY][0]["field"] == "record_requirement"
        circe = service._build_seeded_target_circe(_eligibility(inclusion=[row]))
        assert len(circe["InclusionRules"]) == 1
        assert circe["_skippedCriteria"] == []

    def test_should_take_the_members_with_it_when_a_group_label_is_conditional(self, service):
        label = _annotated(CAROLINA_37, _conditional(CAROLINA_SPAN))
        member = _annotated(CAROLINA_38, {"record_requirement": "required"})
        circe = service._build_seeded_target_circe(_eligibility(inclusion=[label, member]))
        assert circe["InclusionRules"] == []
        skips = _skips(circe)
        assert {cid: skips[cid]["reason"] for cid in skips} == {
            "37": CONDITIONAL_REASON,
            "38": CONDITIONAL_REASON,
        }
        assert skips["38"]["conditionalDecidedBy"] == "37"
        assert skips["38"]["conditionalSpan"] == CAROLINA_SPAN

    def test_should_skip_an_exclusion_too_when_its_annotation_says_conditional(self, service):
        row = dict(_annotated(CARMELINA_7, _conditional(CARMELINA_SPAN)), logicType="ABSENCE")
        circe = service._build_seeded_target_circe(_eligibility(exclusion=[row]))
        assert circe["InclusionRules"] == []
        assert _skips(circe)["7"]["role"] == "exclusion"


class TestAgent1ConditionalFlagIsRecordedNotDropped:
    @staticmethod
    def _ir_rows() -> list[dict[str, Any]]:
        from src.models.ir import Criteria

        item = Criteria.model_validate(WOCBP_IR)
        assert item.conditional is True
        svc = TTEService.__new__(TTEService)
        return svc._criteria_from_ir([item])

    def test_should_write_a_store_row_when_agent1_flagged_the_criterion_conditional(self):
        rows = self._ir_rows()
        assert len(rows) == 1
        assert rows[0]["conditional"] is True
        assert rows[0]["protocolLine"] == WOCBP_IR["source_text"]

    def test_should_record_a_skip_for_it_in_the_build(self, service):
        rows = self._ir_rows()
        circe = service._build_seeded_target_circe(_eligibility(inclusion=rows))
        assert circe["InclusionRules"] == []
        skip = _skips(circe)["1"]
        assert skip["reason"] == CONDITIONAL_REASON
        assert skip["conditionalSource"] == "extraction"
        assert skip["conditionalSpan"] is None

    def test_should_carry_the_annotation_span_when_the_annotation_agrees(self, service):
        row = _annotated(self._ir_rows()[0], _conditional(WOCBP_SPAN))
        circe = service._build_seeded_target_circe(_eligibility(inclusion=[row]))
        skip = _skips(circe)["1"]
        assert (skip["conditionalSource"], skip["conditionalSpan"]) == ("annotation", WOCBP_SPAN)


class TestProcessEligibilityAnnotatesBeforeMapping:
    def test_should_hand_annotated_rows_to_the_mapping_step(self, monkeypatch):
        from src.models.ir import ProvisionalSectionSource, ProvisionalStudyIR

        svc = TTEService(store=MagicMock())
        llm = _StubLLM(_conditional(CARMELINA_SPAN))
        monkeypatch.setattr(annotation_mod, "_build_llm", lambda model: llm)
        seen: dict[str, Any] = {}

        def fake_build(eligibility: dict[str, Any]) -> dict[str, Any]:
            seen["rows"] = deepcopy(eligibility["inclusionCriteria"])
            return {
                "ConceptSets": [],
                "PrimaryCriteria": {"CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}]},
                "InclusionRules": [],
            }

        section = MagicMock(spec=ProvisionalSectionSource)
        section.source, section.fallback_used, section.fragments = "test", False, []
        with (
            patch.object(svc, "_build_seeded_target_circe", side_effect=fake_build),
            patch.object(svc, "_build_eligibility_suggestion", return_value={
                "targetCohortName": "Type 2 diabetes",
                "inclusionCriteria": [deepcopy(CARMELINA_7)],
                "exclusionCriteria": [],
            }),
            patch.object(svc, "_build_mapping_quality_signal", return_value=None),
            patch.object(svc, "_get_capability_signal", return_value=None),
            patch.object(svc, "_apply_draft_concept_set_metadata", side_effect=lambda c, *a: c),
            patch("src.services.tte_service.SuggestionArtifactMeta") as meta_cls,
        ):
            meta_cls.return_value.model_dump.return_value = {}
            payload, _meta, status = svc._build_process_eligibility_artifact_payload(
                study={"id": 9, "name": "CARMELINA"},
                provisional_ir=MagicMock(spec=ProvisionalStudyIR),
                section_source=section,
            )
        assert status == "completed"
        assert len(llm.calls) == 1
        assert seen["rows"][0][ANNOTATION_KEY]["record_requirement"] == "conditional"
        stored = payload["proposedChanges"]["eligibility"]["inclusionCriteria"][0]
        assert stored[ANNOTATION_KEY]["conditional_span"] == CARMELINA_SPAN
