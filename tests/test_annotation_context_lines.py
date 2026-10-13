"""The annotation step reads the trial's other lines of the criterion's role, for one decision.

CARMELINA inclusion 7 ("Stable antidiabetic background medication (unchanged daily dose) for
at least 8 weeks prior to") states a requirement when it is read alone. What makes it
conditional is another line of the same role, inclusion 2, which admits patients who are
drug-naive. Shown only its own line, the model answered ``required`` and the P3 dry rebuild
emitted the row as a drug presence rule -- the 2026-09-23 comparator-collapse shape.

Every row here is real: CARMELINA's inclusion role and two exclusion rows from the P3 dry
rebuild's arm A store, copied verbatim into ``tests/fixtures/annotation_context_rows.json``
(with the source file's SHA-256). The model is a stub everywhere; nothing reaches an LLM.

What is pinned:

* the prompt shows every other ``protocolLine`` of the row's role once, in store order, and
  no line of the other role; ``none`` when the role holds no other line;
* ``conditional_span`` is accepted from the row's own line (recorded with no source line) or
  from one of the lines shown (recorded with that line verbatim); every other fragment is
  still checked against the row's own line only;
* the build skips a row on a recorded source line only when that line is the
  ``protocolLine`` of a row of the same role and holds the span, and the skip record carries
  the line, so the delivery gate re-checks it without re-deriving the context.
"""

from __future__ import annotations

import json
import os
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation_mod
from src.services.criterion_annotation import (
    ANNOTATION_KEY,
    ANNOTATION_REJECTED_KEY,
    CONDITIONAL_REASON,
    annotate_eligibility,
    conditional_skips,
    validate_annotation,
)
from src.services.tte_service import TTEService

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "annotation_context_rows.json").read_text()
)
INCLUSION: list[dict[str, Any]] = FIXTURE["inclusionCriteria"]
EXCLUSION: list[dict[str, Any]] = FIXTURE["exclusionCriteria"]
ROW_2 = next(r for r in INCLUSION if r["id"] == 2)
ROW_7 = next(r for r in INCLUSION if r["id"] == 7)
EXC_35 = next(r for r in EXCLUSION if r["id"] == 35)

#: A fragment of inclusion 2's line -- the subgroup that makes inclusion 7 conditional.
SPAN_FROM_ROW_2 = "drug-naïve or pre-treated with any antidiabetic background therapy"
#: A fragment of inclusion 7's own line.
SPAN_FROM_ROW_7 = "Stable antidiabetic background medication (unchanged daily dose)"
#: A fragment of exclusion 35's line: real, conditional for its own row, and the other role.
SPAN_FROM_EXC_35 = "Pre-menopausal women"

HEADING = "The trial's other {role} lines:\n"


def _without_annotations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = deepcopy(rows)
    for row in rows:
        row.pop(ANNOTATION_KEY, None)
        row.pop(ANNOTATION_REJECTED_KEY, None)
    return rows


def _conditional(span: str) -> dict[str, Any]:
    return {"record_requirement": "conditional", "conditional_span": span, "excepted_entities": []}


