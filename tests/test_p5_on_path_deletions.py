"""P5 / RFC-016 §5: five on-path text rules deleted with no replacement, judged on real rows.

Every row here comes from ``tests/fixtures/p5_candidate_rows.json``, a verbatim extract of
the candidate store ``output/site_gap/2026-10-12_prompt_f2/store/studies.json`` (studies
1, 2, 3, 8, 9, 10). Where deleting a rule changes what that candidate produces, the test
names the rows and was seen failing on the code that still carried the rule. Where it
changes nothing, the test pins the unchanged output on every candidate row.

* A3  ``LogicDecomposer._normalize_drug_entity_text`` -- stripped parentheticals and a
  trailing "or other <word>" from a Drug ``entity_text``.
* A13 ``query_expander._CURATED_EXPANSIONS`` -- rewrote the retrieval query for eGFR,
  NSTEMI, TIA and Stroke.
* A15 ``nlu_router.TEMPORAL_KEYWORDS`` -- refused a RAG-fallback seed containing a window
  word before the intent separator saw it.
* A23 ``TTEService._extract_eligibility_concept_ids_for_outcome`` -- split the outcome
  label on or/and/,/; and handed the outcome mapper the concepts of every criterion
  whose description contained a piece.
* A24 ``TTEService._parse_description`` -- read "X vs Y for Z in W" out of a study
  description.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent1 import parser
from src.agents.agent2.query_expander import QueryExpander
from src.agents.conceptset.nlu_router import IntentResult, NLURouter
from src.services.tte_service import TTEService

FIXTURE = Path(__file__).parent / "fixtures" / "p5_candidate_rows.json"
STUDIES: dict[int, dict[str, Any]] = {
    s["id"]: s for s in json.loads(FIXTURE.read_text(encoding="utf-8"))["studies"]
}


def _row(study_id: int, role: str, criterion_id: int) -> dict[str, Any]:
    for row in STUDIES[study_id]["eligibility"][f"{role}Criteria"]:
        if row["id"] == criterion_id:
            return row
    raise KeyError((study_id, role, criterion_id))


def _rows() -> list[tuple[int, str, dict[str, Any]]]:
    return [
        (sid, role, row)
        for sid, study in STUDIES.items()
        for role in ("inclusion", "exclusion")
        for row in study["eligibility"][f"{role}Criteria"]
    ]


def test_should_read_the_six_candidate_studies_when_the_fixture_loads() -> None:
    assert sorted(STUDIES) == [1, 2, 3, 8, 9, 10]
    assert len(_rows()) == 431


# --------------------------------------------------------------------------- #
# A3 -- Drug entity_text reaches the mapper as the model wrote it
# --------------------------------------------------------------------------- #


def _decomposer() -> parser.LogicDecomposer:
    return parser.LogicDecomposer.__new__(parser.LogicDecomposer)


def test_should_keep_a_drug_entity_verbatim_when_it_carries_a_parenthetical() -> None:
    """LEADER inclusion #12's protocol line names the drug class with its abbreviation."""
    line = _row(1, "inclusion", 12)["protocolLine"]
    entity = "oral anti-diabetic drugs (OADs)"
    assert entity in line

    built = _decomposer()._build_criteria(
        {"name": "Treated with OADs", "domain": "Drug", "entity_text": entity, "source_text": line}
    )

    assert built.entity_text == entity


def test_should_leave_every_candidate_drug_seed_unchanged_when_the_normaliser_is_gone() -> None:
    """No change on the candidate: none of its 66 Drug rows carried what A3 stripped.

    Measured on the raw model output too: 0 of the 978 Drug ``entity_text`` values across
    the 136 cached IR files in ``data/cache/agent1_ir/`` contain a parenthesis or
    "or other".
    """
    drug_rows = [row for _, _, row in _rows() if row["domain"] == "Drug"]
    assert len(drug_rows) == 66
    for row in drug_rows:
        if not row["sourceText"]:
            continue
        built = _decomposer()._build_criteria(
            {"name": row["description"], "domain": "Drug", "entity_text": row["sourceText"]}
        )
        assert built.entity_text == row["sourceText"]


