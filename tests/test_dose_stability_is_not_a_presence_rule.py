"""A stable-background-medication criterion is not emitted as a drug-presence rule.

CARMELINA inclusion 7 reads "Stable antidiabetic background medication (unchanged daily
dose) for at least 8 weeks prior to randomization". It conditions whatever therapy a
patient is on; it does not require one, and the same protocol admits drug-naive
patients (inclusion 2-6). CAROLINA says the same in inclusion 37/38 and 41, and admits
treatment-naive patients in inclusion 5-8. All three were delivered as `DrugExposure`
at-least-1 rules over -56..0, which reads "must be on an antidiabetic drug": Ajou's
CARMELINA comparator fell 38,664 -> 1,257 at that one rule in the 2026-09-23 send.
Neither TROY v1.1 gold carries any background-medication rule.

OMOP CDM records exposures, not a dose held constant, so "unchanged dose" has no
expression. The criterion is recorded under `DOSE_STABILITY_REASON` instead of emitted.

The mapper is stubbed throughout, and Agent 2's workflow, query expander and retriever
raise on construction, so nothing here reaches a model, ChromaDB or the vocabulary.
"""
from __future__ import annotations

import json
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import src.services.tte_service as tte_service_module
from src.services.dose_stability import (
    DOSE_STABILITY_EXPLANATION,
    DOSE_STABILITY_REASON,
    dose_stability_criterion_ids,
)
from src.services.tte_service import TTEService
from src.utils.circe_lint import CRITERION_CONCEPT_SET_REFS_KEY

#: The store the 2026-09-23 delivery was built from. Read only.
STORE = (
    Path(__file__).resolve().parents[1]
    / "output/site_gap/2026-09-22_verify5/store/studies.json"
)

CAROLINA_GROUP = "dd6fa83b-9e7b-4e93-bf43-a0deef399326"


def _row(
    criterion_id: int,
    description: str,
    source_text: str = "",
    *,
    domain: str = "Drug",
    group_id: str | None = None,
    is_group_label: bool = False,
    logic_type: str = "PRESENCE",
) -> dict[str, Any]:
    """One store criterion row, in the fields the build and the predicate read."""
    return {
        "id": criterion_id,
        "description": description,
        "sourceText": source_text,
        "domain": domain,
        "valueConstraint": None,
        "window": {"start": -56, "end": 0},
        "logicType": logic_type,
        "groupId": group_id,
        "groupType": "ANY" if group_id else "ALL",
        "parentGroupId": None,
        "isGroupLabel": is_group_label,
    }


# The four rows, with the text the store carries for them.
CARMELINA_7 = _row(7, "Stable antidiabetic background medication for 8 weeks")
CAROLINA_37 = _row(
    37,
    "Stable anti-diabetic background medication",
    "Anti-diabetic medication",
    group_id=CAROLINA_GROUP,
    is_group_label=True,
)
CAROLINA_38 = _row(
    38, "Anti-diabetic medication", "Anti-diabetic medication", group_id=CAROLINA_GROUP
)
CAROLINA_41 = _row(41, "Stable anti-diabetic background for 8 weeks", "Anti-diabetic medication")


class TestThePredicate:
    def test_should_select_a_drug_row_when_it_states_stable_background_medication(self):
        assert dose_stability_criterion_ids([CARMELINA_7]) == {"7"}

    def test_should_select_a_drug_row_when_stability_is_in_the_description_only(self):
        """CAROLINA 41's sourceText is the bare entity; the stability is in the description."""
        assert dose_stability_criterion_ids([CAROLINA_41]) == {"41"}

    def test_should_not_select_a_drug_row_when_it_states_no_stability(self):
        assert dose_stability_criterion_ids([_row(5, "Anti-diabetic medication")]) == set()

    @pytest.mark.parametrize(
        "text",
        [
            "Stable angina",
            "Stable coronary artery disease",
            # Every term but the domain: only the Drug gate keeps this out.
            "Stable coronary artery disease on optimal medical therapy",
        ],
    )
    def test_should_not_select_a_condition_when_stable_describes_the_disease(self, text):
        assert dose_stability_criterion_ids([_row(1, text, text, domain="Condition")]) == set()

    def test_should_not_select_a_drug_row_when_stable_names_the_disease_it_treats(self):
        """Drug domain and a stability word, but no therapy/medication/dose term: the
        drug presence is the criterion here, and "stable" belongs to the angina."""
        row = _row(3, "Nitrates for stable angina", "Nitrates")
        assert dose_stability_criterion_ids([row]) == set()

    def test_should_carry_its_members_when_a_group_label_states_dose_stability(self):
        assert dose_stability_criterion_ids([CAROLINA_37, CAROLINA_38]) == {"37", "38"}

    def test_should_not_select_a_group_label_when_a_member_is_not_a_drug(self):
        """Dropping the group would drop a non-drug criterion under a reason about drugs."""
        hba1c = _row(39, "HbA1c", "HbA1c", domain="Measurement", group_id=CAROLINA_GROUP)
        assert dose_stability_criterion_ids([CAROLINA_37, CAROLINA_38, hba1c]) == set()

    def test_should_not_select_a_group_label_when_it_has_no_members(self):
        """Nothing shows the label's text describes drug therapy at all."""
        assert dose_stability_criterion_ids([CAROLINA_37]) == set()


