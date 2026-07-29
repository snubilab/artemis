"""Stage-2 classifier gates (ADR-032 D5/D6) plus the orchestration around them.

Almost every test here runs without the model. That is the point: the gates are the
part of the design that has to hold when the model misbehaves, so they are pure code
and are exercised against the answers the probe actually recorded — including the
ablation answers, where removing the head requirement made the model put the unit in
the head slot rather than falling through to AGE as predicted.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.agents.agent1.threshold_classifier import (
    NON_CRITERION_FAMILIES,
    PROMPT_PATH,
    SPAN_CLASSES,
    ThresholdSpan,
    apply_gates,
    classify_criteria,
    classify_criterion,
    deescape,
    instruction_tail,
    is_headless,
)

ROOT = Path(__file__).resolve().parents[1]


def _payload(*spans: dict[str, Any]) -> dict[str, Any]:
    return {"spans": [{"family": None, **span} for span in spans]}


def _classes(spans: list[ThresholdSpan]) -> list[str]:
    return [span.span_class for span in spans]


# ---------------------------------------------------------------------------
# G1 -- headless criterion. Judged before the model answer is read.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("criterion", ["> 1500/mm3", "< 100,000/mm3", ">= 6 months", "\\>= 6 months"])
def test_headless_criterion_is_review_whatever_the_model_says(criterion: str) -> None:
    """The model answering MEASUREMENT_VALUE cannot make a parentless child a class."""
    spans = apply_gates(criterion, _payload(
        {"threshold_phrase": criterion, "head": "mm3", "class": "MEASUREMENT_VALUE"}
    ))
    assert _classes(spans) == ["REVIEW"]
    assert "gate 1" in (spans[0].review_reason or "")


@pytest.mark.parametrize("criterion", [
    "Adequate organ function, defined as: absolute neutrophil count > 1500/mm3",
    "at least 18 years old",          # head follows the comparator -- the position-based
    "≤ 40 years of age",         # rule flagged 2.5% of lines like these, this one 0.1%
    "White blood cell count <3×10^9/L",
])
def test_criterion_with_a_head_is_not_headless(criterion: str) -> None:
    assert not is_headless(criterion)


# ---------------------------------------------------------------------------
# G2 -- class and family membership
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("klass,family", [
    ("MEASUREMENT", None),                       # not in the enum
    ("NON_CRITERION", "made_up_family"),
    ("NON_CRITERION", None),
])
def test_unknown_class_or_family_is_review(klass: str, family: str | None) -> None:
    spans = apply_gates("ALT > 3 x ULN", _payload(
        {"threshold_phrase": "> 3 x ULN", "head": "ALT", "class": klass, "family": family}
    ))
    assert _classes(spans) == ["REVIEW"]
    assert "gate 2" in (spans[0].review_reason or "")


def test_family_outside_non_criterion_is_dropped_not_rejected() -> None:
    """family is meaningless off NON_CRITERION (D1); a stray one is noise, not a fault."""
    spans = apply_gates("ALT > 3 x ULN", _payload(
        {"threshold_phrase": "> 3 x ULN", "head": "ALT",
         "class": "MEASUREMENT_VALUE", "family": "inclusive_range"}
    ))
    assert _classes(spans) == ["MEASUREMENT_VALUE"] and spans[0].family is None


# ---------------------------------------------------------------------------
# G3 -- threshold_phrase must be a verbatim substring
# ---------------------------------------------------------------------------

def test_summarised_phrase_is_review() -> None:
    """Recorded failure: the model dropped 'for the hazard ratio' from the middle."""
    criterion = ("the upper boundary of the two-sided 95.02% confidence interval "
                 "for the hazard ratio was less than 1.3")
    spans = apply_gates(criterion, _payload({
        "threshold_phrase": "the upper boundary of the two-sided 95.02% confidence interval "
                            "was less than 1.3",
        "head": None, "class": "NON_CRITERION", "family": "statistical_decision_rule",
    }))
    assert spans[0].span_class == "REVIEW" and "gate 3" in (spans[0].review_reason or "")


def test_substring_check_tolerates_escapes_case_and_spacing() -> None:
    spans = apply_gates("Serum ALT \\> 3 x ULN at screening", _payload(
        {"threshold_phrase": "alt  >  3 x uln", "head": "Serum ALT", "class": "MEASUREMENT_VALUE"}
    ))
    assert _classes(spans) == ["MEASUREMENT_VALUE"]


# ---------------------------------------------------------------------------
# G4 -- head substring, and outside the operand region
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("criterion,phrase,head", [
    ("Neutrophils > 1500/mm3", "> 1500/mm3", "mm3"),
    ("Washout >= 6 months", ">= 6 months", "months"),
    ("Consumption of coffee (more than 8 cups per day)", "more than 8 cups per day", "cups"),
])
def test_unit_in_the_head_slot_is_review(criterion: str, phrase: str, head: str) -> None:
    """The ablation's actual behaviour: a real substring that is not a head."""
    spans = apply_gates(criterion, _payload(
        {"threshold_phrase": phrase, "head": head, "class": "MEASUREMENT_VALUE"}
    ))
    assert spans[0].span_class == "REVIEW" and "gate 4" in (spans[0].review_reason or "")


