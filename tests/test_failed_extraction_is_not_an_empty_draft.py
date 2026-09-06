"""A failed extraction must surface as a failure, not as a study with no criteria.

`_generate_with_trial_agent_from_nct` caught every exception from the trial agent and
called `_heuristic_draft(f"Target trial emulation from {nct_id}")`. That string carries
no comparator, no outcome, and no population, so `_parse_description` recovers nothing
from it and the draft comes back with zero eligibility criteria, a target of "Target
population to be specified", and `status="completed"` on the job. A truncated LLM
response therefore arrived downstream as a finished proposal to empty a study.

`_reject_criteria_loss` catches that at apply time and must keep doing so -- but it is
the last line of defence, and it only fires because the study being overwritten was
already populated. A first extraction into an empty study has nothing to compare
against, so the shell would simply be applied.

The fallback itself is kept: `generate_draft` and `run_generate_draft` hand it a real
natural-language question ("compare X vs Y for Z in P"), and from that it does recover
a treatment, a comparator, an outcome, and a population. What it must not do is return
a study built entirely from defaults and call that a proposal.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.tte_service import TTEService
from src.services.tte_store import TTEStore
from src.utils.exceptions import LLMTruncationError

# The label the NCT path hands the heuristic. Nothing in it is a treatment.
NCT_LABEL = "Target trial emulation from NCT01243424"


@pytest.fixture
def service(tmp_path: Path) -> TTEService:
    store_path = tmp_path / "studies.json"
    store_path.write_text(
        json.dumps(
            {
                "next_id": 1,
                "next_artifact_id": 1,
                "next_job_id": 1,
                "studies": [],
                "artifacts": [],
                "jobs": [],
            }
        )
    )
    return TTEService(TTEStore(str(store_path)))


class _TruncatedAgent:
    """Agent 1 as it behaved on CAROLINA once the IR cache was turned off."""

    def parse_nct(self, nct_id: str):
        raise LLMTruncationError(
            "Agent 1 NCT extraction was cut off at the token ceiling "
            "(finish_reason='length').",
            prompt_tokens=10777,
            completion_tokens=5607,
        )


def test_should_refuse_a_heuristic_draft_when_the_description_yields_no_structure(
    service: TTEService,
) -> None:
    with pytest.raises(ValueError) as excinfo:
        service._heuristic_draft(NCT_LABEL)
    assert "NCT01243424" in str(excinfo.value)


def test_should_still_build_a_heuristic_draft_when_the_description_names_a_comparator(
    service: TTEService,
) -> None:
    """The legitimate call sites keep working: this is a refusal, not a removal."""
    draft = service._heuristic_draft(
        "Compare dapagliflozin vs DPP4 inhibitors for MACE in adults with T2DM"
    )
    assert draft["studyType"] == "comparative"
    assert [arm["name"] for arm in draft["treatmentArms"]] == [
        "dapagliflozin",
        "DPP4 inhibitors",
    ]
    assert draft["eligibility"]["inclusionCriteria"][0]["description"] == "adults with T2DM"


def test_should_surface_the_extraction_failure_when_nct_generation_fails(
    service: TTEService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect: a truncated extraction became a completed zero-criteria draft."""
    monkeypatch.setattr(
        "src.agents.agent1.parser.get_agent1", lambda **_: _TruncatedAgent()
    )
    with pytest.raises(LLMTruncationError):
        service._generate_with_trial_agent_from_nct("NCT01243424")


def test_should_keep_the_original_cause_when_nct_generation_fails(
    service: TTEService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The heuristic's own refusal must not displace the reason the run failed."""
    monkeypatch.setattr(
        "src.agents.agent1.parser.get_agent1", lambda **_: _TruncatedAgent()
    )
    with pytest.raises(LLMTruncationError) as excinfo:
        service._generate_with_trial_agent_from_nct("NCT01243424")
    assert "token ceiling" in str(excinfo.value)
    assert excinfo.value.completion_tokens == 5607


def test_should_mark_the_job_failed_when_nct_generation_raises(
    service: TTEService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raise must not leave the capability's job stuck reading 'running'."""
    monkeypatch.setattr(
        "src.agents.agent1.parser.get_agent1", lambda **_: _TruncatedAgent()
    )
    study = service.store.create_study({"name": "CAROLINA", "description": ""})

    with pytest.raises(LLMTruncationError):
        service.run_generate_from_nct(study["id"], "NCT01243424")

    jobs = service.store.list_jobs(study_id=study["id"])
    assert [job["status"] for job in jobs] == ["failed"]
    assert "token ceiling" in jobs[0]["error"]


def test_should_not_create_a_draft_artifact_when_nct_generation_raises(
    service: TTEService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing to apply means nothing on disk that reads like a proposal."""
    monkeypatch.setattr(
        "src.agents.agent1.parser.get_agent1", lambda **_: _TruncatedAgent()
    )
    study = service.store.create_study({"name": "CAROLINA", "description": ""})

    with pytest.raises(LLMTruncationError):
        service.run_generate_from_nct(study["id"], "NCT01243424")

    assert service.store.list_artifacts(study_id=study["id"]) == []