def _other_lines(row: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    """The role's distinct protocol lines in store order, the row's own left out."""
    own = row["protocolLine"]
    return [line for line in dict.fromkeys(r["protocolLine"] for r in rows) if line != own]


def _context_block(user_prompt: str, role: str) -> str:
    heading = HEADING.format(role=role)
    assert heading in user_prompt, "the prompt carries no context heading"
    return user_prompt.split(heading, 1)[1].split("\n\nExtracted criterion:", 1)[0]


class _Recorder:
    """Stands in for the chat model: records (system, user) per call, answers ``payload``."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        system, user = (str(m.content) for m in messages)
        self.calls.append((system, user))
        return AIMessage(content=json.dumps(self.payload))

    def user_prompt_of(self, row: dict[str, Any]) -> str:
        prefix = f"Protocol line:\n{row['protocolLine']}\n\n"
        found = [user for _system, user in self.calls if user.startswith(prefix)]
        assert len(found) == 1, f"{len(found)} calls for row {row['id']}"
        return found[0]


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation_mod.reset_for_tests()
    yield
    annotation_mod.reset_for_tests()


def _annotate(eligibility: dict[str, Any], payload: Any) -> _Recorder:
    recorder = _Recorder(payload)
    with patch.object(annotation_mod, "_build_llm", lambda _model: recorder):
        annotate_eligibility(eligibility, model="stub-model")
    return recorder


# --------------------------------------------------------------------------- #
# The prompt
# --------------------------------------------------------------------------- #


class TestThePromptShowsTheRolesOtherLines:
    def test_should_show_each_other_line_of_the_role_once_in_store_order_when_annotating_a_row(
        self,
    ):
        eligibility = {
            "inclusionCriteria": _without_annotations(INCLUSION),
            "exclusionCriteria": _without_annotations(EXCLUSION),
        }
        recorder = _annotate(eligibility, _conditional(SPAN_FROM_ROW_2))
        block = _context_block(recorder.user_prompt_of(ROW_7), "inclusion")
        expected = [" ".join(line.split()) for line in _other_lines(ROW_7, INCLUSION)]
        assert len(expected) >= 2
        assert block.split("\n") == [f"- {line}" for line in expected]

    def test_should_show_no_line_of_the_other_role_when_annotating_a_row(self):
        eligibility = {
            "inclusionCriteria": _without_annotations(INCLUSION),
            "exclusionCriteria": _without_annotations(EXCLUSION),
        }
        recorder = _annotate(eligibility, _conditional(SPAN_FROM_ROW_2))
        inclusion_block = _context_block(recorder.user_prompt_of(ROW_7), "inclusion")
        exclusion_block = _context_block(recorder.user_prompt_of(EXC_35), "exclusion")
        for row in EXCLUSION:
            assert " ".join(row["protocolLine"].split()) not in inclusion_block
        for row in INCLUSION:
            assert " ".join(row["protocolLine"].split()) not in exclusion_block

    def test_should_show_none_when_the_role_holds_no_other_line(self):
        eligibility = {"inclusionCriteria": _without_annotations([ROW_7]), "exclusionCriteria": []}
        recorder = _annotate(eligibility, _conditional(SPAN_FROM_ROW_7))
        assert _context_block(recorder.user_prompt_of(ROW_7), "inclusion") == "none"

    def test_should_call_the_model_again_when_another_line_of_the_role_changes(self):
        first = {"inclusionCriteria": _without_annotations([ROW_2, ROW_7]), "exclusionCriteria": []}
        _annotate(first, _conditional(SPAN_FROM_ROW_7))
        changed_row_2 = dict(_without_annotations([ROW_2])[0], protocolLine="Documented diagnosis")
        second = {
            "inclusionCriteria": [changed_row_2, _without_annotations([ROW_7])[0]],
            "exclusionCriteria": [],
        }
        recorder = _annotate(second, _conditional(SPAN_FROM_ROW_7))
        assert recorder.user_prompt_of(ROW_7)  # row 7 was called again, not served from cache


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


class TestTheConditionalSpanMayComeFromALineShown:
    CONTEXT = _other_lines(ROW_7, INCLUSION)

    def test_should_accept_conditional_and_record_the_line_when_the_span_is_in_a_line_shown(self):
        fields, rejected = validate_annotation(
            _conditional(SPAN_FROM_ROW_2), ROW_7["protocolLine"], self.CONTEXT
        )
        assert rejected == []
        assert fields["record_requirement"] == "conditional"
        assert fields["conditional_span"] == SPAN_FROM_ROW_2
        assert fields["conditional_span_line"] == ROW_2["protocolLine"]

    def test_should_record_no_line_when_the_span_is_in_the_rows_own_line(self):
        fields, rejected = validate_annotation(
            _conditional(SPAN_FROM_ROW_7), ROW_7["protocolLine"], self.CONTEXT
        )
        assert rejected == []
        assert fields["conditional_span"] == SPAN_FROM_ROW_7
        assert fields["conditional_span_line"] is None

    def test_should_reject_conditional_when_the_span_is_in_no_line_shown(self):
        fields, rejected = validate_annotation(
            _conditional(SPAN_FROM_EXC_35), ROW_7["protocolLine"], self.CONTEXT
        )
        assert fields["record_requirement"] is None
        assert fields["conditional_span"] is None
        assert fields["conditional_span_line"] is None
        assert [r["field"] for r in rejected] == ["record_requirement"]

    def test_should_reject_a_span_from_another_line_when_no_line_is_shown(self):
        fields, rejected = validate_annotation(_conditional(SPAN_FROM_ROW_2), ROW_7["protocolLine"])
        assert fields["record_requirement"] is None
        assert [r["field"] for r in rejected] == ["record_requirement"]

    @pytest.mark.parametrize(
        "payload, field",
        [
            (
                {"excepted_entities": [{"text": "GLP-1 receptor agonists",
                                        "span": "GLP-1 receptor agonists"}]},
                "excepted_entities",
            ),
            (
                {"relation": "any", "relation_span": "drug-naïve or pre-treated"},
                "relation",
            ),
            (
                {"timing": "prior", "window_span": "prior to randomization"},
                "timing",
            ),
            (
                {"no_entity": "refers_elsewhere",
                 "no_entity_span": "excluding treatment with GLP-1 receptor agonists"},
                "no_entity",
            ),
        ],
    )
    def test_should_check_every_other_span_against_the_own_line_only_when_lines_are_shown(
        self, payload, field
    ):
        base = {"record_requirement": "required", "conditional_span": None, "excepted_entities": []}
        _fields, rejected = validate_annotation(
            {**base, **payload}, ROW_7["protocolLine"], self.CONTEXT
        )
        assert [r["field"] for r in rejected] == [field]

    def test_should_store_the_line_on_the_row_when_the_step_accepts_a_span_from_a_line_shown(
        self,
    ):
        eligibility = {
            "inclusionCriteria": _without_annotations(INCLUSION),
            "exclusionCriteria": [],
        }
        _annotate(eligibility, _conditional(SPAN_FROM_ROW_2))
        rows = {r["id"]: r for r in eligibility["inclusionCriteria"]}
        assert rows[7][ANNOTATION_KEY]["conditional_span_line"] == ROW_2["protocolLine"]
        assert rows[2][ANNOTATION_KEY]["conditional_span_line"] is None


# --------------------------------------------------------------------------- #
# The build
# --------------------------------------------------------------------------- #


def _rows_with_row_7_annotated(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _without_annotations(INCLUSION)
    next(r for r in rows if r["id"] == 7)[ANNOTATION_KEY] = {
        "promptVersion": "test", "model": "stub", **annotation
    }
    return rows


def _context_annotation(span: str, line: str | None) -> dict[str, Any]:
    return {"record_requirement": "conditional", "conditional_span": span,
            "conditional_span_line": line}


class TestTheBuildReChecksTheRecordedLine:
    def test_should_skip_the_row_when_its_span_is_in_the_recorded_line_of_its_role(self):
        rows = _rows_with_row_7_annotated(
            _context_annotation(SPAN_FROM_ROW_2, ROW_2["protocolLine"])
        )
        decision = conditional_skips(rows)["7"]
        assert (decision.span, decision.span_line, decision.decided_by) == (
            SPAN_FROM_ROW_2, ROW_2["protocolLine"], "7"
        )

    def test_should_not_skip_the_row_when_the_recorded_line_is_a_line_of_the_other_role(self):
        rows = _rows_with_row_7_annotated(
            _context_annotation(SPAN_FROM_EXC_35, EXC_35["protocolLine"])
        )
        assert "7" not in conditional_skips(rows)

    def test_should_not_skip_the_row_when_the_span_is_not_in_the_recorded_line(self):
        rows = _rows_with_row_7_annotated(
            _context_annotation(SPAN_FROM_EXC_35, ROW_2["protocolLine"])
        )
        assert "7" not in conditional_skips(rows)

    def test_should_not_skip_the_row_when_no_line_is_recorded_and_the_span_is_elsewhere(self):
        rows = _rows_with_row_7_annotated(_context_annotation(SPAN_FROM_ROW_2, None))
        assert "7" not in conditional_skips(rows)


def _stub_concept_set(seed: str, domain: str) -> dict[str, Any]:
    concept_id = zlib.crc32(seed.encode()) % 10**8
    return {
        "name": seed,
        "domain": domain,
        "expression": {"items": [{
            "concept": {
                "CONCEPT_ID": concept_id, "CONCEPT_NAME": seed, "CONCEPT_CODE": str(concept_id),
                "DOMAIN_ID": domain, "VOCABULARY_ID": "RxNorm" if domain == "Drug" else "SNOMED",
                "CONCEPT_CLASS_ID": "Ingredient" if domain == "Drug" else "Clinical Finding",
            },
            "includeDescendants": True,
            "isExcluded": False,
        }]},
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
        return _stub_concept_set(seed_text.strip(), kwargs.get("expected_domain") or "Drug")

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    return svc


def _built(service: TTEService, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return service._build_seeded_target_circe(
        {"targetCohortName": "linagliptin", "inclusionCriteria": rows, "exclusionCriteria": []}
    )


def _skip_of(circe: dict[str, Any], criterion_id: str) -> dict[str, Any] | None:
    return next((r for r in circe["_skippedCriteria"] if r["criterionId"] == criterion_id), None)


class TestTheSkipRecordCarriesTheLineToTheGate:
    def test_should_carry_the_recorded_line_into_the_skip_record_when_the_build_skips_on_it(
        self, service
    ):
        rows = _rows_with_row_7_annotated(
            _context_annotation(SPAN_FROM_ROW_2, ROW_2["protocolLine"])
        )
        skip = _skip_of(_built(service, rows), "7")
        assert skip is not None
        assert skip["reason"] == CONDITIONAL_REASON
        assert (skip["conditionalSpan"], skip["conditionalSpanLine"]) == (
            SPAN_FROM_ROW_2, ROW_2["protocolLine"]
        )

    def test_should_carry_no_line_when_the_span_is_the_rows_own(self, service):
        rows = _rows_with_row_7_annotated(_context_annotation(SPAN_FROM_ROW_7, None))
        skip = _skip_of(_built(service, rows), "7")
        assert skip is not None
        assert (skip["conditionalSpan"], skip["conditionalSpanLine"]) == (SPAN_FROM_ROW_7, None)

    def test_should_emit_the_row_when_the_recorded_line_belongs_to_the_other_role(self, service):
        rows = _rows_with_row_7_annotated(
            _context_annotation(SPAN_FROM_EXC_35, EXC_35["protocolLine"])
        )
        circe = _built(service, rows)
        assert _skip_of(circe, "7") is None
        assert "inclusion:7" in circe["_criterionConceptSetRefs"]

    def test_should_pass_the_gate_with_the_built_record_and_fail_it_once_the_line_is_forged(
        self, service
    ):
        """The build writes what the gate needs, and the gate is shown failing on a forgery
        of that very record before its pass is believed."""
        from scripts.verify_circe_delivery import criteria_index, skipped_criteria_violations

        rows = _rows_with_row_7_annotated(
            _context_annotation(SPAN_FROM_ROW_2, ROW_2["protocolLine"])
        )
        circe = _built(service, rows)
        study = {"eligibility": {"inclusionCriteria": rows,
                                 "exclusionCriteria": _without_annotations(EXCLUSION)}}
        index = criteria_index(study)
        record = _skip_of(circe, "7")
        assert skipped_criteria_violations([record], index, circe) == []

        forged = dict(record, conditionalSpan=SPAN_FROM_EXC_35,
                      conditionalSpanLine=EXC_35["protocolLine"])
        violations = skipped_criteria_violations([forged], index, circe)
        assert len(violations) == 1
        assert "not the protocolLine of any inclusion row" in violations[0]


def test_should_render_every_prompt_through_the_production_path_without_a_cache_write(tmp_path):
    """The context arm adds no call: one per row with a line, cache off writes nothing."""
    eligibility = {
        "inclusionCriteria": _without_annotations(INCLUSION),
        "exclusionCriteria": _without_annotations(EXCLUSION),
    }
    with patch.dict(os.environ, {"ARTEMIS_ANNOTATION_CACHE": "0"}):
        recorder = _annotate(eligibility, _conditional(SPAN_FROM_ROW_2))
    assert len(recorder.calls) == len(INCLUSION) + len(EXCLUSION)
    assert not (tmp_path / "annotations.jsonl").exists()
