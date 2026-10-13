"""A mapping failure travels from MappingResult to the store and stops the delivery gate.

A refused KG expansion (``kg_expansion_failure``, a failed KG or refiner lookup) and a
failed critic (``critic_failure``) each leave a criterion's concept set built from the
reranker's seeds alone. Until here both stopped at ``MappingResult``: ``map_single_entity``
copied the concept ids and dropped the reason, the criterion's mapping metadata had no
field for it, and nothing in the delivered file said that any of its concept sets was
the product of a failure -- so the gate passed a file in which some sets depend on
whether the database was congested on the day.

Nothing here contacts a database, a graph or a model: Agent 2 is replaced by the
``MappingResult`` it would have returned.
"""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agents.agent2.map_entity import map_single_entity
from src.api.models.tte import CriterionMappingMetadata
from src.models.ir import MappingResult
from src.services.tte_service import TTEService
from tests.test_delivery_gate_reads_drop_records import CLEAN_RECORDS, _study

#: Where the build writes the record and the gate reads it (``circe_lint``).
MAPPING_FAILURE_CRITERIA_KEY = "_mappingFailureCriteria"

KG_REASON = "RefinerLookupError: Refiner lookup failed (descendant count) for [20] in synthea_cdm"
CRITIC_REASON = "OutputParserException: Invalid json output: {\"selected_concepts\": [{\"conc"


def _failed(**kwargs) -> MappingResult:
    return MappingResult(concept_ids=[10], seed_concept_ids=[10], route_path="slow", **kwargs)


# ── EntityMappingResult ──────────────────────────────────────


def test_should_carry_every_recorded_failure_into_the_entity_mapping_result():
    agent2 = MagicMock()
    agent2.process_with_details.return_value = _failed(
        kg_expansion_failure=KG_REASON, critic_failure=CRITIC_REASON
    )

    emr = map_single_entity("History of stroke", domain_hint="Condition", agent2=agent2)

    expected = [
        {"stage": "kg_expansion", "reason": KG_REASON, "seedsOnly": True},
        {"stage": "critic", "reason": CRITIC_REASON, "seedsOnly": True},
    ]
    assert emr.mapping_failures == expected
    assert emr.to_meta_dict()["mapping_failures"] == expected
    mapped = emr.to_mapped_set(entity_id=1, entity_text="History of stroke", domain="Condition")
    assert mapped["mapping_failures"] == expected


def test_should_carry_an_empty_list_when_the_mapping_ran_clean():
    agent2 = MagicMock()
    agent2.process_with_details.return_value = _failed()

    emr = map_single_entity("History of stroke", domain_hint="Condition", agent2=agent2)

    assert emr.mapping_failures == []
    assert emr.to_meta_dict()["mapping_failures"] == []


# ── the criterion's mapping metadata ─────────────────────────


def test_should_record_the_failures_in_the_criterion_mapping_metadata():
    from tests.test_kg_specificity_lookup_failure import _recommend

    out, _cache = _recommend(_failed(critic_failure=CRITIC_REASON))

    assert out["mapping_metadata"].mappingFailures == [
        {"stage": "critic", "reason": CRITIC_REASON, "seedsOnly": True,
         "query": "History of Stroke"}
    ]


def test_should_record_no_failure_in_the_metadata_of_a_clean_mapping():
    from tests.test_kg_specificity_lookup_failure import _recommend

    out, cache = _recommend(_failed())

    assert out["mapping_metadata"].mappingFailures == []
    assert cache.stats()["current_size"] == 1


def test_should_keep_the_failure_of_an_excepted_phrase_on_the_repaired_mapping():
    """'insulin other than human NPH insulin' is mapped as two phrases. A failure on the
    excepted phrase changes what the subtraction removes, so it belongs to the criterion."""
    from src.services.entity_subtraction import EntityException

    def _mapping(phrase, ids, failures):
        return {
            "name": phrase,
            "domain": "Drug",
            "expression": {"items": [
                {"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"c{cid}"},
                 "isExcluded": False, "includeDescendants": True} for cid in ids]},
            "mapping_metadata": CriterionMappingMetadata(
                queryUsed=phrase, selectedConceptIds=ids, mappingFailures=failures
            ),
        }

    excepted_failure = {"stage": "critic", "reason": CRITIC_REASON, "seedsOnly": True,
                        "query": "human NPH insulin"}
    table = {
        "insulin": _mapping("insulin", [1, 2, 3], []),
        "human NPH insulin": _mapping("human NPH insulin", [1], [excepted_failure]),
    }

    class _Stubbed(TTEService):
        def _recommend_seeded_concept_set(self, seed_text, **kwargs):
            if kwargs.get("resolving_entity_exception"):
                return table[seed_text]
            return super()._recommend_seeded_concept_set(seed_text, **kwargs)

    result = _Stubbed(store=MagicMock())._recommend_seeded_concept_set(
        "insulin", expected_domain="Drug",
        entity_exception=EntityException(
            text="insulin other than human NPH insulin", base="insulin",
            excepted=["human NPH insulin"]),
    )

    assert result["mapping_metadata"].mappingFailures == [excepted_failure]


# ── the build writes the record the delivered file carries ───


