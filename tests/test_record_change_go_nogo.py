"""The go/no-go rows, end to end: their real answers in, a record-change skip out.

"Stable antidiabetic background medication (unchanged daily dose) for at least 8 weeks prior
to" (CARMELINA inclusion 7; CAROLINA inclusion 37/38/41, their arm-B and P2-NEW counterparts)
asks that a dose stayed the same across a period. CIRCE cannot test that; at ``b027a7d`` the
build emitted these rows as DrugExposure PRESENCE (Occurrence Type 2, Count 1) -- "some
antidiabetic exposure exists" -- which is not what the protocol line says.

Four calls per row (coordinator, 2026-10-15): calls 1 and 2 are stage 2's `current` and
`placebo` prompts and decide every field but record_change; call 3 (`cf`) is made on every row
and read for record_change only; call 4 (`pf`) only when call 3 fills it, and the fill is kept
only when call 4 fills one too. The build records a kept fill as
``record-change-not-representable``, a group label takes its members, the delivery gate
re-judges the skip from the store row, and a row with that fill that reached a rule anyway fails
the gate.

Every case is a real row of the P3 dry run (arm A / arm B / P2-NEW stores, verbatim) with the
real gemma-4-E4B answers of every call where one exists
(``tests/fixtures/record_change_go_nogo_rows.json``, written by
``overfill/analysis_cfpf/make_record_change_fixture.py``; rows chosen before any answer existed):
calls 1 and 2 from stage 2 (call 1 from the stability run for arm-B rows -- the same prompt),
calls 3 and 4 from the cf / pf re-check. Stage 2 did not run arm B, so no call-2 answer exists
for an arm-B row; a row whose call 1 asks for call 2 without one is not "replayable", and the
end-to-end build uses only replayable rows (the excluded ones are named in a test). The stub
answers each call by which of the four prompts it was sent, and each call is checked to send
exactly the prompt its answer was given to.
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
GO_NOGO = sorted(k for k, r in CASES.items() if r["group"] in ("gonogo", "counterpart"))
CHANGE = sorted(k for k, r in CASES.items() if r["group"] == "change")
CONTROLS = sorted(k for k, r in CASES.items() if r["group"] == "control")
REASON = getattr(annotation, "RECORD_CHANGE_REASON", "record-change-not-representable")
#: Keys a store row carries from the P3 dry run's own annotation, removed before re-annotating.
_STALE = (
    "annotation", "_annotationRejected", "_windowDisagreement", "_annotationAgreement",
    "_recordChangeAgreement",
)
#: The four calls of a row, by the arm of the over-fill A/B whose prompt each sends.
CALLS = {
    "current": ("ANNOTATION_SYSTEM_PROMPT", "ANNOTATION_PROMPT"),
    "placebo": ("AGREEMENT_SYSTEM_PROMPT", "AGREEMENT_PROMPT"),
    "cf": ("RECORD_CHANGE_SYSTEM_PROMPT", "RECORD_CHANGE_PROMPT"),
    "pf": ("RECORD_CHANGE_AGREEMENT_SYSTEM_PROMPT", "RECORD_CHANGE_AGREEMENT_PROMPT"),
}


class _NoMeasuredAnswerError(RuntimeError):
    """Raised for a call no measured answer exists for (call 2 of an arm-B row)."""


class _Replay:
    """The chat model, replaced: answers each call with the recorded answer of the arm whose
    prompt it was sent, rendered for this row by the production renderer."""

    def __init__(self, case: dict[str, Any]) -> None:
        self.answers = {arm: a["content"] for arm, a in case["answers"].items()}
        self.prompts = {
            arm: (
                getattr(annotation, system, None),
                annotation.render_prompt(
                    case["row"], case["members"], case["role"],
                    getattr(annotation, template, annotation.ANNOTATION_PROMPT),
                ),
            )
            for arm, (system, template) in CALLS.items()
        }
        self.calls: list[tuple[str, ...]] = []
        self.arms: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        sent = tuple(str(m.content) for m in messages)
        arms = [a for a, prompt in self.prompts.items() if prompt == sent]
        assert len(arms) == 1, f"the call matches {arms} of the four prompts"
        self.calls.append(sent)
        self.arms.append(arms[0])
        if arms[0] not in self.answers:
            raise _NoMeasuredAnswerError(f"no measured {arms[0]} answer for this row")
        return AIMessage(content=self.answers[arms[0]])


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
    llm = _Replay(case)
    annotation.annotate_row(row, case["members"], case["role"], model="stub", llm=llm)
    return row, llm


def _replayable(spec: tuple[str, str, str]) -> bool:
    """Every call production makes for this row has a measured answer."""
    _row, llm = _annotate(spec)
    return all(arm in CASES[spec]["answers"] for arm in llm.arms)


def _sha(call: tuple[str, ...]) -> str:
    return hashlib.sha256(json.dumps(list(call), ensure_ascii=False).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# The calls
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", sorted(CASES), ids=lambda s: ":".join(s))
def test_should_send_the_four_prompts_the_a_b_measured(spec):
    """Calls 1-4 send exactly what stage 2 sent as current / placebo and the re-check as cf / pf
    (sha256 of the harness's rendering, from the fixture), in that order."""
    _row, llm = _annotate(spec)
    want = CASES[spec]["promptSha256"]
    assert [_sha(call) for call in llm.calls] == [want[arm] for arm in llm.arms]
    assert llm.arms == sorted(llm.arms, key=list(CALLS).index)
    assert {"current", "cf"} <= set(llm.arms)


def test_should_name_the_rows_no_measured_call_two_answer_covers():
    """Stage 2 did not run arm B. These arm-B rows' call 1 fills a field the agreement call
    checks, and no measured call-2 answer exists, so the end-to-end build leaves them out."""
    assert sorted(k for k in CASES if not _replayable(k)) == [
        ("carmelina@b", "inclusion", str(i)) for i in (10, 11, 12, 14, 15)
    ] + [("carolina@b", "inclusion", "28"), ("carolina@b", "inclusion", "29")]


@pytest.mark.parametrize("spec", GO_NOGO, ids=lambda s: ":".join(s))
def test_should_keep_record_change_stable_on_every_go_nogo_row(spec):
    """Calls 3 and 4 alone decide it, so this holds on every go/no-go row and counterpart,
    replayable or not (a missing call-2 answer touches only calls 1-2's fields)."""
    row, llm = _annotate(spec)
    stored = row[ANNOTATION_KEY]
    assert stored.get("record_change") == "stable", stored
    assert span_in_line(stored.get("record_change_span"), row["protocolLine"])
    assert llm.arms[-2:] == ["cf", "pf"]
    assert row["_recordChangeAgreement"]["kept"]["record_change"]["value"] == "stable"


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


def _built(specs: list[tuple[str, str, str]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """The given rows, annotated from their real answers, as one eligibility block per study.

    :returns: trial key (``carolina``, ``carolina@b``, ...) -> its eligibility block.
    """
    by_trial: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"inclusionCriteria": [], "exclusionCriteria": []}
    )
    for spec in sorted(specs, key=lambda s: (s[0], s[1], int(s[2]))):
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


def _build(service: Any, eligibility: dict[str, Any]) -> dict[str, Any]:
    return service._build_seeded_target_circe(
        {"targetCohortName": "linagliptin", **copy.deepcopy(eligibility)}
    )


def test_should_record_every_replayable_go_nogo_row_as_a_record_change_skip(service):
    """Not conditional, not emitted: calls 1 and 2 (stage 2's prompts) keep no conditional on
    these rows, and calls 3 and 4 keep `stable`. The gate re-judges every such skip clean."""
    from scripts.verify_circe_delivery import criteria_index, skipped_criteria_violations

    replayable = [k for k in CASES if _replayable(k)]
    checked = []
    for trial, eligibility in _built(replayable).items():
        circe = _build(service, eligibility)
        skips = {(r["role"], r["criterionId"]): r for r in circe["_skippedCriteria"]}
        for spec in GO_NOGO:
            if spec[0] != trial or spec not in replayable:
                continue
            role, rid = spec[1], spec[2]
            skip = skips.get((role, rid))
            assert skip is not None and skip["reason"] == REASON, (
                f"{':'.join(spec)} is not recorded as {REASON}: skip {skip}, "
                f"emitted {_emitted(circe, role, rid)}"
            )
            assert skip["recordChange"] == "stable"
            decider = next(
                r for r in eligibility[f"{role}Criteria"]
                if str(r["id"]) == skip["recordChangeDecidedBy"]
            )
            assert span_in_line(skip["recordChangeSpan"], decider["protocolLine"])
            assert skip["recordChangeAgreement"]["promptVersion"] == (
                annotation.RECORD_CHANGE_AGREEMENT_PROMPT_VERSION
            )
            assert _emitted(circe, role, rid) == []
            checked.append(spec)
        allowed = [r for r in circe["_skippedCriteria"] if r["reason"] == REASON]
        study = {"eligibility": copy.deepcopy(eligibility)}
        assert skipped_criteria_violations(allowed, criteria_index(study), circe) == []
        records = circe[annotation.RECORD_CHANGE_RECORDS_KEY]
        listed = {(r["role"], r["criterionId"]) for r in records}
        assert {(r["role"], r["criterionId"]) for r in allowed} <= listed
    # 7 of the 9 go/no-go rows (carolina@b 28 / 29 have no measured call-2 answer) + the 3
    # P2-NEW counterparts
    assert len(checked) == 10, checked


def test_should_record_the_change_in_dose_exclusion_as_a_record_change_skip(service):
    """CAROLINA exclusion 19, "Change in dose(age) of thyroid hormones within 6 weeks": calls 3
    and 4 both say `changed`; built through the exclusion loop, it is a record-change skip."""
    (spec,) = CHANGE
    assert _replayable(spec)
    circe = _build(service, _built([spec])[spec[0]])
    skip = next(r for r in circe["_skippedCriteria"] if (r["role"], r["criterionId"]) == spec[1:])
    assert skip["reason"] == REASON and skip["recordChange"] == "changed"


@pytest.mark.parametrize("spec", CONTROLS, ids=lambda s: ":".join(s))
def test_should_not_skip_a_control_for_record_change(spec, service):
    assert _replayable(spec)
    row, llm = _annotate(spec)
    assert row[ANNOTATION_KEY].get("record_change") in (None, "none")
    assert "pf" not in llm.arms
    circe = _build(service, _built([spec])[spec[0]])
    assert not [r for r in circe["_skippedCriteria"] if r["reason"] == REASON]


# --------------------------------------------------------------------------- #
# The lint: a row with a kept record_change fill that reached a rule anyway
# --------------------------------------------------------------------------- #


def _bypassed(
    service: Any, monkeypatch: Any, spec: tuple[str, str, str]
) -> tuple[dict, dict, dict]:
    """CARMELINA inclusion 7 annotated from its real answers, built twice: as the build does it,
    and with the record-change skip bypassed (the construct a producer bug would be)."""
    eligibility = _built([spec])[spec[0]]
    honest = _build(service, eligibility)
    monkeypatch.setattr("src.services.tte_service.record_change_skips", lambda rows: {})
    bypassed = _build(service, eligibility)
    return honest, bypassed, {"eligibility": copy.deepcopy(eligibility)}


def test_should_find_the_go_nogo_row_when_its_skip_was_bypassed(service, monkeypatch):
    from src.utils.circe_lint import record_change_occurrence_criteria

    spec = ("carmelina", "inclusion", "7")
    honest, bypassed, study = _bypassed(service, monkeypatch, spec)
    assert _emitted(bypassed, "inclusion", "7"), "the bypass did not emit the row"
    assert record_change_occurrence_criteria(honest, study) == []
    (finding,) = record_change_occurrence_criteria(bypassed, study)
    assert "inclusion #7" in finding and "stable" in finding


def test_should_fail_the_delivery_gate_on_the_bypassed_row(service, monkeypatch, tmp_path, capsys):
    import scripts.verify_circe_delivery as gate

    spec = ("carmelina", "inclusion", "7")
    honest, bypassed, study = _bypassed(service, monkeypatch, spec)

    def run(expression: dict[str, Any], where: Path) -> str:
        # The gate pins the store it resolved into the environment; each run starts clear
        # (monkeypatch restores the environment at teardown).
        for name in ("TTE_STORE_PATH", "TTE_DRUG_ANCHORED_ENTRY"):
            monkeypatch.delenv(name, raising=False)
        where.mkdir()
        stored = {
            "id": 9, "name": "Study 9", "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "linagliptin"}, {"name": "placebo"}],
            "eligibility": {**study["eligibility"], "structuredExpression": expression},
        }
        for role in ("treatment", "comparator"):
            (where / f"carmelina_{role}.circe.json").write_text(json.dumps(expression))
        store = where / "studies.json"
        store.write_text(json.dumps([stored]))
        rc = gate.main(["--dir", str(where), "--store", str(store), "--map", "carmelina=9"])
        captured = capsys.readouterr()
        return f"rc={rc}\n{captured.out}\n{captured.err}"

    clean, caught = run(honest, tmp_path / "honest"), run(bypassed, tmp_path / "bypassed")
    assert clean.startswith("rc=") and "record_change criterion emitted" not in clean
    assert caught.startswith("rc=1") and "record_change criterion emitted (1)" in caught, caught
