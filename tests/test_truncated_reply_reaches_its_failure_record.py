"""Every other LLM call site: a reply cut off mid-item is a failure of that stage, recorded.

Measured on 1835b17, one reply per site cut inside an item (no finish_reason on the
message unless stated):

- planner: ``_extract_json`` answered a JSON error with ``{"decompose": false}``, so a
  cut decomposition read as "atomic", printed with a check mark. Any other failure was
  printed and swallowed per criterion. Now both raise ``PlannerFailed`` out of
  ``plan()`` -- the trial's existing planner failure path: NCT generation keeps the
  unplanned IR and records ``fallbackReason`` on the draft -- and a draft carrying a
  ``fallbackReason`` is no longer reused from the draft cache.
- Agent 1 threshold review: a cut reply read as "no misses", logged at DEBUG. It stays
  fail-open by design (a review must not fail the parse it reviews) but says so at
  WARNING, and a reply with no ``misses`` list is a failure, not "no misses".
- analysis finalizer: ``JsonOutputParser.parse`` repaired the cut reply and reported
  ``status: ok`` with a cut rationale; now its existing ``heuristic_fallback`` record
  carries the parse failure.
- report narrative: a narrative stopped at the token ceiling (``finish_reason="length"``)
  was returned as the report; now it is refused and the plain report is returned.

Already strict on 1835b17, pinned here so they stay that way: Agent 1 extraction (it
checks ``finish_reason`` and parses with ``json.loads``), the OR-group dedup judge, and
the comparator's literature extraction.

No LLM is called: each site's model is a stub returning the text.
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.models.ir import Criteria


def _cut_inside(text: str, fragment: str) -> str:
    at = text.index(fragment)
    return text[: at + len(fragment) // 2]


def _model(reply, **metadata):
    message = AIMessage(content=reply, response_metadata=metadata)
    return SimpleNamespace(invoke=lambda _messages: message)


# ── planner ──────────────────────────────────────────────────

LEADER_LINE = "Currently planned coronary, carotid, or peripheral artery revascularization"
PLAN = json.dumps({"decompose": True, "sub_criteria": [
    {"name": "coronary revascularization", "entity_text": "coronary revascularization",
     "domain": "Procedure", "source_span": "coronary"},
    {"name": "carotid revascularization", "entity_text": "carotid revascularization",
     "domain": "Procedure", "source_span": "carotid"},
], "excepted_entities": []})
PLAN_CUT = _cut_inside(PLAN, "carotid revascularization")


def _criterion() -> Criteria:
    return Criteria(name="revascularization", domain="Procedure",
                    entity_text="planned coronary, carotid, or peripheral revascularization",
                    source_text=LEADER_LINE, logic_type="ABSENCE")


def _planner(reply):
    from src.agents.planner.decomposer import CriteriaPlanner

    planner = CriteriaPlanner.__new__(CriteriaPlanner)
    planner.llm = _model(reply) if not isinstance(reply, Exception) else SimpleNamespace(
        invoke=lambda _m: (_ for _ in ()).throw(reply))
    return planner


@pytest.mark.parametrize("reply, reason", [
    (PLAN_CUT, "JSON"),
    (TimeoutError("read timeout"), "TimeoutError: read timeout"),
], ids=["cut mid-item", "call raised"])
def test_should_fail_the_plan_naming_the_criterion_when_its_decomposition_is_unusable(reply, reason):
    from src.agents.planner.decomposer import PlannerFailed

    criterion = _criterion()
    cohort = SimpleNamespace(inclusion_rules=[], exclusion_rules=[criterion])
    ir = SimpleNamespace(target=cohort, comparator=SimpleNamespace(inclusion_rules=[],
                                                                     exclusion_rules=[]))

    with pytest.raises(PlannerFailed) as raised:
        _planner(reply).plan(ir)

    assert reason in str(raised.value) and criterion.entity_text in str(raised.value)
    assert criterion.sub_criteria == []


def test_should_keep_an_atomic_answer_atomic():
    reply = json.dumps({"decompose": False, "sub_criteria": [], "excepted_entities": []})

    criterion = _planner(reply)._decompose_criterion(_criterion())

    assert criterion.sub_criteria == []


def test_should_record_the_planner_failure_on_the_draft_and_keep_the_unplanned_ir():
    """The existing route a plan() failure takes in NCT generation (unchanged here)."""
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    ir = SimpleNamespace(name="unplanned")
    with patch.object(svc, "_parse_trial_agent_ir_from_nct", return_value=ir), \
            patch.object(svc, "_get_last_paper_status", return_value=None), \
            patch.object(svc, "_plan_trial_agent_ir",
                         side_effect=__import__("src.agents.planner.decomposer",
                                                fromlist=["PlannerFailed"]).PlannerFailed("cut")), \
            patch.object(svc, "_study_from_ir", side_effect=lambda got, *_a, **_k: {"ir": got}), \
            patch.object(svc, "_fetch_nct_trial_metadata", return_value={}):
        study, _mode, fallback_reason, _paper = svc._generate_with_trial_agent_from_nct("NCT01179048")

    assert study["ir"] is ir and fallback_reason == "cut"


def _draft(meta_extra):
    return {"capability": "generate_from_nct", "kind": "draft_generation", "status": "completed",
            "payload": {"meta": {"nctId": "NCT01179048", "generatorVersion": "v",
                                 "generationMode": "trial_agent", **meta_extra}}}


@pytest.mark.parametrize("reason, reused", [("PlannerFailed: cut", False), (None, True)],
                         ids=["planner failed", "clean draft"])
def test_should_reuse_only_a_draft_whose_planning_ran(tmp_path, reason, reused):
    from src.services.tte_store import TTEStore

    store = TTEStore(str(tmp_path / "studies.json"))
    with patch.object(store, "_read", return_value={"artifacts": [_draft({"fallbackReason": reason})]}):
        found = store.find_latest_generate_from_nct_artifact(nct_id="NCT01179048",
                                                             generator_version="v")

    assert (found is not None) is reused


# ── Agent 1 threshold review ─────────────────────────────────

REVIEW = json.dumps({"misses": [
    {"criterion_line": 3, "criterion_text": "HbA1c 7.0-10.0%", "reason": "range lost"},
    {"criterion_line": 5, "criterion_text": "eGFR >= 30", "reason": "bound lost"}]})


def _review(reply, caplog):
    from src.agents.agent1 import parser as parser_mod

    decomposer = parser_mod.LogicDecomposer.__new__(parser_mod.LogicDecomposer)
    decomposer.model_name = "stub"
    ir = SimpleNamespace(target=SimpleNamespace(inclusion_rules=[], exclusion_rules=[]))
    caplog.set_level(logging.WARNING)
    with patch.object(parser_mod, "get_llm", lambda *a, **k: _model(reply)):
        return decomposer._llm_review_value_constraints("NCT01243424", ["a"], [], ir)


@pytest.mark.parametrize("reply", [_cut_inside(REVIEW, "eGFR >= 30"), '{"verdict": "none"}'],
                         ids=["cut mid-item", "no misses list"])
def test_should_say_at_warning_that_the_threshold_review_failed(caplog, reply):
    misses = _review(reply, caplog)

    assert misses == []
    lines = [r.getMessage() for r in caplog.records
             if "[Agent 1] Threshold review failed for NCT01243424" in r.getMessage()]
    assert len(lines) == 1 and "\n" not in lines[0], lines


def test_should_return_the_misses_of_a_whole_review(caplog):
    assert len(_review(REVIEW, caplog)) == 2


# ── analysis finalizer ───────────────────────────────────────

FINAL = json.dumps({"recommendationSource": "llm_finalizer", "whyThisMethod": "IPTW balances",
                    "whyNot": {"PSM": "loses sample", "MAHALANOBIS": "not requested"},
                    "diagnosisSummary": "balanced"})


def _finalize(reply):
    import src.services.tte_service as tte_service

    with patch.object(tte_service, "get_llm", lambda *a, **k: _model(reply)):
        return tte_service.TTEService._finalize_analysis_strategy_candidates(
            None, diagnosis_title="t", diagnosis_summary="s", diagnosis_facts=[], warnings=[],
            candidates=[], selected_method="IPTW", recommendation_stage="final",
            requested_ps_method=None,
        )


def test_should_fall_back_and_record_why_when_the_finalizer_reply_is_cut():
    parsed, meta = _finalize(_cut_inside(FINAL, "not requested"))

    assert parsed is None
    assert meta["status"] == "heuristic_fallback"
    assert "Invalid json output" in meta["reason"], meta


def test_should_use_a_whole_finalizer_reply():
    parsed, meta = _finalize(FINAL)

    assert meta["status"] == "ok" and parsed.whyNot["MAHALANOBIS"] == "not requested"


# ── report narrative ─────────────────────────────────────────


def _narrative(reply, monkeypatch, tmp_path, **metadata):
    import src.services.tte_service as tte_service

    monkeypatch.setenv("ARTEMIS_TRUNCATION_DIR", str(tmp_path))
    svc = tte_service.TTEService.__new__(tte_service.TTEService)
    with patch.object(tte_service, "get_llm", lambda *a, **k: _model(reply, **metadata)):
        return svc._generate_report_narrative(
            title="Study", description="d", nct_id="NCT00412984", brief_title="b",
            treatment_name="apixaban", comparator_name="warfarin", outcome_name="stroke",
            analysis_method="IPTW", n_treatment=10, n_comparator=12, hr=None, ci_lower=None,
            ci_upper=None, p_value=None, treatment_events=None, comparator_events=None,
            matched_pairs=None, followup_days="365", source_key="k",
        )


CUT_HTML = "<h2>1. Clinical Question</h2><p>The target trial asks whether apix"


def test_should_return_the_plain_report_when_the_narrative_hit_the_token_ceiling(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.WARNING)

    html = _narrative(CUT_HTML, monkeypatch, tmp_path, finish_reason="length")

    assert not html.startswith(CUT_HTML), "the cut narrative was returned as the report"
    assert any("LLM report narrative generation failed" in r.getMessage()
               and "finish_reason='length'" in r.getMessage() for r in caplog.records)


def test_should_return_a_narrative_that_finished(monkeypatch, tmp_path):
    assert _narrative(CUT_HTML + "</p>", monkeypatch, tmp_path, finish_reason="stop") == CUT_HTML + "</p>"


# ── already strict on 1835b17 ────────────────────────────────


def test_should_refuse_a_cut_agent1_extraction():
    from src.agents.agent1.parser import LogicDecomposer

    reply = json.dumps({"target": {"inclusion_rules": [
        {"name": "Age", "domain": "Demographic"},
        {"name": "Atrial fibrillation", "domain": "Condition"}]}})
    decomposer = LogicDecomposer.__new__(LogicDecomposer)
    decomposer.llm = _model(_cut_inside(reply, "Atrial fibrillation"))

    with pytest.raises(ValueError, match="Failed to parse LLM response as JSON"):
        decomposer._invoke_and_extract([], what="Agent 1 NCT extraction")


def test_should_give_no_verdict_for_a_cut_dedup_judge_reply():
    from src.agents.agent1.criteria_dedup_judge import _parse_response

    reply = json.dumps({"verdict": "restatement", "matched_alternatives": [1, 2], "reason": "same"})
    with pytest.raises(ValueError):
        _parse_response(_cut_inside(reply, "same"), ["a", "b"])


def test_should_record_a_caveat_and_no_candidate_for_a_cut_comparator_reply():
    from src.agents.comparator import recommender

    reply = json.dumps({"candidates": [
        {"drug_class": "DPP-4 inhibitors", "ingredients": ["sitagliptin"], "verdict": "neutral",
         "same_setting": True, "rationale": "r"},
        {"drug_class": "Sulfonylureas", "ingredients": ["glimepiride"], "verdict": "harmful",
         "same_setting": True, "rationale": "r"}]})
    with patch.object(recommender, "_vllm_reachable", lambda *a, **k: True), \
            patch.object(recommender, "_fetch_comparator_docs", lambda _q: []), \
            patch.object(recommender, "_get_llm",
                         lambda: _model(_cut_inside(reply, "Sulfonylureas"))):
        out = recommender.recommend_from_literature("linagliptin", "DPP-4", "T2DM", "MACE",
                                                    use_cache=False, save=False)

    assert out["candidates"] == [] and out["recommendation"] is None
    assert out["caveat"].startswith("extract failed")

