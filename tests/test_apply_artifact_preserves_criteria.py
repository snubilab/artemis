"""Applying a failed generation must not empty a populated eligibility section.

`run_generate_from_nct` catches any exception from the trial agent and falls back to
`_heuristic_draft`, a placeholder study whose target is literally "Target population
to be specified". It records the reason in `fallbackReason` and leaves
`generationMode` at "heuristic" -- and then still returns `status="completed"`.

`_merge_eligibility_section` is named for a merge it does not perform: it deep-copies
the proposed section wholesale and carries over only `structuredExpression`. So
applying that placeholder replaces the criteria list rather than merging into it.

Measured on 2026-07-31 re-ingesting ARISTOTLE from its protocol PDF: the PDF stage
worked (0 -> 29 exclusion criteria), Agent 1's IR JSON was truncated by a 16384
context, the capability reported "completed", and applying the artifact took the
study from 31 criteria to 0. It ran against an isolated store copy, so nothing real
was lost -- this test is what makes that safety not depend on remembering to isolate.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.tte_service import TTEService
from src.services.tte_store import TTEStore

POPULATED = {
    "targetCohortName": "Patients with atrial fibrillation",
    "inclusionCriteria": [
        {"id": 1, "description": "Atrial fibrillation"},
        {"id": 2, "description": "Age >= 18"},
    ],
    "exclusionCriteria": [
        {"id": 3, "description": "ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN"},
    ],
}

# What _heuristic_draft produces when generation fails.
PLACEHOLDER = {
    "targetCohortName": "Target population to be specified",
    "inclusionCriteria": [],
    "exclusionCriteria": [],
}


@pytest.fixture
def service(tmp_path: Path) -> TTEService:
    store_path = tmp_path / "studies.json"
    store_path.write_text(
        json.dumps({"next_id": 1, "next_artifact_id": 1, "next_job_id": 1,
                    "studies": [], "artifacts": [], "jobs": []})
    )
    return TTEService(TTEStore(str(store_path)))


def _study_with(service: TTEService, eligibility: dict) -> dict:
    return service.store.create_study(
        {"name": "ARISTOTLE", "description": "apixaban vs warfarin", "eligibility": eligibility}
    )


def _draft_artifact(service: TTEService, study: dict, proposed_eligibility: dict,
                    *, fallback: str | None = None) -> dict:
    return service.store.create_artifact(
        {
            "studyId": study["id"],
            "studyVersion": int(study.get("version") or 1),
            "kind": "draft_generation",
            "status": "completed",
            "source": "artemis",
            "capability": "generate_from_nct",
            "summary": "draft",
            "payload": {
                "proposedChanges": {"eligibility": proposed_eligibility},
                "rationale": [],
                "suggestions": [],
                "meta": {
                    "generationMode": "heuristic" if fallback else "trial_agent",
                    "fallbackReason": fallback,
                },
            },
        }
    )


def test_placeholder_draft_does_not_empty_populated_criteria(service: TTEService) -> None:
    """The exact shape that took ARISTOTLE from 31 criteria to 0."""
    study = _study_with(service, POPULATED)
    artifact = _draft_artifact(
        service, study, PLACEHOLDER,
        fallback="Failed to parse LLM response as JSON: Expecting property name ...",
    )

    with pytest.raises(ValueError, match="(?i)empt|fallback|placeholder"):
        service.apply_artifact(artifact["id"], ["eligibility"], int(study["version"]))

    after = service.store.get_study(study["id"])["eligibility"]
    assert len(after["inclusionCriteria"]) == 2
    assert len(after["exclusionCriteria"]) == 1


def test_a_real_draft_still_applies(service: TTEService) -> None:
    """The guard must not block the case the capability exists for."""
    study = _study_with(service, POPULATED)
    richer = {
        "targetCohortName": "Patients with atrial fibrillation",
        "inclusionCriteria": [{"id": i, "description": f"incl {i}"} for i in range(1, 24)],
        "exclusionCriteria": [{"id": i, "description": f"excl {i}"} for i in range(1, 30)],
    }
    artifact = _draft_artifact(service, study, richer)

    service.apply_artifact(artifact["id"], ["eligibility"], int(study["version"]))

    after = service.store.get_study(study["id"])["eligibility"]
    assert len(after["inclusionCriteria"]) == 23
    assert len(after["exclusionCriteria"]) == 29


def test_first_population_of_an_empty_study_still_applies(service: TTEService) -> None:
    """Nothing to protect when the study has no criteria yet."""
    study = _study_with(service, {"targetCohortName": "new", "inclusionCriteria": [],
                                  "exclusionCriteria": []})
    artifact = _draft_artifact(
        service, study,
        {"targetCohortName": "new", "inclusionCriteria": [{"id": 1, "description": "x"}],
         "exclusionCriteria": []},
    )

    service.apply_artifact(artifact["id"], ["eligibility"], int(study["version"]))

    assert len(service.store.get_study(study["id"])["eligibility"]["inclusionCriteria"]) == 1
