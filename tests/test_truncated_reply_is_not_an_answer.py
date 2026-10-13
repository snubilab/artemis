"""A reply cut off mid-item is a failed call, never a shorter or different answer.

``src.utils.llm._last_json_value`` is the fallback three call sites use when a reply is
not one JSON value (segmentation, criterion annotation, specimen critic), and the
reasoning-preamble strip every vLLM caller goes through (``extract_answer``). It returned
the longest COMPLETE value anywhere in the text, so on a reply cut inside its second
item it returned the first item: an inner object handed to the caller as the whole
answer, and cached as one.

Measured on 1835b17 with the replies below:
- annotation: the P3 dry-run answer for LEADER's revascularization line, cut inside its
  second excepted entity, came back as ``{"text": "coronary artery revascularization",
  "span": "coronary"}`` and was written to the annotation cache;
- segmentation: PLATO's registry eligibility, answered as the corpus truth answers it,
  cut inside the last exclusion item, came back as the INCLUSION section object -- read
  as "no criteria in this part", recorded as no rejection, and cached;
- ``extract_answer`` after a reasoning preamble returned that inner object with strategy
  ``last_json``.

Where the provider reports ``finish_reason="length"`` the three sites refuse first
(``raise_if_truncated``); these replies carry no metadata, which is what a provider that
does not report it (the Azure transport sets none) hands over.

No LLM is called: each call site's model is a stub returning the text.
"""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.utils.llm import _last_json_value, extract_answer

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: P3 dry-run (output/site_gap/2026-10-12_p3_dry/arm_a/caches/annotations.jsonl): the
#: annotation answer for LEADER's "Currently planned coronary, carotid, or peripheral
#: artery revascularization".
ANNOTATION = {
    "record_requirement": "forbidden", "conditional_span": None,
    "excepted_entities": [
        {"text": "coronary artery revascularization", "span": "coronary"},
        {"text": "peripheral artery revascularization", "span": "peripheral"},
    ],
    "base_span": "coronary, carotid, or peripheral artery revascularization",
    "relation": "any", "relation_span": ", ", "cardinality": None, "timing": "prospective",
    "window_span": None, "route": ["any"], "route_span": None, "specimen": "any",
    "specimen_span": None, "no_entity": "none", "no_entity_span": None,
    "threshold_span": None, "quantity_kind": None, "reference_bound": None,
}
LEADER_LINE = "Currently planned coronary, carotid, or peripheral artery revascularization"