@pytest.fixture(scope="module")
def store_studies() -> dict[int, dict[str, Any]]:
    if not STORE.exists():
        pytest.skip(f"real store not present: {STORE}")
    payload = json.loads(STORE.read_text())
    studies = payload["studies"] if isinstance(payload, dict) else payload
    return {study["id"]: study for study in studies}


class TestTheRealStore:
    def test_should_select_exactly_the_carmelina_and_carolina_rows_when_run_over_the_real_store(
        self, store_studies
    ):
        selected = {
            (study_id, role, criterion_id)
            for study_id, study in store_studies.items()
            for role, key in (
                ("inclusion", "inclusionCriteria"),
                ("exclusion", "exclusionCriteria"),
            )
            for criterion_id in dose_stability_criterion_ids(
                (study.get("eligibility") or {}).get(key) or []
            )
        }
        assert selected == {
            (9, "inclusion", "7"),
            (10, "inclusion", "37"),
            (10, "inclusion", "38"),
            (10, "inclusion", "41"),
        }


def _stub_concept_set(seed: str, domain: str) -> dict[str, Any]:
    """A distinct one-concept set per seed, in the domain the criterion asked for."""
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


@pytest.fixture
def service(monkeypatch) -> TTEService:
    # The build constructs these inside try/except and degrades to per-criterion
    # mapping, which the stub below answers.
    monkeypatch.setattr("src.agents.agent2.workflow.Agent2Workflow", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.query_expander.QueryExpander", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.retriever.ConceptRetriever", _Agent2IsStubbed)
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        domain = kwargs.get("expected_domain") or "Condition"
        if seed_text.strip() in {"linagliptin", "empagliflozin"}:
            domain = "Drug"
        return _stub_concept_set(seed_text.strip(), domain)

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    return svc


def _eligibility(
    inclusion: list[dict[str, Any]] | None = None,
    exclusion: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "targetCohortName": "linagliptin",
        "inclusionCriteria": deepcopy(inclusion or []),
        "exclusionCriteria": deepcopy(exclusion or []),
    }


def _reasons(circe: dict[str, Any]) -> set[tuple[str, str]]:
    return {(r["criterionId"], r["reason"]) for r in circe["_skippedCriteria"]}


class TestTheBuildStep:
    def test_should_record_dose_stability_when_an_inclusion_states_stable_background_medication(
        self, service
    ):
        circe = service._build_seeded_target_circe(_eligibility(inclusion=[CARMELINA_7]))
        assert circe["InclusionRules"] == []
        assert _reasons(circe) == {("7", DOSE_STABILITY_REASON)}
        assert circe["_skippedCriteria"][0]["explanation"] == DOSE_STABILITY_EXPLANATION

    def test_should_skip_the_member_with_its_group_label_when_the_label_states_dose_stability(
        self, service
    ):
        circe = service._build_seeded_target_circe(
            _eligibility(inclusion=[CAROLINA_37, CAROLINA_38])
        )
        assert circe["InclusionRules"] == []
        assert _reasons(circe) == {("37", DOSE_STABILITY_REASON), ("38", DOSE_STABILITY_REASON)}
        census = circe["_generationCensus"]
        assert (census["total"], census["mappable"], census["skipped"]) == (2, 0, 2)

    def test_should_still_emit_an_exclusion_when_its_text_reads_stable(self, service):
        """Inclusion only. An exclusion is never a presence requirement, and the
        forbidden-drug exclusions stay exactly as they are."""
        row = _row(30, "Stable dose of insulin", "Insulin")
        circe = service._build_seeded_target_circe(_eligibility(exclusion=[row]))
        assert len(circe["InclusionRules"]) == 1
        assert circe["_skippedCriteria"] == []