def test_head_inside_its_own_phrase_before_the_comparator_is_kept() -> None:
    """'head must not be in the phrase' would be the wrong rule; only the operand is barred."""
    spans = apply_gates("White blood cell count <3×10^9/L", _payload(
        {"threshold_phrase": "White blood cell count <3×10^9/L",
         "head": "White blood cell count", "class": "MEASUREMENT_VALUE"}
    ))
    assert _classes(spans) == ["MEASUREMENT_VALUE"]


def test_invented_head_is_review() -> None:
    spans = apply_gates("ANC > 1500/mm3 at screening", _payload(
        {"threshold_phrase": "> 1500/mm3", "head": "absolute neutrophil count",
         "class": "MEASUREMENT_VALUE"}
    ))
    assert spans[0].span_class == "REVIEW" and "gate 4" in (spans[0].review_reason or "")


def test_null_head_cannot_carry_a_class() -> None:
    spans = apply_gates("Creatinine clearance > 60 mL/min", _payload(
        {"threshold_phrase": "> 60 mL/min", "head": None, "class": "MEASUREMENT_VALUE"}
    ))
    assert spans[0].span_class == "REVIEW" and "gate 4" in (spans[0].review_reason or "")


@pytest.mark.parametrize("spelling", ["null", "None", " NULL ", ""])
def test_the_string_null_is_folded_to_a_missing_head(spelling: str) -> None:
    """Observed in 2 of 3 elided-head probe cases. Folding it is not leniency."""
    spans = apply_gates("Creatinine clearance > 60 mL/min", _payload(
        {"threshold_phrase": "> 60 mL/min", "head": spelling, "class": "REVIEW"}
    ))
    assert spans[0].head is None


# ---------------------------------------------------------------------------
# G5 -- AGE needs an age word
# ---------------------------------------------------------------------------

def test_age_without_an_age_word_is_review() -> None:
    spans = apply_gates("Washout period >= 18 years", _payload(
        {"threshold_phrase": ">= 18 years", "head": "Washout period", "class": "AGE"}
    ))
    assert spans[0].span_class == "REVIEW" and "gate 5" in (spans[0].review_reason or "")


def test_age_with_an_age_word_is_kept() -> None:
    spans = apply_gates("Age >= 18 years at screening", _payload(
        {"threshold_phrase": "Age >= 18 years", "head": "Age", "class": "AGE"}
    ))
    assert _classes(spans) == ["AGE"]


# ---------------------------------------------------------------------------
# G6 -- overlap, and phrases carrying no threshold at all
# ---------------------------------------------------------------------------

def test_overlapping_spans_collapse_to_the_longer_one() -> None:
    """EVERY NUMERAL made the model emit '> 500 mL' twice, once inside a longer phrase."""
    criterion = "Blood donation or blood loss > 500 mL within 3 months prior to screening"
    spans = apply_gates(criterion, _payload(
        {"threshold_phrase": "> 500 mL", "head": "blood loss", "class": "EVENT_QUANTITY"},
        {"threshold_phrase": "Blood donation or blood loss > 500 mL",
         "head": "Blood donation or blood loss", "class": "EVENT_QUANTITY"},
    ))
    kept = [s for s in spans if s.origin == "model"]
    assert [s.threshold_phrase for s in kept] == ["Blood donation or blood loss > 500 mL"]