# --------------------------------------------------------------------------- #
# A13 -- the retrieval query is the seed itself
# --------------------------------------------------------------------------- #

A13_ROWS = [
    (1, "inclusion", 11), (2, "inclusion", 25), (8, "inclusion", 10), (8, "exclusion", 51),
    (9, "exclusion", 39), (9, "exclusion", 42), (9, "exclusion", 43), (10, "inclusion", 25),
    (10, "inclusion", 27), (10, "exclusion", 72), (10, "exclusion", 75), (10, "exclusion", 76),
]


@pytest.mark.parametrize("study_id,role,criterion_id", A13_ROWS)
def test_should_query_the_retriever_with_the_seed_when_it_was_on_the_curated_list(
    monkeypatch: pytest.MonkeyPatch, study_id: int, role: str, criterion_id: int
) -> None:
    """The twelve mapped rows behind the candidate's 24 ``[QueryExpander] Expanded`` lines."""
    monkeypatch.delenv("AGENT2_QUERY_EXPAND", raising=False)
    row = _row(study_id, role, criterion_id)
    assert row["sourceText"] in {"eGFR", "NSTEMI", "TIA", "Stroke"}

    assert QueryExpander(umls_expander=None).expand(row["sourceText"], row["domain"]) == (
        row["sourceText"]
    )


# --------------------------------------------------------------------------- #
# A15 -- a window word no longer refuses a seed before the intent separator
# --------------------------------------------------------------------------- #


class _RecordingSeparator:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def separate(self, query: str) -> IntentResult:
        self.queries.append(query)
        return IntentResult(include=[query], exclude=[])


@pytest.mark.parametrize("criterion_id", [35, 44])
def test_should_hand_a_seed_with_a_window_word_to_the_intent_separator(criterion_id: int) -> None:
    """CARMELINA exclusion #35 and #44: the candidate refused both on the RAG fallback.

    Both arms of the delivered CARMELINA file record them as ``missing-entity-text``
    with the chained cause "Temporal logic detected in: ..." -- the A15 refusal, masked
    by the outer code, which is why the inventory counted 0 ``intent-unparsed``.
    """
    seed = _row(9, "exclusion", criterion_id)["description"]
    router = NLURouter.__new__(NLURouter)
    router.intent_separator = _RecordingSeparator()

    result = router.route(seed)

    assert router.intent_separator.queries == [seed]
    assert result.fallback_to is None


# --------------------------------------------------------------------------- #
# A23 -- an outcome cohort is mapped from its own label only
# --------------------------------------------------------------------------- #


class _Stop(Exception):
    """Raised once the outcome expression has been built: nothing after it is under test."""


@pytest.mark.parametrize("study_id", [1, 2, 3, 8, 9, 10])
def test_should_build_the_primary_outcome_without_eligibility_concepts(study_id: int) -> None:
    """PLATO and ARISTOTLE changed: their outcome labels share "stroke" with criteria.

    On the candidate the prefetch handed PLATO's outcome mapper 32 concepts (from
    "Previous ischemic stroke") and ARISTOTLE's 35 (from four stroke criteria); the other
    four studies got none. Outcome cohorts are not in the delivered per-arm files.
    """
    study = copy.deepcopy(STUDIES[study_id])
    service = TTEService.__new__(TTEService)
    service.store = MagicMock()
    service.store.list_artifacts.return_value = [{"id": "elig", "kind": "eligibility_processing"}]
    service.store.get_artifact.return_value = {
        "payload": {"criterionMappingMetadata": study["criterionMappingMetadata"]}
    }
    handed: list[Any] = []

    def condition_circe(label: str, **kwargs: Any) -> dict[str, Any]:
        handed.append(kwargs.get("pre_fetched_candidates"))
        return {}

    def cohort_item(**kwargs: Any) -> Any:
        kwargs["expression_builder"]()
        raise _Stop

    with patch("src.services.tte_service.WebAPIClient"), \
            patch.object(TTEService, "_materialize_seeded_target_cohort", return_value=MagicMock()), \
            patch.object(TTEService, "_materialize_seeded_treatment_cohorts", return_value=MagicMock()), \
            patch.object(TTEService, "_build_seeded_condition_circe", side_effect=condition_circe), \
            patch.object(TTEService, "_materialize_seeded_cohort_item", side_effect=cohort_item):
        with pytest.raises(_Stop):
            service._build_seeded_cohort_artifact_payload(study_id, study)

    assert handed == [None]


