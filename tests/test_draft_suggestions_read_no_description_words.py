"""The draft's suggestions come from the drafted study, never from words in its description.

``TTEService._build_suggestions`` used to test the free-text study description for the
phrase "new user" and, when it was present, dropped the suggestion that names the
follow-up and washout the draft defaulted. The draft's ``timeParams`` are the same
defaults either way (``followUpDuration`` 30, ``washoutPeriod`` 180), so the phrase only
hid a true statement about the payload (AGENTS.md § PROMPTS AND TEXT RULES, rule 2).

The payloads are the six candidate studies of ``tests/fixtures/p5_candidate_rows.json``
(a verbatim extract of ``output/site_gap/2026-10-12_prompt_f2/store/studies.json``), with
their stored ``description`` and ``naturalLanguageDescription``. None of those says "new
user", so each is also asked with that phrase appended: the suggestions must not move.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.services.tte_service import TTEService

FIXTURE = Path(__file__).parent / "fixtures" / "p5_candidate_rows.json"
STUDIES: dict[int, dict[str, Any]] = {
    s["id"]: s for s in json.loads(FIXTURE.read_text(encoding="utf-8"))["studies"]
}
DEFAULTS_TEXT = "Defaulted follow-up to 30 days and washout to 180 days."


def _descriptions(study: dict[str, Any]) -> list[str]:
    stored = [study.get("description"), study.get("naturalLanguageDescription")]
    return [text for text in stored if text]


def _suggestions(description: str, study: dict[str, Any]) -> list[dict[str, Any]]:
    service = TTEService.__new__(TTEService)
    return [s.model_dump() for s in service._build_suggestions(description, study, "trial_agent")]


@pytest.mark.parametrize("study_id", sorted(STUDIES))
def test_should_give_the_same_suggestions_when_the_description_says_new_user(study_id: int) -> None:
    study = STUDIES[study_id]
    for description in _descriptions(study):
        assert _suggestions(f"{description} (new user design)", study) == _suggestions(description, study)


@pytest.mark.parametrize("study_id", sorted(STUDIES))
def test_should_name_the_defaulted_time_params_on_every_candidate_draft(study_id: int) -> None:
    study = STUDIES[study_id]
    for description in _descriptions(study):
        texts = [s["text"] for s in _suggestions(f"{description} new user", study)]
        assert DEFAULTS_TEXT in texts
