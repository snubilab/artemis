"""Calls 3-4 (record_change) run beside calls 1-2-5-6, and the row comes out the same.

Call 3 is made whatever call 1 answers, and the two branches read only the row's extracted
fields (``render_prompt``) -- neither reads what the other writes. So ``annotate_row`` may send
call 3 before call 1 returns. These tests pin two things: the branches really are in flight
together (a barrier both must reach before either answers), and the merged row -- every key,
in the same order -- and the cache keys written equal the sequential run's for the same answers.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_store_rows.json").read_text()
)
ROW = FIXTURE["carmelina_inclusion_7"]
SPAN = "(unchanged daily dose)"
FRAGMENT = "for at least 8 weeks"

CONDITIONAL = {"record_requirement": "conditional", "conditional_span": FRAGMENT,
               "excepted_entities": []}
STABLE = {"record_change": "stable", "record_change_span": SPAN}
REVERT = {"fragment_role": "time_or_record", "entity_outside_trial": "yes"}


class _Stub:
    """Answers by which call a prompt is; ``barrier`` (if set) holds calls 1 and 3 until both
    have arrived."""

    def __init__(self, row: dict[str, Any], answers: dict[int, Any], barrier=None) -> None:
        self.answers = answers
        self.barrier = barrier
        self.prompts = {
            annotation.render_prompt(row, [], "inclusion", template): number
            for number, template in {
                1: annotation.ANNOTATION_PROMPT,
                2: annotation.AGREEMENT_PROMPT,
                3: annotation.RECORD_CHANGE_PROMPT,
                4: annotation.RECORD_CHANGE_AGREEMENT_PROMPT,
            }.items()
        }

    def invoke(self, messages: list[Any]) -> AIMessage:
        system, user = (str(m.content) for m in messages)
        number = self.prompts.get(user)
        if number is None:  # calls 5 and 6 carry the fragment
            number = 5 if system == annotation.ANNOTATION_SYSTEM_PROMPT else 6
        if self.barrier is not None and number in (1, 3):
            self.barrier.wait()  # BrokenBarrierError when the other never arrives
        answer = self.answers[number]
        if isinstance(answer, Exception):
            raise answer
        return AIMessage(content=json.dumps(answer))


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


def _run(answers, *, pool=None, barrier=None) -> tuple[str, dict[str, Any]]:
    row = deepcopy(ROW)
    llm = _Stub(row, answers, barrier)
    outcome = annotation.annotate_row(
        row, [], "inclusion", model="stub", llm=llm, branch_pool=pool
    )
    return outcome, row


def _cache_keys() -> list[str]:
    path = annotation.cache_path()
    return sorted(json.loads(l)["key"] for l in path.read_text().splitlines()) if path.exists() else []


def test_should_have_calls_one_and_three_in_flight_together_when_given_a_branch_pool():
    barrier = threading.Barrier(2, timeout=5)
    with ThreadPoolExecutor(1) as pool:
        outcome, row = _run({1: CONDITIONAL, 2: CONDITIONAL, 3: STABLE, 4: STABLE,
                             5: REVERT, 6: REVERT}, pool=pool, barrier=barrier)
    assert not barrier.broken
    assert outcome == "called"
    assert "error" not in row[annotation.RECORD_CHANGE_KEY]
    assert row[annotation.ANNOTATION_KEY]["record_change"] == "stable"


SCENARIOS = {
    "all six calls": {1: CONDITIONAL, 2: CONDITIONAL, 3: STABLE, 4: STABLE, 5: REVERT, 6: REVERT},
    "call 1 fails": {1: RuntimeError("down"), 3: STABLE, 4: STABLE},
    "call 3 fails": {1: CONDITIONAL, 2: CONDITIONAL, 3: RuntimeError("down"), 5: REVERT,
                     6: {"fragment_role": "patients", "entity_outside_trial": "no"}},
    "agreement drops": {1: CONDITIONAL, 2: {"record_requirement": "required"},
                        3: STABLE, 4: {"record_change": "none"}},
}


@pytest.mark.parametrize("answers", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_should_merge_like_the_sequential_run_when_the_branches_overlap(answers, tmp_path,
                                                                       monkeypatch):
    sequential = _run(answers)
    sequential_keys = _cache_keys()
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "overlap.jsonl"))
    annotation.reset_for_tests()
    with ThreadPoolExecutor(1) as pool:
        overlapped = _run(answers, pool=pool)
    assert overlapped[0] == sequential[0]
    # same keys, same values, same insertion order
    assert json.dumps(overlapped[1]) == json.dumps(sequential[1])
    assert _cache_keys() == sequential_keys


def test_should_overlap_in_annotate_eligibility_only_when_the_env_allows(monkeypatch):
    seen: list[bool] = []
    real = annotation.annotate_row

    def spy(*args, branch_pool=None, **kwargs):
        seen.append(branch_pool is not None)
        return "no-line"

    monkeypatch.setattr(annotation, "annotate_row", spy)
    monkeypatch.setattr(annotation, "_build_llm", lambda model: None)
    eligibility = {"inclusionCriteria": [deepcopy(ROW)], "exclusionCriteria": []}
    monkeypatch.setenv("ARTEMIS_ANNOTATION_OVERLAP", "0")
    annotation.annotate_eligibility(deepcopy(eligibility), model="stub")
    monkeypatch.delenv("ARTEMIS_ANNOTATION_OVERLAP")
    annotation.annotate_eligibility(deepcopy(eligibility), model="stub")
    assert seen == [False, True]
    assert real is not spy
