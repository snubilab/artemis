"""The go/no-go rows, end to end: their real answers in, a recorded skip out.

"Stable antidiabetic background medication (unchanged daily dose) for at least 8 weeks prior
to" (CARMELINA inclusion 7; CAROLINA inclusion 37/38/41 and their arm-B counterparts) asks
that a dose stayed the same across a period. CIRCE cannot test that; at ``b027a7d`` the build
emitted these rows as DrugExposure PRESENCE -- "some antidiabetic exposure exists" -- which is
not what the protocol line says. With ``record_change`` the annotation states it in a schema
field with a quoted span; the build records the row as a skip under
``record-change-not-representable``, a group label takes its members, and the delivery gate
re-judges the skip from the store row.

Every case is a real row of the P3 dry run (arm A / arm B stores, verbatim) with the real
gemma-4-E4B answers the cf / pf re-check recorded for it
(``tests/fixtures/record_change_go_nogo_rows.json``, written by
``overfill/analysis_cfpf/make_record_change_fixture.py``; rows chosen before any answer
existed). The model is a stub replaying them -- the first call gets the `cf` answer, the
second the `pf` answer -- and each call is checked to send exactly the prompt that answer was
given to. Controls (two disease names that describe a course, a duration, a drug) keep
emitting.
"""

from __future__ import annotations

import copy
import hashlib
import json
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation
from src.services.criterion_annotation import ANNOTATION_KEY, span_in_line

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "record_change_go_nogo_rows.json").read_text()
)
CASES = {(r["trial"], r["role"], r["id"]): r for r in FIXTURE["rows"]}
GO_NOGO = sorted(k for k, r in CASES.items() if r["group"] == "gonogo")
MEMBERS = sorted(k for k, r in CASES.items() if r["group"] == "member")
CHANGE = sorted(k for k, r in CASES.items() if r["group"] == "change")
CONTROLS = sorted(k for k, r in CASES.items() if r["group"] == "control")
#: Keys a store row carries from the P3 dry run's own annotation, removed before re-annotating.
_STALE = ("annotation", "_annotationRejected", "_windowDisagreement", "_annotationAgreement")
REASON = getattr(annotation, "RECORD_CHANGE_REASON", "record-change-not-representable")


class _Replay:
    """The chat model, replaced: answers each call with the next recorded reply, in order."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, ...]] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append(tuple(str(m.content) for m in messages))
        assert len(self.calls) <= len(self.replies), "more calls than recorded answers"
        return AIMessage(content=self.replies[len(self.calls) - 1])


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


def _annotate(spec: tuple[str, str, str]) -> tuple[dict[str, Any], _Replay]:
    case = CASES[spec]
    row = copy.deepcopy(case["row"])
    for key in _STALE:
        row.pop(key, None)
    llm = _Replay(case["answers"]["cf"]["content"], case["answers"]["pf"]["content"])
    annotation.annotate_row(row, case["members"], case["role"], model="stub", llm=llm)
    return row, llm


def _sha(call: tuple[str, ...]) -> str:
    return hashlib.sha256(json.dumps(list(call), ensure_ascii=False).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# The annotation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", sorted(CASES), ids=lambda s: ":".join(s))
def test_should_send_the_prompts_the_re_check_sent_as_cf_and_pf(spec):
    """The replayed answers were given to exactly these prompts (sha256 from the fixture)."""
    _row, llm = _annotate(spec)
    want = CASES[spec]["cfpfPromptSha256"]
    assert _sha(llm.calls[0]) == want["cf"]
    if len(llm.calls) > 1:
        assert _sha(llm.calls[1]) == want["pf"]


@pytest.mark.parametrize("spec", GO_NOGO, ids=lambda s: ":".join(s))
def test_should_keep_record_change_stable_on_every_go_nogo_row(spec):
    row, llm = _annotate(spec)
    stored = row[ANNOTATION_KEY]
    assert stored.get("record_change") == "stable", stored
    assert span_in_line(stored.get("record_change_span"), row["protocolLine"])
    assert len(llm.calls) == 2
    assert row["_annotationAgreement"]["kept"]["record_change"]["value"] == "stable"


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
                        "CONCEPT_CLASS_ID": (
                            "Ingredient" if domain == "Drug" else "Clinical Finding"
                        ),
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
        domain = kwargs.get("expected_domain") or "Drug"
        return _stub_concept_set(seed_text.strip() or "seed", domain)

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    monkeypatch.setattr(svc, "_lab_test_vocabulary", _no_database)
    return svc


def _built() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Each study of the fixture as an eligibility block, every row annotated from its real
    answers, in store id order.

    :returns: trial key (``carolina``, ``carolina@b``, ...) -> its eligibility block.
    """
    by_trial: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"inclusionCriteria": [], "exclusionCriteria": []}
    )
    for spec in sorted(CASES, key=lambda s: (s[0], s[1], int(s[2]))):
        row, _llm = _annotate(spec)
        by_trial[spec[0]][f"{spec[1]}Criteria"].append(row)
    return by_trial


