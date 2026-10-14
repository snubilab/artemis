"""An annotation fill is kept only when a second, reworded prompt gives it too.

Stage 2 of the over-fill A/B (gemma-4-E4B,
output/site_gap/2026-10-12_p3_dry/overfill/analysis_stage2/): a wrong excepted entity changes
under almost any rewording of the prompt while a correct one recurs -- under the `placebo`
rewording 27 of 27 correct spans reappear and 37 of 126 wrong ones do. Keeping an excepted
entity only when the same verified span (the same offsets in protocolLine) is in both answers
fixes 44.7 of 62 wrong-exception rows and breaks 0 of 113 controls; the same agreement on
``record_requirement: conditional`` and on ``no_entity`` != ``none`` moves 6 and 2 more rows.

So the annotation step makes its first call with the measured `current` wording and, only when
that answer fills ``excepted_entities``, ``record_requirement: conditional`` or a ``no_entity``
other than ``none``, a second call with the `placebo` wording. Every comparison is of offsets
or enum values.

Each case is a real row of the P3 dry run with the two real answers stage 2 recorded for it
(``tests/fixtures/annotation_agreement_rows.json``). The model is replaced by a stub that
replays them: the first call gets the `current` answer, the second the `placebo` answer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import zlib
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation
from src.services.criterion_annotation import (
    ANNOTATION_KEY,
    CONDITIONAL_REASON,
    conditional_skips,
    stated_base,
    stated_exceptions,
    stated_no_entity,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "annotation_agreement_rows.json").read_text()
)
CASES = {(r["trial"], r["role"], r["id"]): r for r in FIXTURE["rows"]}
#: Keys a store row carries from the P3 dry run's own annotation, removed before re-annotating.
_STALE = ("annotation", "_annotationRejected", "_windowDisagreement", "_annotationAgreement")


class _Replay:
    """The chat model, replaced: answers each call with the next recorded reply, in order."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append(tuple(str(m.content) for m in messages))
        assert len(self.calls) <= len(self.replies), "more calls than recorded answers"
        reply = self.replies[len(self.calls) - 1]
        if isinstance(reply, Exception):
            raise reply
        return AIMessage(content=reply)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


