"""A planner failure on one criterion is that criterion's, recorded on its row and gated.

At b89ef7c a decomposition the planner could not obtain raised ``PlannerFailed`` out of
``plan()``, and NCT generation fell back to the UNPLANNED IR for the whole trial: one cut
reply discarded every other criterion's decomposition, and the only trace was the
draft's ``fallbackReason``, which no delivery check reads.

Now the failure stays with its criterion: it keeps the criterion exactly as Agent 1
extracted it (undecomposed), records the reason on it (``Criteria.planning_failure``,
the store row's ``planningFailure``), and every other criterion is planned. The build
lists such rows under ``_planningFailureCriteria`` (present and empty when none), the
delivery gate's check (ac) FAILS a file listing any, and a draft carrying one is not
reused from the NCT draft cache.

The replies are ARISTOTLE's two decompositions from the 2026-10-12 P2 re-ingest
(``output/site_gap/2026-10-12_p2_new``: reingest.log ``'atrial fibrillation or atrial
flutter' -> 2 sub-criteria (PRESENCE/ANY; 2 named by the line ...)`` and ``'mitral
stenosis' -> 2 sub-criteria (ABSENCE/ALL; 2 named by the line ...)``; store rows 8-10 and
4-6), written in the planner's output contract. The first is cut inside its second
member. No LLM is called.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.models.ir import Criteria
from src.services.tte_service import TTEService

AF_ENTITY = "atrial fibrillation or atrial flutter"
AF_LINE = "4. In atrial fibrillation or atrial flutter not due to a reversible cause and documented by"
MS_ENTITY = "mitral stenosis"
MS_LINE = "2. Clinically significant (moderate or severe) mitral stenosis"


def _member(name: str, entity: str, span: str) -> dict[str, Any]:
    return {"name": name, "entity_text": entity, "domain": "Condition", "source_span": span,
            "value_constraint_text": None, "value_constraint": None}


AF_REPLY = json.dumps({
    "decompose": True, "reasoning": "two arrhythmias", "excepted_entities": [],
    "relation": "any", "relation_span": "or", "cardinality": None,
    "sub_criteria": [_member("Atrial Fibrillation", "atrial fibrillation", "atrial fibrillation"),
                     _member("Atrial Flutter", "atrial flutter", "atrial flutter")],
})
AF_CUT = AF_REPLY[: AF_REPLY.index('"Atrial Flutter"') + 8]
MS_REPLY = json.dumps({
    "decompose": True, "reasoning": "two grades", "excepted_entities": [],
    "relation": "any", "relation_span": "or", "cardinality": None,
    "sub_criteria": [_member("Moderate Mitral Stenosis", "mitral stenosis, moderate", "moderate"),
                     _member("Severe Mitral Stenosis", "mitral stenosis, severe", "severe")],
})


class _Model:
    """Answers each criterion's prompt with that criterion's reply."""

    def __init__(self, replies: dict[str, str]) -> None:
        self.replies = replies

    def invoke(self, messages):
        prompt = str(messages[-1].content)
        for entity, reply in self.replies.items():
            if f"Entity Text: {entity}\n" in prompt or entity in prompt:
                return AIMessage(content=reply)
        raise AssertionError(f"no reply for prompt {prompt[:120]!r}")


def _planner(replies: dict[str, str]):
    from src.agents.planner.decomposer import CriteriaPlanner

    planner = CriteriaPlanner.__new__(CriteriaPlanner)
    planner.llm = _Model(replies)
    return planner


def _ir() -> SimpleNamespace:
    af = Criteria(name="AF/Flutter documented", domain="Condition", entity_text=AF_ENTITY,
                  source_text=AF_LINE, logic_type="PRESENCE")
    ms = Criteria(name="Mitral stenosis", domain="Condition", entity_text=MS_ENTITY,
                  source_text=MS_LINE, logic_type="ABSENCE")
    return SimpleNamespace(
        target=SimpleNamespace(primary_criteria=None, inclusion_rules=[af], exclusion_rules=[ms],
                               repair_accounting=[]),
        comparator=SimpleNamespace(primary_criteria=None, inclusion_rules=[], exclusion_rules=[]),
        outcome=None,
    )


# ── the planner ──────────────────────────────────────────────


def test_should_keep_the_failed_criterion_as_extracted_and_plan_the_others():
    ir = _planner({AF_ENTITY: AF_CUT, MS_ENTITY: MS_REPLY}).plan(_ir())

    af = ir.target.inclusion_rules[0]
    ms = ir.target.exclusion_rules[0]
    assert af.sub_criteria == [] and af.group_type == "ALL" and af.relation is None
    assert af.entity_text == AF_ENTITY and af.source_text == AF_LINE
    assert "Failed to parse planner response as JSON" in (af.planning_failure or ""), af
    assert [m.entity_text for m in ms.sub_criteria] == ["mitral stenosis, moderate",
                                                        "mitral stenosis, severe"]
    assert ms.planning_failure is None


def test_should_record_a_failed_call_on_the_criterion_too():
    def boom(_messages):
        raise TimeoutError("read timeout")

    planner = _planner({})
    planner.llm = SimpleNamespace(invoke=boom)
    ir = planner.plan(_ir())

    assert ir.target.inclusion_rules[0].planning_failure == "TimeoutError: read timeout"
    assert ir.target.exclusion_rules[0].planning_failure == "TimeoutError: read timeout"


def test_should_plan_every_criterion_and_record_nothing_when_all_replies_are_whole():
    ir = _planner({AF_ENTITY: AF_REPLY, MS_ENTITY: MS_REPLY}).plan(_ir())

    for rule in (ir.target.inclusion_rules[0], ir.target.exclusion_rules[0]):
        assert len(rule.sub_criteria) == 2 and rule.planning_failure is None


# ── NCT generation: the trial is planned, the failure rides on its row ──


def _generate(replies: dict[str, str]):
    svc = TTEService.__new__(TTEService)
    with patch.object(svc, "_parse_trial_agent_ir_from_nct", return_value=_ir()), \
            patch.object(svc, "_get_last_paper_status", return_value=None), \
            patch("src.agents.planner.get_planner", return_value=_planner(replies)), \
            patch.object(svc, "_fetch_nct_trial_metadata", return_value={}):
        return svc._generate_with_trial_agent_from_nct("NCT00412984")


def _row(rows: list[dict[str, Any]], source_text: str) -> dict[str, Any]:
    return next(r for r in rows if r.get("sourceText") == source_text)


def test_should_plan_the_trial_and_record_the_failure_on_the_criterion_row():
    study, _mode, fallback_reason, _paper = _generate({AF_ENTITY: AF_CUT, MS_ENTITY: MS_REPLY})

    eligibility = study["eligibility"]
    assert fallback_reason is None, "one criterion's failure discarded the trial's plan"
    af = _row(eligibility["inclusionCriteria"], AF_ENTITY)
    assert len(eligibility["inclusionCriteria"]) == 1 and af.get("groupId") is None
    assert "Failed to parse planner response as JSON" in af["planningFailure"]
    assert [r["sourceText"] for r in eligibility["exclusionCriteria"]] == [
        MS_ENTITY, "mitral stenosis, moderate", "mitral stenosis, severe"]
    assert all("planningFailure" not in r for r in eligibility["exclusionCriteria"])


def test_should_write_no_planning_failure_on_any_row_when_every_criterion_plans():
    study, _mode, fallback_reason, _paper = _generate({AF_ENTITY: AF_REPLY, MS_ENTITY: MS_REPLY})

    rows = study["eligibility"]["inclusionCriteria"] + study["eligibility"]["exclusionCriteria"]
    assert fallback_reason is None and len(rows) == 6
    assert all("planningFailure" not in r for r in rows)


# ── the draft cache ──────────────────────────────────────────


def _run_generate(replies: dict[str, str]) -> dict[str, Any]:
    """run_generate_from_nct over the real generation; returns the stored artifact payload."""
    store = MagicMock()
    store.get_study.return_value = {"id": 3, "version": 1}
    store.create_job.return_value = {"id": "job_1"}
    store.find_latest_generate_from_nct_artifact.return_value = None
    store.create_artifact.side_effect = lambda payload: {"id": "artifact_1", **payload}
    store.update_job.return_value = {"id": "job_1", "status": "completed"}
    svc = TTEService.__new__(TTEService)
    svc.store = store
    with patch.object(svc, "_parse_trial_agent_ir_from_nct", return_value=_ir()), \
            patch.object(svc, "_get_last_paper_status", return_value=None), \
            patch("src.agents.planner.get_planner", return_value=_planner(replies)), \
            patch.object(svc, "_fetch_nct_trial_metadata", return_value={}), \
            patch.object(svc, "_get_capability_signal",
                         return_value=MagicMock(model_dump=lambda: {})):
        svc.run_generate_from_nct(3, "NCT00412984", force_refresh=True)
    return store.create_artifact.call_args.args[0]["payload"]


def test_should_name_the_failed_criterion_on_the_draft_meta():
    meta = _run_generate({AF_ENTITY: AF_CUT, MS_ENTITY: MS_REPLY})["meta"]

    assert meta["fallbackReason"] is None
    assert [(f["role"], f["label"]) for f in meta["planningFailures"]] == [("inclusion", AF_ENTITY)]
    assert "Failed to parse planner response as JSON" in meta["planningFailures"][0]["reason"]


def test_should_name_no_criterion_on_the_meta_of_a_clean_draft():
    assert _run_generate({AF_ENTITY: AF_REPLY, MS_ENTITY: MS_REPLY})["meta"]["planningFailures"] == []


def _draft(meta_extra: dict[str, Any]) -> dict[str, Any]:
    return {"capability": "generate_from_nct", "kind": "draft_generation", "status": "completed",
            "payload": {"meta": {"nctId": "NCT00412984", "generatorVersion": "v",
                                 "generationMode": "trial_agent", **meta_extra}}}


@pytest.mark.parametrize("meta, reused", [
    ({"planningFailures": [{"criterionId": "8", "role": "inclusion", "label": AF_ENTITY,
                            "reason": "ValueError: cut"}]}, False),
    ({"planningFailures": []}, True),
    ({}, True),
], ids=["a criterion failed", "every criterion planned", "draft predates the record"])
def test_should_reuse_only_a_draft_whose_every_criterion_was_planned(tmp_path, meta, reused):
    from src.services.tte_store import TTEStore

    store = TTEStore(str(tmp_path / "studies.json"))
    with patch.object(store, "_read", return_value={"artifacts": [_draft(meta)]}):
        found = store.find_latest_generate_from_nct_artifact(nct_id="NCT00412984",
                                                             generator_version="v")

    assert (found is not None) is reused


# ── the build writes the record the delivered file carries ───


def _concept_set(seed: str) -> dict[str, Any]:
    from src.api.models.tte import CriterionMappingMetadata

    return {
        "name": seed, "domain": "Condition",
        "expression": {"items": [{
            "concept": {"CONCEPT_ID": 313217, "CONCEPT_NAME": seed, "CONCEPT_CODE": "x",
                        "DOMAIN_ID": "Condition", "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding"},
            "includeDescendants": True, "isExcluded": False}]},
        "mapping_metadata": CriterionMappingMetadata(queryUsed=seed, selectedConceptIds=[313217]),
    }


def _build(monkeypatch, rows: list[dict[str, Any]]) -> dict[str, Any]:
    svc = TTEService.__new__(TTEService)
    monkeypatch.setattr(svc, "_recommend_seeded_concept_set",
                        lambda seed, **_k: _concept_set(seed.strip()))
    return svc._build_seeded_target_circe({
        "targetCohortName": "apixaban", "inclusionCriteria": rows, "exclusionCriteria": [],
    })


def _criterion(cid: str, entity: str, **extra: Any) -> dict[str, Any]:
    return {"id": cid, "description": entity, "sourceText": entity, "protocolLine": AF_LINE,
            "domain": "Condition", "window": {"start": -9999, "end": 0},
            "logicType": "PRESENCE", "isGroupLabel": False, **extra}


REASON = "ValueError: Failed to parse planner response as JSON: Unterminated string"


def test_should_list_a_row_whose_planning_failed_in_the_built_expression(monkeypatch):
    circe = _build(monkeypatch, [_criterion("8", AF_ENTITY, planningFailure=REASON),
                                 _criterion("9", "hypertension")])

    assert circe["_planningFailureCriteria"] == [
        {"criterionId": "8", "role": "inclusion", "label": AF_ENTITY, "reason": REASON}]


def test_should_carry_the_record_present_and_empty_when_every_row_was_planned(monkeypatch):
    circe = _build(monkeypatch, [_criterion("9", "hypertension")])

    assert circe["_planningFailureCriteria"] == []


def test_should_name_the_record_key_in_one_place():
    from src.utils import circe_lint

    assert circe_lint.PLANNING_FAILURE_CRITERIA_KEY == "_planningFailureCriteria"


# ── the delivery gate, check (ac) ────────────────────────────


@pytest.fixture
def gate(monkeypatch, tmp_path, capsys):
    """Run the delivery gate over both ARISTOTLE arms carrying ``records``."""
    from tests.test_delivery_gate_reads_drop_records import CLEAN_RECORDS, _study

    def _run(rows: list[dict[str, Any]] | None) -> tuple[int, str]:
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study()
        core = study["eligibility"]["structuredExpression"]
        records = json.loads(json.dumps(CLEAN_RECORDS))
        if rows is not None:
            records["_planningFailureCriteria"] = rows
        for role in ("treatment", "comparator"):
            payload = json.loads(json.dumps(core))
            payload.update(json.loads(json.dumps(records)))
            (tmp_path / f"aristotle_{role}.circe.json").write_text(json.dumps(payload))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "aristotle=3"])
        return rc, capsys.readouterr().out

    return _run


FAILED_ROW = {"criterionId": "8", "role": "inclusion", "label": AF_ENTITY, "reason": REASON}


def test_should_fail_a_file_listing_a_criterion_whose_planning_failed(gate):
    rc, out = gate([FAILED_ROW])

    assert rc == 1, out
    assert "planning failed (1)" in out
    assert f"inclusion #8 {AF_ENTITY!r}" in out and "Failed to parse planner response" in out


def test_should_pass_and_say_zero_when_the_record_is_present_and_empty(gate):
    rc, out = gate([])

    assert rc == 0, out
    assert "0 criteria carry a planning failure" in out


def test_should_pass_without_a_claim_when_the_artifact_predates_the_record(gate):
    rc, out = gate(None)

    assert rc == 0, out
    assert "planning failure" not in out and "planning failed" not in out