def test_should_name_the_record_key_in_one_place():
    from src.utils import circe_lint

    assert circe_lint.MAPPING_FAILURE_CRITERIA_KEY == MAPPING_FAILURE_CRITERIA_KEY


def _concept_set(seed: str, failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": seed,
        "domain": "Condition",
        "expression": {"items": [{
            "concept": {"CONCEPT_ID": 4310996, "CONCEPT_NAME": seed, "CONCEPT_CODE": "x",
                        "DOMAIN_ID": "Condition", "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding"},
            "includeDescendants": True, "isExcluded": False,
        }]},
        "mapping_metadata": CriterionMappingMetadata(
            queryUsed=seed, selectedConceptIds=[4310996], mappingFailures=failures
        ),
    }


@pytest.fixture
def build(monkeypatch):
    """`_build_seeded_target_circe` with the mapper replaced: `failing` seeds carry a failure."""

    def _run(failing: dict[str, list[dict[str, Any]]], criteria: list[dict[str, Any]]):
        svc = TTEService.__new__(TTEService)
        monkeypatch.setattr(
            svc, "_recommend_seeded_concept_set",
            lambda seed, **_k: _concept_set(seed.strip(), failing.get(seed.strip(), [])),
        )
        return svc._build_seeded_target_circe({
            "targetCohortName": "empagliflozin",
            "inclusionCriteria": criteria,
            "exclusionCriteria": [],
        })

    return _run


def _criterion(cid: str, entity: str) -> dict[str, Any]:
    return {"id": cid, "description": entity, "sourceText": entity, "domain": "Condition",
            "window": {"start": -365, "end": 0}, "logicType": "PRESENCE", "isGroupLabel": False}


def test_should_write_a_record_row_for_a_criterion_mapped_with_a_failure(build):
    failure = {"stage": "kg_expansion", "reason": KG_REASON, "seedsOnly": True, "query": "stroke"}

    circe = build({"stroke": [failure]}, [_criterion("1", "stroke"), _criterion("2", "angina")])

    assert circe[MAPPING_FAILURE_CRITERIA_KEY] == [{
        "criterionId": "1", "role": "inclusion", "label": "stroke", "failures": [failure],
    }]


def test_should_write_a_record_row_for_the_target_when_its_mapping_failed(build):
    failure = {"stage": "critic", "reason": CRITIC_REASON, "seedsOnly": True,
               "query": "empagliflozin"}

    circe = build({"empagliflozin": [failure]}, [_criterion("2", "angina")])

    assert circe[MAPPING_FAILURE_CRITERIA_KEY] == [{
        "criterionId": "_target", "role": "target", "label": "empagliflozin",
        "failures": [failure],
    }]


def test_should_carry_the_key_present_and_empty_when_every_mapping_ran_clean(build):
    """Present and empty is the claim that nothing failed; an absent key cannot make it."""
    circe = build({}, [_criterion("2", "angina")])

    assert circe[MAPPING_FAILURE_CRITERIA_KEY] == []


# ── the delivery gate ────────────────────────────────────────


@pytest.fixture
def gate(monkeypatch, tmp_path, capsys):
    """Run the delivery gate over both ARISTOTLE arms carrying `records`."""

    def _run(records: dict[str, Any]) -> tuple[int, str]:
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study()
        core = study["eligibility"]["structuredExpression"]
        for role in ("treatment", "comparator"):
            payload = json.loads(json.dumps(core))
            payload.update(json.loads(json.dumps(records)))
            (tmp_path / f"aristotle_{role}.circe.json").write_text(json.dumps(payload))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "aristotle=3"])
        return rc, capsys.readouterr().out

    return _run


def _with_failures(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    payload = json.loads(json.dumps(CLEAN_RECORDS))
    if rows is not None:
        payload[MAPPING_FAILURE_CRITERIA_KEY] = rows
    return payload


FAILED_ROW = {
    "criterionId": "12", "role": "exclusion", "label": "Prosthetic mechanical heart valve",
    "failures": [{"stage": "kg_expansion", "reason": KG_REASON, "seedsOnly": True,
                  "query": "prosthetic mechanical heart valve"}],
}


def test_should_fail_a_file_carrying_a_criterion_mapped_with_a_recorded_failure(gate):
    rc, out = gate(_with_failures([FAILED_ROW]))

    assert rc == 1, out
    assert "mapped with a recorded failure (1)" in out
    assert "exclusion #12 'Prosthetic mechanical heart valve'" in out
    assert "kg_expansion" in out and "Refiner lookup failed" in out


def test_should_pass_and_say_zero_when_the_record_is_present_and_empty(gate):
    rc, out = gate(_with_failures([]))

    assert rc == 0, out
    assert "0 mappings carry a recorded failure" in out


def test_should_pass_without_a_claim_when_the_artifact_predates_the_record(gate):
    """Every file delivered so far is one of these: no record, so no claim either way."""
    rc, out = gate(_with_failures(None))

    assert rc == 0, out
    assert "recorded failure" not in out


def test_should_fail_a_record_row_that_names_no_failure(gate):
    """A row is written only for a failure, so one naming none is a broken record."""
    rc, out = gate(_with_failures([{**FAILED_ROW, "failures": []}]))

    assert rc == 1, out
    assert "mapped with a recorded failure (1)" in out