def test_phrase_with_neither_numeral_nor_comparator_is_discarded() -> None:
    """EVERY NUMERAL made the model emit 'prior to screening' as a span of its own."""
    criterion = "Blood loss > 500 mL within 3 months prior to screening"
    spans = apply_gates(criterion, _payload(
        {"threshold_phrase": "> 500 mL", "head": "Blood loss", "class": "EVENT_QUANTITY"},
        {"threshold_phrase": "prior to screening", "head": None, "class": "TEMPORAL_WINDOW"},
    ))
    assert [s.threshold_phrase for s in spans] == ["> 500 mL", "3"]


def test_numeral_free_criterion_yields_no_spans() -> None:
    """Out of scope by ADR-032, and a REVIEW per prose line would bury the gap report."""
    assert apply_gates("Histologically confirmed adenocarcinoma", _payload()) == []


def test_implicit_multiplier_one_survives_having_no_numeral() -> None:
    """'below the lower limit of normal' is a real LLN threshold with nothing to count."""
    spans = apply_gates("hemoglobin below the lower limit of normal", _payload(
        {"threshold_phrase": "below the lower limit of normal", "head": "hemoglobin",
         "class": "MEASUREMENT_VALUE"}
    ))
    assert _classes(spans) == ["MEASUREMENT_VALUE"]


# ---------------------------------------------------------------------------
# G7 -- numeral recall net. The countermeasure to the dominant failure.
# ---------------------------------------------------------------------------

def test_dropped_span_becomes_a_recall_net_review() -> None:
    """Measured: the model dropped the window in all four multi-threshold probe lines."""
    spans = apply_gates("LVEF < 40% measured within 6 months prior to randomization", _payload(
        {"threshold_phrase": "< 40%", "head": "LVEF", "class": "MEASUREMENT_VALUE"}
    ))
    assert _classes(spans) == ["MEASUREMENT_VALUE", "REVIEW"]
    assert spans[1].origin == "recall_net" and spans[1].threshold_phrase == "6"


def test_recall_is_by_offset_so_a_longer_numeral_cannot_absorb_a_shorter_one() -> None:
    """A substring test would read '5' as claimed because the kept span holds '150'."""
    criterion = "HIV for >5 years with CD4 count > 150 cells/microL"
    spans = apply_gates(criterion, _payload(
        {"threshold_phrase": "> 150 cells/microL", "head": "CD4 count", "class": "MEASUREMENT_VALUE"}
    ))
    assert [s.threshold_phrase for s in spans if s.origin == "recall_net"] == ["5"]


@pytest.mark.parametrize("criterion,phrase,head", [
    ("CD4 count > 150 cells/microL", "> 150 cells/microL", "CD4 count"),
    ("HbA1c >= 7.0%", ">= 7.0%", "HbA1c"),
    ("Platelet count <90×10^9/L", "<90×10^9/L", "Platelet count"),
])
def test_digits_inside_analyte_names_and_units_are_not_unclaimed(
    criterion: str, phrase: str, head: str
) -> None:
    """Without the lookbehind, CD4's '4' and HbA1c's '1' were reported as dropped spans."""
    spans = apply_gates(criterion, _payload(
        {"threshold_phrase": phrase, "head": head, "class": "MEASUREMENT_VALUE"}
    ))
    assert [s for s in spans if s.origin == "recall_net"] == []


def test_a_review_span_still_claims_its_numeral() -> None:
    """A gate demotion is not a drop; re-reporting it through G7 would be noise."""
    spans = apply_gates("Washout period >= 18 years", _payload(
        {"threshold_phrase": ">= 18 years", "head": "Washout period", "class": "AGE"}
    ))
    assert len(spans) == 1 and spans[0].origin == "model"


# ---------------------------------------------------------------------------
# G0 and the structural property the whole design rests on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [None, {}, {"spans": "nope"}, {"spans": []}, {"spans": [7]}])
def test_unusable_model_answer_is_review(payload: Any) -> None:
    spans = apply_gates("ALT > 3 x ULN", payload)
    assert spans and all(s.span_class == "REVIEW" for s in spans)