def _cut_inside(text: str, fragment: str) -> str:
    """``text`` up to the middle of ``fragment``: a reply stopped mid-item."""
    at = text.index(fragment)
    return text[: at + len(fragment) // 2]


ANNOTATION_CUT = _cut_inside(json.dumps(ANNOTATION), "peripheral artery revascularization")


def _segmentation_reply() -> tuple[str, str]:
    """PLATO's registry eligibility answered as the corpus truth answers it: (whole, cut)."""
    truth = json.loads((FIXTURES / "segmentation" / "corpus_truth.json").read_text())
    source = next(s for s in truth["sources"] if s["id"] == "PLATO.nct")
    answer = {}
    for kind in ("inclusion", "exclusion"):
        section = dict(source[kind][0])
        section.pop("span", None)
        section.setdefault("interruptions", [])
        answer[kind] = section
    whole = json.dumps(answer, ensure_ascii=False)
    return whole, _cut_inside(whole, answer["exclusion"]["items"][-1]["start"])


class _Model:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return AIMessage(content=self.reply)


# ── the shared extraction ────────────────────────────────────


def test_should_find_no_answer_in_a_reply_cut_inside_its_second_item():
    assert _last_json_value(ANNOTATION_CUT) is None


def test_should_leave_a_cut_reply_after_a_reasoning_preamble_unextracted():
    text = "Thinking Process:\n1. Read the line.\n\n" + ANNOTATION_CUT

    cleaned, strategy = extract_answer(text)

    assert strategy == "none", cleaned
    assert cleaned == text


def test_should_still_extract_a_whole_reply_after_a_preamble_that_quotes_a_cut_object():
    """A broken object in the reasoning ends before the answer; it encloses nothing."""
    answer = json.dumps(ANNOTATION)
    text = 'Thinking Process:\nthe schema starts {"record_requirement": and so on.\n\n' + answer

    cleaned, strategy = extract_answer(text)

    assert strategy == "last_json"
    assert json.loads(cleaned) == ANNOTATION


# ── criterion annotation ─────────────────────────────────────


@pytest.fixture
def annotation(tmp_path, monkeypatch):
    from src.services import criterion_annotation

    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    criterion_annotation.reset_for_tests()
    yield criterion_annotation
    criterion_annotation.reset_for_tests()


def test_should_record_an_error_and_cache_nothing_when_the_annotation_reply_is_cut(annotation):
    row = {"id": "21", "protocolLine": LEADER_LINE}
    model = _Model(ANNOTATION_CUT)

    first = annotation.annotate_row(row, [], "exclusion", model="stub", llm=model)
    again = annotation.annotate_row(dict(row), [], "exclusion", model="stub", llm=model)

    assert first == again == "error"
    assert "JSONDecodeError" in row[annotation.ANNOTATION_KEY]["error"], row
    assert model.calls == 2, "a cut reply was replayed from the annotation cache"


def test_should_annotate_and_cache_the_whole_reply(annotation):
    row = {"id": "21", "protocolLine": LEADER_LINE}
    model = _Model(json.dumps(ANNOTATION))

    assert annotation.annotate_row(row, [], "exclusion", model="stub", llm=model) == "called"
    assert annotation.annotate_row(dict(row), [], "exclusion", model="stub", llm=model) == "cached"
    assert "error" not in row[annotation.ANNOTATION_KEY], row
    assert row[annotation.ANNOTATION_KEY]["record_requirement"] == "forbidden"


# ── eligibility segmentation ─────────────────────────────────


@pytest.fixture
def segmentation(tmp_path, monkeypatch):
    from src.agents.agent1 import segmentation

    monkeypatch.setenv("ARTEMIS_SEGMENTATION_CACHE_PATH", str(tmp_path / "segments.jsonl"))
    monkeypatch.delenv("ARTEMIS_SEGMENTATION_CACHE", raising=False)
    segmentation.reset_cache_for_tests()
    yield segmentation
    segmentation.reset_cache_for_tests()


def _plato_text() -> str:
    from tests.test_eligibility_segmentation import text_of

    return text_of("PLATO.nct")


def test_should_record_a_failed_part_and_cache_nothing_when_the_segmentation_reply_is_cut(
    segmentation, monkeypatch
):
    _whole, cut = _segmentation_reply()
    model = _Model(cut)
    monkeypatch.setattr(segmentation, "_build_llm", lambda _model: model)

    first = segmentation.segment_eligibility(_plato_text(), model="stub-model")
    segmentation.reset_cache_for_tests()
    segmentation.segment_eligibility(_plato_text(), model="stub-model")

    assert first.criteria() == {"inclusion": [], "exclusion": []}
    assert [r.reason for r in first.failures] == [segmentation.REASON_CALL_FAILED], first.rejected
    assert model.calls == 2, "a cut reply was replayed from the segmentation cache"


def test_should_segment_the_whole_reply(segmentation, monkeypatch):
    whole, _cut = _segmentation_reply()
    monkeypatch.setattr(segmentation, "_build_llm", lambda _model: _Model(whole))

    result = segmentation.segment_eligibility(_plato_text(), model="stub-model")

    assert result.criteria()["inclusion"] and result.criteria()["exclusion"]
    assert result.failures == []


# ── specimen critic: refused a cut reply already (its answer holds no nested value) ──

#: P3 dry-run (arm_a/caches/specimen_judgements.jsonl) answer shape, cut inside its third
#: identifier, and cut after its list (the closing brace lost).
SPECIMEN_CUTS = {
    "inside an identifier": '{"accepted": ["V1", "V2", "V',
    "after the list": '{"accepted": ["V1", "V2", "V3", "V4"]',
}


@pytest.mark.parametrize("case", sorted(SPECIMEN_CUTS))
def test_should_give_no_judgement_and_cache_nothing_when_the_specimen_reply_is_cut(
    tmp_path, monkeypatch, case
):
    from src.agents.agent2 import specimen_critic
    from src.services.loinc_specimen import SpecimenOption

    monkeypatch.setenv("ARTEMIS_SPECIMEN_CRITIC_CACHE_PATH", str(tmp_path / "judgements.jsonl"))
    monkeypatch.delenv("ARTEMIS_SPECIMEN_CRITIC_CACHE", raising=False)
    specimen_critic.reset_for_tests()
    model = _Model(SPECIMEN_CUTS[case])
    options = [SpecimenOption(None, f"System {i}", None) for i in range(4)]

    for _ in range(2):
        assert specimen_critic.judge_specimen_options(
            protocol_line=LEADER_LINE, analyte="Glucose", specimen="any", specimen_span=None,
            options=options, model="stub", llm=model,
        ) is None
    assert model.calls == 2
    specimen_critic.reset_for_tests()