def _emitted(circe: dict[str, Any], role: str, criterion_id: str) -> list[dict[str, Any]]:
    """The criteria the file emits for one row, located through its concept-set refs."""
    from src.utils.circe_lint import _leaf_codeset_id, _walk_criteria_entries

    ref = (circe.get("_criterionConceptSetRefs") or {}).get(f"{role}:{criterion_id}")
    codesets = set(ref) if isinstance(ref, (list, tuple, set)) else {ref} - {None}
    found = []
    for rule in circe.get("InclusionRules") or []:
        for entry in _walk_criteria_entries(rule.get("expression") or {}):
            if _leaf_codeset_id(entry) in codesets:
                found.append({
                    "rule": rule.get("name"),
                    "criteria": sorted(entry.get("Criteria") or {}),
                    "occurrence": entry.get("Occurrence"),
                })
    return found


def test_should_record_every_go_nogo_row_and_its_members_as_skips_not_emit_them(service):
    """Each go/no-go row and member is recorded as a skip and emits nothing. The reason is
    record-change, except where the agreed annotation also says ``conditional`` (the row's own
    or its label's): the build checks that first, and either reason is a permitted skip."""
    from scripts.verify_circe_delivery import criteria_index, skipped_criteria_violations

    trials = _built()
    checked = 0
    for trial, eligibility in trials.items():
        circe = service._build_seeded_target_circe(
            {"targetCohortName": "linagliptin", **copy.deepcopy(eligibility)}
        )
        skips = {(r["role"], r["criterionId"]): r for r in circe["_skippedCriteria"]}
        for spec in GO_NOGO + MEMBERS:
            if spec[0] != trial:
                continue
            role, rid = spec[1], spec[2]
            conditional = annotation.conditional_skips(eligibility[f"{role}Criteria"])
            want = annotation.CONDITIONAL_REASON if rid in conditional else REASON
            skip = skips.get((role, rid))
            assert skip is not None and skip["reason"] == want, (
                f"{':'.join(spec)} is not recorded as {want}: skip {skip}, "
                f"emitted {_emitted(circe, role, rid)}"
            )
            assert f"{role}:{rid}" not in circe.get("_criterionConceptSetRefs", {})
            checked += 1
            if want != REASON:
                continue
            assert skip["recordChange"] == "stable"
            decider = next(
                r for r in eligibility[f"{role}Criteria"]
                if str(r["id"]) == skip["recordChangeDecidedBy"]
            )
            assert span_in_line(skip["recordChangeSpan"], decider["protocolLine"])
        study = {"eligibility": copy.deepcopy(eligibility)}
        allowed = [r for r in circe["_skippedCriteria"] if r["reason"] == REASON]
        assert skipped_criteria_violations(allowed, criteria_index(study), circe) == []
        if allowed:
            assert circe["_generationCensus"]["skippedByReason"][REASON] == len(allowed)
    assert checked == len(GO_NOGO) + len(MEMBERS) == 15


def test_should_record_the_change_in_dose_exclusion_as_a_record_change_skip(service):
    """CAROLINA exclusion 19, "Change in dose(age) of thyroid hormones within 6 weeks": the line
    states a change; the criterion is skipped through the exclusion loop."""
    (spec,) = CHANGE
    eligibility = _built()[spec[0]]
    circe = service._build_seeded_target_circe(
        {"targetCohortName": "linagliptin", **copy.deepcopy(eligibility)}
    )
    skip = next(r for r in circe["_skippedCriteria"] if (r["role"], r["criterionId"]) == spec[1:])
    assert skip["reason"] == REASON and skip["recordChange"] in ("changed", "stable")


@pytest.mark.parametrize("spec", CONTROLS, ids=lambda s: ":".join(s))
def test_should_not_skip_a_control_for_record_change(spec, service):
    row, _llm = _annotate(spec)
    assert row[ANNOTATION_KEY].get("record_change") in (None, "none")
    eligibility = {"inclusionCriteria": [], "exclusionCriteria": []}
    eligibility[f"{spec[1]}Criteria"].append(row)
    circe = service._build_seeded_target_circe({"targetCohortName": "linagliptin", **eligibility})
    assert not [r for r in circe["_skippedCriteria"] if r["reason"] == REASON]