def test_no_gate_failure_can_reach_a_class() -> None:
    """There must be no path from a gate failure to anything but REVIEW (D5)."""
    criterion = "Serum ALT > 3 x ULN and washout >= 6 weeks"
    malformed = [
        {"threshold_phrase": "> 3 x ULN", "head": "ULN", "class": "MEASUREMENT_VALUE"},
        {"threshold_phrase": "not in the text", "head": "ALT", "class": "MEASUREMENT_VALUE"},
        {"threshold_phrase": ">= 6 weeks", "head": "washout", "class": "AGE"},
        {"threshold_phrase": ">= 6 weeks", "head": None, "class": "STATE_DURATION"},
        {"threshold_phrase": "> 3 x ULN", "head": "Serum ALT", "class": "NOT_A_CLASS"},
        {"threshold_phrase": "> 3 x ULN", "head": "Serum ALT", "class": "NON_CRITERION",
         "family": "nope"},
    ]
    for span in malformed:
        spans = apply_gates(criterion, _payload(span))
        demoted = [s for s in spans if s.review_reason]
        assert demoted, f"{span} passed every gate"
        assert all(s.span_class == "REVIEW" for s in demoted), span


def test_no_returned_head_is_ever_invented() -> None:
    """ThresholdSpan.head promises a verbatim substring, on demoted spans too."""
    criterion = "Serum ALT > 3 x ULN and washout >= 6 weeks"
    for span in [
        {"threshold_phrase": "> 3 x ULN", "head": "alkaline phosphatase", "class": "MEASUREMENT_VALUE"},
        {"threshold_phrase": "not in the text", "head": "alkaline phosphatase", "class": "MEASUREMENT_VALUE"},
        {"threshold_phrase": ">= 6 weeks", "head": "ULN", "class": "STATE_DURATION"},
    ]:
        for out in apply_gates(criterion, _payload(span)):
            assert out.head is None or out.head.lower() in criterion.lower(), out


def test_no_emitted_head_is_ever_unverified() -> None:
    """ThresholdSpan.head promises a verbatim substring, including on demoted spans."""
    criterion = "Serum ALT > 3 x ULN and washout >= 6 weeks"
    for span in [
        {"threshold_phrase": "not in the text", "head": "invented", "class": "MEASUREMENT_VALUE"},
        {"threshold_phrase": "> 3 x ULN", "head": "invented", "class": "MEASUREMENT_VALUE"},
        {"threshold_phrase": "> 3 x ULN", "head": "ULN", "class": "MEASUREMENT_VALUE"},
        {"threshold_phrase": ">= 6 weeks", "head": "washout", "class": "AGE"},
    ]:
        for out in apply_gates(criterion, _payload(span)):
            assert out.head is None or out.head.lower() in criterion.lower(), out


def test_every_emitted_class_is_in_the_enum() -> None:
    spans = apply_gates("Age >= 18 years", _payload(
        {"threshold_phrase": "Age >= 18 years", "head": "Age", "class": "AGE"}
    ))
    assert {s.span_class for s in spans} <= SPAN_CLASSES


def test_deescape_removes_ct_gov_comparator_escapes() -> None:
    """5/13 probe cases parsed with these intact, 13/13 without."""
    assert deescape("ALT \\> 3 x ULN, ANC =\\< 1500") == "ALT > 3 x ULN, ANC =< 1500"


# ---------------------------------------------------------------------------
# Orchestration -- stub model, no network
# ---------------------------------------------------------------------------

class _Stub(BaseChatModel):
    """Replies from a scripted list and counts how often it was asked."""

    replies: List[str] = []
    calls: List[str] = []

    @property
    def _llm_type(self) -> str:
        return "stub"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(str(messages[-1].content))
        body = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=body))])


ANSWER = json.dumps({"spans": [
    {"threshold_phrase": "> 3 x ULN", "head": "Serum ALT", "class": "MEASUREMENT_VALUE",
     "family": None}
]})


def _stub(*replies: str) -> _Stub:
    return _Stub(replies=list(replies) or [ANSWER], calls=[])