def _codesets_in(node: Any) -> set[int]:
    if isinstance(node, dict):
        found = {node["CodesetId"]} if "CodesetId" in node else set()
        for value in node.values():
            found |= _codesets_in(value)
        return found
    if isinstance(node, list):
        return set().union(*(_codesets_in(item) for item in node)) if node else set()
    return set()


def _canonical(node: Any, names: dict[int, str]) -> Any:
    """`node` with every CodesetId replaced by its concept set's content.

    Removing a criterion before the mapper shifts every later codeset id by one, so
    rules are compared by what they select rather than by the number they cite.
    """
    if isinstance(node, dict):
        return {
            key: names[value] if key == "CodesetId" else _canonical(value, names)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_canonical(item, names) for item in node]
    return node


def _concept_set_names(circe: dict[str, Any]) -> dict[int, str]:
    return {
        cs["id"]: cs["name"] + "|" + json.dumps(cs["expression"], sort_keys=True)
        for cs in circe["ConceptSets"]
    }


class TestTheRealStudiesBuild:
    @pytest.mark.parametrize(
        "study_id, removed",
        [(9, {"7"}), (10, {"37", "38", "41"})],
        ids=["CARMELINA", "CAROLINA"],
    )
    def test_should_drop_only_the_dose_stability_rows_when_building_the_real_study(
        self, service, monkeypatch, store_studies, study_id, removed
    ):
        eligibility = store_studies[study_id]["eligibility"]
        after = service._build_seeded_target_circe(deepcopy(eligibility))
        # The same stubbed build with the predicate selecting nothing: the build as it
        # was before this branch existed.
        monkeypatch.setattr(
            tte_service_module, "dose_stability_criterion_ids", lambda criteria: set(),
            raising=False,
        )
        before = service._build_seeded_target_circe(deepcopy(eligibility))

        before_refs = before[CRITERION_CONCEPT_SET_REFS_KEY]
        after_refs = after[CRITERION_CONCEPT_SET_REFS_KEY]
        mapped_removed = {cid for cid in removed if f"inclusion:{cid}" in before_refs}
        # Every removed row that is not a group label minted a set before -- so the
        # patch above took effect and this is a real comparison.
        labels = {
            str(c["id"]) for c in eligibility["inclusionCriteria"] if c.get("isGroupLabel")
        }
        assert mapped_removed == removed - labels
        # (1) no rule and no concept set for the removed rows.
        assert not {f"inclusion:{cid}" for cid in removed} & set(after_refs)
        removed_codesets = {before_refs[f"inclusion:{cid}"] for cid in mapped_removed}
        dropped = [r for r in before["InclusionRules"] if _codesets_in(r) & removed_codesets]
        assert len(dropped) == len(mapped_removed)
        assert all(_codesets_in(r) <= removed_codesets for r in dropped), (
            "a dropped rule carried another criterion with it"
        )
        # (2) a skip record under the new reason for each of them.
        assert {
            (r["role"], r["criterionId"])
            for r in after["_skippedCriteria"]
            if r["reason"] == DOSE_STABILITY_REASON
        } == {("inclusion", cid) for cid in removed}
        # (3) every other criterion's emission unchanged.
        before_names, after_names = _concept_set_names(before), _concept_set_names(after)
        kept = [r for r in before["InclusionRules"] if not _codesets_in(r) & removed_codesets]
        assert _canonical(after["InclusionRules"], after_names) == _canonical(kept, before_names)
        assert sorted(after_names.values()) == sorted(
            name for cid, name in before_names.items() if cid not in removed_codesets
        )
        assert after["_unmappedCriteria"] == before["_unmappedCriteria"]
        assert [
            r for r in after["_skippedCriteria"] if r["reason"] != DOSE_STABILITY_REASON
        ] == [
            r
            for r in before["_skippedCriteria"]
            if not (r["role"] == "inclusion" and r["criterionId"] in removed)
        ]
        census_before, census_after = before["_generationCensus"], after["_generationCensus"]
        assert census_after["total"] == census_before["total"]
        assert census_after["mapped"] == census_before["mapped"] - len(mapped_removed)
        assert census_after["total"] == (
            census_after["mapped"]
            + census_after["unmapped"]
            + census_after["demographicRules"]
            + census_after["skipped"]
        )