def _fresh(case: dict[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(case["row"])
    for key in _STALE:
        row.pop(key, None)
    return row


def _annotate(
    spec: tuple[str, str, str], *replies: str | Exception
) -> tuple[dict[str, Any], _Replay]:
    case = CASES[spec]
    answers = case["answers"]
    llm = _Replay(*(replies or (answers["current"]["content"], answers["placebo"]["content"])))
    row = _fresh(case)
    annotation.annotate_row(row, case["members"], case["role"], model="stub", llm=llm)
    return row, llm


def _spans(entries: list[dict[str, Any]]) -> list[str]:
    return [e["span"] for e in entries]


def _agreement(row: dict[str, Any]) -> dict[str, Any]:
    record = row.get(getattr(annotation, "AGREEMENT_KEY", "_annotationAgreement"))
    assert isinstance(record, dict), f"no agreement record on the row: {sorted(row)}"
    return record


# --------------------------------------------------------------------------- #
# excepted_entities
# --------------------------------------------------------------------------- #


class TestExceptedEntities:
    def test_should_drop_every_excepted_entity_when_the_reworded_answer_gives_none(self):
        """CARMELINA exclusion 16 (target): ALT and alkaline phosphatase are thresholds of the
        criterion, not entities removed from it; the `placebo` answer excepts nothing."""
        row, llm = _annotate(("carmelina", "exclusion", "16"))

        assert len(llm.calls) == 2
        assert row[ANNOTATION_KEY]["excepted_entities"] == []
        assert row[ANNOTATION_KEY]["base_span"] is None
        assert stated_exceptions(row) == [] and stated_base(row) is None
        dropped = _agreement(row)["dropped"]
        assert sorted(_spans(dropped["excepted_entities"])) == [
            "ALT (SGPT)",
            "alkaline phosphatase (AP)",
        ]
        assert dropped["base_span"] == (
            "serum levels of either ALT (SGPT), AST (SGOT), or alkaline phosphatase (AP)"
        )
        assert "excepted_entities" not in _agreement(row)["kept"]

    def test_should_drop_every_excepted_entity_when_the_two_answers_share_no_span(self):
        """LEADER exclusion 16 (target): `current` excepts coronary and peripheral, `placebo`
        excepts carotid -- no span sits at the same offsets in both."""
        row, _llm = _annotate(("leader", "exclusion", "16"))

        assert row[ANNOTATION_KEY]["excepted_entities"] == []
        assert row[ANNOTATION_KEY]["base_span"] is None
        assert sorted(_spans(_agreement(row)["dropped"]["excepted_entities"])) == [
            "coronary",
            "peripheral",
        ]

    def test_should_keep_only_the_excepted_entity_both_answers_give_and_the_first_base_span(self):
        """CARMELINA inclusion 6: `current` excepts three drug classes, `placebo` one of them."""
        row, _llm = _annotate(("carmelina", "inclusion", "6"))

        assert _spans(row[ANNOTATION_KEY]["excepted_entities"]) == ["SGLT-2 inhibitors"]
        assert row[ANNOTATION_KEY]["base_span"] == "any antidiabetic background therapy"
        record = _agreement(row)
        assert _spans(record["kept"]["excepted_entities"]) == ["SGLT-2 inhibitors"]
        assert sorted(_spans(record["dropped"]["excepted_entities"])) == [
            "DPP-4 inhibitors",
            "GLP-1 receptor agonists",
        ]
        assert "base_span" not in record["dropped"]

    def test_should_record_where_each_compared_span_sits_in_the_line(self):
        """The comparison is of offsets in protocolLine, and the record says which."""
        row, _llm = _annotate(("carmelina", "inclusion", "6"))
        line = row["protocolLine"]
        (kept,) = _agreement(row)["kept"]["excepted_entities"]
        start, end = kept["offsets"]
        assert line[start:end] == "SGLT-2 inhibitors"

    def test_should_keep_a_correct_exception_both_answers_give(self):
        """EMPA-REG exclusion 19 (fill control): cancer except basal cell carcinoma."""
        row, _llm = _annotate(("empa-reg", "exclusion", "19"))

        assert _spans(stated_exceptions(row)) == ["basal cell carcinoma"]
        assert stated_base(row) == "cancer"
        assert _agreement(row)["dropped"] == {}

    def test_should_keep_three_correct_exceptions_both_answers_give(self):
        """LEADER exclusion 41 (fill control): insulin other than NPH, long-acting or premixed."""
        row, _llm = _annotate(("leader", "exclusion", "41"))

        assert _spans(stated_exceptions(row)) == [
            "human NPH insulin",
            "long-acting insulin analogue",
            "premixed insulin",
        ]
        assert stated_base(row) == "insulin"


# --------------------------------------------------------------------------- #
# record_requirement: conditional
# --------------------------------------------------------------------------- #


class TestConditional:
    def test_should_drop_conditional_when_the_reworded_answer_does_not_say_conditional(self):
        """ARISTOTLE exclusion 15 (target, a group label): `current` says conditional, `placebo`
        says required. The fill is dropped to absent -- the value a rejected field takes."""
        row, _llm = _annotate(("aristotle", "exclusion", "15"))

        assert row[ANNOTATION_KEY]["record_requirement"] is None
        assert row[ANNOTATION_KEY]["conditional_span"] is None
        rows = [row, *copy.deepcopy(CASES[("aristotle", "exclusion", "15")]["members"])]
        for member in rows[1:]:
            for key in _STALE:
                member.pop(key, None)
        assert conditional_skips(rows) == {}
        dropped = _agreement(row)["dropped"]["record_requirement"]
        assert dropped["value"] == "conditional"
        assert _agreement(row)["second"]["record_requirement"] == "required"

    def test_should_keep_conditional_when_both_answers_say_conditional(self):
        """ARISTOTLE inclusion 4 (fill control): 'If not in atrial fibrillation/flutter at the time
        of enrollment, must have ...' applies only to that subgroup."""
        row, _llm = _annotate(("aristotle", "inclusion", "4"))

        assert row[ANNOTATION_KEY]["record_requirement"] == "conditional"
        skip = conditional_skips([row])["4"]
        record = _agreement(row)
        assert record["kept"]["record_requirement"]["value"] == "conditional"
        assert (skip.agreement_version, skip.agreement_key) == (
            record["promptVersion"],
            record["cacheKey"],
        )


# --------------------------------------------------------------------------- #
# no_entity
# --------------------------------------------------------------------------- #


class TestNoEntity:
    def test_should_drop_no_entity_when_the_reworded_answer_says_none_and_keep_the_exceptions(self):
        """LEADER exclusion 40 (target): `current` calls the insulin line an investigator's
        judgement; `placebo` says it names an entity. Its three exceptions are in both answers;
        base_span comes from the first answer ('insulin'), not the second ('Use of insulin')."""
        row, _llm = _annotate(("leader", "exclusion", "40"))

        assert row[ANNOTATION_KEY]["no_entity"] is None
        assert row[ANNOTATION_KEY]["no_entity_span"] is None
        assert stated_no_entity(row) is None
        assert _agreement(row)["dropped"]["no_entity"]["value"] == "investigator_judgement"
        assert len(stated_exceptions(row)) == 3
        assert stated_base(row) == "insulin"

    def test_should_keep_no_entity_when_both_answers_give_the_same_value(self):
        """CAROLINA exclusion 69 (fill control): 'Patients considered unreliable by the
        investigator'."""
        row, _llm = _annotate(("carolina", "exclusion", "69"))

        statement = stated_no_entity(row)
        assert statement is not None and statement.kind.value == "investigator_judgement"
        assert _agreement(row)["kept"]["no_entity"]["value"] == "investigator_judgement"

    def test_should_drop_no_entity_when_the_two_answers_give_different_values(self):
        """DECLARE exclusion 48: `current` refers_elsewhere, `placebo` investigator_judgement. The
        rule keeps a no_entity fill only when both answers give the same value."""
        row, _llm = _annotate(("declare", "exclusion", "48"))

        assert row[ANNOTATION_KEY]["no_entity"] is None
        assert _agreement(row)["dropped"]["no_entity"]["value"] == "refers_elsewhere"
        assert _agreement(row)["second"]["no_entity"] == "investigator_judgement"


# --------------------------------------------------------------------------- #
# When the second call is made, and what it sends
# --------------------------------------------------------------------------- #


class TestTheSecondCall:
    def test_should_not_make_the_second_call_when_the_first_answer_fills_none_of_the_three(self):
        """DECLARE exclusion 2 (neighbour control): the `current` answer fills nothing the rule
        compares (its `placebo` answer happens to say conditional, which must never be asked)."""
        row, llm = _annotate(("declare", "exclusion", "2"))

        assert len(llm.calls) == 1
        assert "_annotationAgreement" not in row
        expected, _rejected = annotation.validate_annotation(
            json.loads(CASES[("declare", "exclusion", "2")]["answers"]["current"]["content"]),
            row["protocolLine"],
        )
        assert {k: row[ANNOTATION_KEY][k] for k in expected} == expected

    @pytest.mark.parametrize("spec", sorted(CASES), ids=lambda s: ":".join(s))
    def test_should_send_the_prompts_stage_two_sent_as_current_and_placebo(self, spec):
        """Byte identity, per row: the first call is what stage 2 sent as `current`, the second
        what it sent as `placebo` (sha256 of the harness's own rendering, from the fixture)."""
        _row, llm = _annotate(spec)
        want = CASES[spec]["stage2PromptSha256"]
        sent = [
            hashlib.sha256(json.dumps(list(call), ensure_ascii=False).encode("utf-8")).hexdigest()
            for call in llm.calls
        ]
        assert sent[0] == want["current"]
        if len(sent) > 1:
            assert sent[1] == want["placebo"]

    def test_should_hold_the_two_prompts_stage_two_measured(self):
        prompts = FIXTURE["stage2Prompts"]
        assert (annotation.ANNOTATION_SYSTEM_PROMPT, annotation.ANNOTATION_PROMPT) == (
            prompts["current"]["system"],
            prompts["current"]["userTemplate"],
        )
        assert (annotation.AGREEMENT_SYSTEM_PROMPT, annotation.AGREEMENT_PROMPT) == (
            prompts["placebo"]["system"],
            prompts["placebo"]["userTemplate"],
        )

    def test_should_cache_both_calls_under_their_own_keys_and_replay_them(self, tmp_path):
        spec = ("leader", "exclusion", "40")
        first, llm = _annotate(spec)
        again, replay = _annotate(spec)  # offered the same answers; the cache must answer instead
        assert len(llm.calls) == 2 and len(replay.calls) == 0
        assert again[ANNOTATION_KEY] == first[ANNOTATION_KEY]
        assert _agreement(again)["outcome"] == "cached"
        records = [
            json.loads(line) for line in (tmp_path / "annotations.jsonl").read_text().splitlines()
        ]
        assert len({r["key"] for r in records}) == 2
        assert {r["promptVersion"] for r in records} == {
            annotation.ANNOTATION_PROMPT_VERSION,
            annotation.AGREEMENT_PROMPT_VERSION,
        }
        assert annotation.ANNOTATION_PROMPT_VERSION != annotation.AGREEMENT_PROMPT_VERSION
        assert _agreement(again)["cacheKey"] in {r["key"] for r in records}

    def test_should_drop_every_fill_and_record_the_error_when_the_second_call_fails(self, tmp_path):
        """No second answer, so nothing is in both: the fill falls back as a disagreement does,
        and the failure is on the record, never cached."""
        case = CASES[("empa-reg", "exclusion", "19")]
        row, llm = _annotate(
            ("empa-reg", "exclusion", "19"),
            case["answers"]["current"]["content"],
            RuntimeError("vLLM went away"),
        )
        assert len(llm.calls) == 2
        assert row[ANNOTATION_KEY]["excepted_entities"] == []
        record = _agreement(row)
        assert record["outcome"] == "error" and "vLLM went away" in record["error"]
        assert _spans(record["dropped"]["excepted_entities"]) == ["basal cell carcinoma"]
        records = [
            json.loads(line) for line in (tmp_path / "annotations.jsonl").read_text().splitlines()
        ]
        assert [r["promptVersion"] for r in records] == [annotation.ANNOTATION_PROMPT_VERSION]


# --------------------------------------------------------------------------- #
# The record reaches the build's record surface
# --------------------------------------------------------------------------- #


class TestTheRecordReachesTheBuild:
    def test_should_list_every_row_the_second_call_was_made_for_with_what_it_kept_and_dropped(self):
        kept_row, _ = _annotate(("aristotle", "inclusion", "4"))
        dropped_row, _ = _annotate(("leader", "exclusion", "16"))
        untouched, _ = _annotate(("declare", "exclusion", "2"))

        records = annotation.agreement_records(
            [kept_row, untouched], "inclusion"
        ) + annotation.agreement_records([dropped_row], "exclusion")
        assert [(r["role"], r["criterionId"]) for r in records] == [
            ("inclusion", "4"),
            ("exclusion", "16"),
        ]
        assert records[0]["kept"]["record_requirement"]["value"] == "conditional"
        assert sorted(_spans(records[1]["dropped"]["excepted_entities"])) == [
            "coronary",
            "peripheral",
        ]
        assert all(
            r["promptVersion"] == annotation.AGREEMENT_PROMPT_VERSION and r["cacheKey"]
            for r in records
        )


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
                        "CONCEPT_CLASS_ID": "Ingredient"
                        if domain == "Drug"
                        else "Clinical Finding",
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


def _no_database() -> Any:
    raise RuntimeError("this test reads no database; the build reached the lab vocabulary")


@pytest.fixture
def service(monkeypatch):
    from src.services.tte_service import TTEService

    monkeypatch.setattr("src.agents.agent2.workflow.Agent2Workflow", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.retriever.ConceptRetriever", _Agent2IsStubbed)
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        return _stub_concept_set(seed_text.strip(), kwargs.get("expected_domain") or "Drug")

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    monkeypatch.setattr(svc, "_lab_test_vocabulary", _no_database)
    return svc


def test_should_carry_the_agreement_into_the_skip_record_and_the_files_record_list(service):
    """The build reads the agreed annotation; the skip it records names the second call that
    confirmed it, and the file lists every row the second call was made for. The delivery gate
    still re-judges the skip from the store row and passes it."""
    from scripts.verify_circe_delivery import criteria_index, skipped_criteria_violations

    kept, _ = _annotate(("aristotle", "inclusion", "4"))
    dropped, _ = _annotate(("leader", "exclusion", "16"))
    eligibility = {
        "targetCohortName": "apixaban",
        "inclusionCriteria": [kept],
        "exclusionCriteria": [dropped],
    }
    circe = service._build_seeded_target_circe(eligibility)

    skip = next(r for r in circe["_skippedCriteria"] if r["criterionId"] == "4")
    assert skip["reason"] == CONDITIONAL_REASON
    assert skip["conditionalAgreement"] == {
        "promptVersion": annotation.AGREEMENT_PROMPT_VERSION,
        "cacheKey": _agreement(kept)["cacheKey"],
    }
    listed = circe[annotation.AGREEMENT_RECORDS_KEY]
    assert [(r["role"], r["criterionId"]) for r in listed] == [
        ("inclusion", "4"),
        ("exclusion", "16"),
    ]
    assert sorted(_spans(listed[1]["dropped"]["excepted_entities"])) == ["coronary", "peripheral"]
    assert "exclusion:16" in circe["_criterionConceptSetRefs"]

    study = {"eligibility": {"inclusionCriteria": [kept], "exclusionCriteria": [dropped]}}
    assert skipped_criteria_violations([skip], criteria_index(study), circe) == []