# --------------------------------------------------------------------------- #
# A24 -- nothing is read out of a study description
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("study_id", [1, 2, 3, 8, 9, 10])
def test_should_take_every_provisional_section_from_the_study_when_it_is_populated(
    study_id: int,
) -> None:
    """No change on the candidate: each description is "Imported from NCT...", and every
    section the parse could have filled was already populated from the study itself."""
    study = copy.deepcopy(STUDIES[study_id])
    service = TTEService.__new__(TTEService)

    ir = service._study_to_provisional_ir(study)

    arms = study["treatmentArms"]
    assert (ir.eligibility.source, ir.treatment.source, ir.outcomes.source) == (
        "structured_section", "structured_section", "structured_section",
    )
    assert ir.comparator_text == arms[1]["name"]
    assert ir.primary_outcome_text == study["outcomes"]["primary"]["cohortName"]
    assert [a["name"] for a in service._build_treatment_suggestion(study, ir)] == [
        a["name"] for a in arms
    ]
    assert service._build_outcomes_suggestion(study, ir)["primary"]["cohortName"] == (
        study["outcomes"]["primary"]["cohortName"]
    )
    suggestion = service._build_eligibility_suggestion(study, ir)
    assert suggestion["inclusionCriteria"] == study["eligibility"]["inclusionCriteria"]


class _AgentDown(RuntimeError):
    pass


@pytest.mark.parametrize("study_id", [1, 2, 3])
def test_should_surface_the_agent_failure_when_drafting_from_a_description(study_id: int) -> None:
    """The studies' own natural-language descriptions ("PLATO trial: ticagrelor vs
    clopidogrel for cardiovascular outcomes in ACS"). With the trial agent down these
    used to come back as a draft parsed out of the sentence."""
    description = STUDIES[study_id]["naturalLanguageDescription"]
    service = TTEService.__new__(TTEService)

    with patch.object(TTEService, "_generate_with_trial_agent", side_effect=_AgentDown("down")):
        with pytest.raises(_AgentDown):
            service.generate_draft(description)


def test_should_fail_the_job_when_the_agent_cannot_draft_a_study(tmp_path: Path) -> None:
    from src.services.tte_store import TTEStore

    store_path = tmp_path / "studies.json"
    store_path.write_text(json.dumps({
        "next_id": 1, "next_artifact_id": 1, "next_job_id": 1,
        "studies": [], "artifacts": [], "jobs": [],
    }))
    service = TTEService(TTEStore(str(store_path)))
    study = service.store.create_study({"name": "LEADER", "description": ""})

    with patch.object(TTEService, "_generate_with_trial_agent", side_effect=_AgentDown("down")):
        with pytest.raises(_AgentDown):
            service.run_generate_draft(study["id"], STUDIES[1]["naturalLanguageDescription"])

    jobs = service.store.list_jobs(study_id=study["id"])
    assert [job["status"] for job in jobs] == ["failed"]
    assert "down" in jobs[0]["error"]
    assert service.store.list_artifacts(study_id=study["id"]) == []