def test_classify_criterion_returns_gated_spans(tmp_path: Path) -> None:
    spans = classify_criterion("Serum ALT \\> 3 x ULN", _stub(), cache_dir=tmp_path)
    assert _classes(spans) == ["MEASUREMENT_VALUE"]


def test_the_model_never_sees_the_ct_gov_escapes(tmp_path: Path) -> None:
    stub = _stub()
    classify_criterion("Serum ALT \\> 3 x ULN", stub, cache_dir=tmp_path)
    assert "\\" not in stub.calls[0]


def test_prose_around_the_json_is_tolerated(tmp_path: Path) -> None:
    spans = classify_criterion(
        "Serum ALT > 3 x ULN", _stub(f"Here you go:\n{ANSWER}\nHope that helps."),
        cache_dir=tmp_path,
    )
    assert _classes(spans) == ["MEASUREMENT_VALUE"]


def test_unparseable_output_is_retried_once_then_reviewed(tmp_path: Path) -> None:
    stub = _stub("{not json", "{still not json")
    spans = classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=tmp_path)
    assert len(stub.calls) == 2
    assert _classes(spans) == ["REVIEW"] and "gate 0" in (spans[0].review_reason or "")


def test_the_retry_is_used_when_the_second_answer_parses(tmp_path: Path) -> None:
    stub = _stub("truncated {\"spans\": [", ANSWER)
    assert _classes(classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=tmp_path)) == [
        "MEASUREMENT_VALUE"
    ]


def test_identical_input_is_served_from_cache(tmp_path: Path) -> None:
    """Reproducibility comes from here, not from temperature 0 (D7)."""
    stub = _stub()
    first = classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=tmp_path)
    second = classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=tmp_path)
    assert len(stub.calls) == 1
    assert first == second


def test_a_prompt_change_invalidates_the_cache(tmp_path: Path) -> None:
    stub = _stub()
    classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=tmp_path)
    classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=tmp_path, every_numeral=True)
    assert len(stub.calls) == 2


def test_cache_key_separates_criteria_and_models(tmp_path: Path) -> None:
    stub = _stub()
    classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=tmp_path)
    classify_criterion("Serum AST > 3 x ULN", stub, cache_dir=tmp_path)
    classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=tmp_path, model="other/model")
    assert len(stub.calls) == 3


def test_cache_is_skipped_when_no_directory_is_given(tmp_path: Path) -> None:
    stub = _stub()
    classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=None)
    classify_criterion("Serum ALT > 3 x ULN", stub, cache_dir=None)
    assert len(stub.calls) == 2


def test_classify_criteria_output_is_aligned_to_input_order(tmp_path: Path) -> None:
    texts = [f"Serum ALT > {n} x ULN" for n in range(12)]
    stub = _stub()
    batches = classify_criteria(texts, stub, cache_dir=tmp_path, max_workers=8)
    assert len(batches) == len(texts)
    # Every criterion carries its own numeral, so a shuffled result would misalign here.
    assert all(str(n) in "".join(s.threshold_phrase for s in batch)
               for n, batch in enumerate(batches) if n != 3)


def test_every_numeral_paragraph_is_off_by_default() -> None:
    """ADR-032 lists it as an unvalidated prompt change; G7 covers the same failure."""
    assert "EVERY NUMERAL" not in instruction_tail()
    assert "EVERY NUMERAL" in instruction_tail(every_numeral=True)


# ---------------------------------------------------------------------------
# Drift: the prompt and the family list have exactly one source of truth
# ---------------------------------------------------------------------------

def _taxonomy_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "build_value_taxonomy", ROOT / "scripts" / "build_value_taxonomy.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_prompt_matches_the_renderer() -> None:
    """The classifier reads a file; the file must still be the taxonomy's pure function."""
    module = _taxonomy_module()
    assert PROMPT_PATH.read_text().rstrip("\n") == module.render_prompt(module.build()).rstrip("\n")


def test_non_criterion_families_match_the_taxonomy() -> None:
    module = _taxonomy_module()
    assert NON_CRITERION_FAMILIES == {f["id"] for f in module.NON_CRITERION_FAMILIES}


def test_span_classes_match_the_taxonomy() -> None:
    module = _taxonomy_module()
    assert SPAN_CLASSES == {c["id"] for c in module.CLASSES}
