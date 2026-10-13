"""The seeded build hands each criterion the candidate pool of its own pre-fetch query.

`ConceptRetriever.batch_search` is asked ``(text, domain_hint)`` per position and answers per
position (``by_index``). The build read the answer by text, ``batch_results.get(text, [])``,
so a seed issued under two domain hints -- two queries, one text -- handed the second criterion
the first one's pool, retrieved under a domain filter it never asked for. That pool is the
mapper's entire primary candidate set.

The real collision: on the 2026-10-12 P3 dry arm A, CAROLINA exclusion #66 (Observation) and
#68 (Condition) are both seeded "cancer" -- their annotation's base span -- and the retriever
logged the seed under two hints. Rows: ``tests/fixtures/restated_text_key_rows.json``.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import src.agents.agent2.retriever as retriever_module
from src.services.tte_service import TTEService
from src.utils.criterion_seed import criterion_mapper_seed

ROWS = json.loads(
    (Path(__file__).parent / "fixtures" / "restated_text_key_rows.json").read_text()
)
CANCER_GROUP = ROWS["carolina_cancer_seed_group"]["rows"]

#: One concept per domain filter, so a pool says which filter it was retrieved under.
POOL_BY_HINT = {
    "Observation": ("4214956", "Observation"),
    "Condition": ("443392", "Condition"),
}


class _Collection:
    """Answers per ``where={"domain_id": ...}``, the way the real collection does."""

    def query(self, query_texts, n_results, include, where=None):
        concept_id, domain = POOL_BY_HINT.get((where or {}).get("domain_id"), ("0", "Condition"))
        n = len(query_texts)
        return {
            "ids": [[concept_id] for _ in range(n)],
            "metadatas": [[{"domain_id": domain, "vocabulary_id": "SNOMED",
                            "concept_class_id": "Clinical Finding"}] for _ in range(n)],
            "distances": [[50.0] for _ in range(n)],
            "documents": [[domain] for _ in range(n)],
        }


class _Retriever(retriever_module.ConceptRetriever):
    def __init__(self) -> None:
        self.concept_weights = {}
        self.collection = _Collection()


@pytest.fixture
def pools(monkeypatch) -> dict[str, Any]:
    """Build CAROLINA's group and return, per criterion id, the pool the mapper was handed."""
    monkeypatch.setattr(retriever_module, "ConceptRetriever", _Retriever)
    svc = TTEService.__new__(TTEService)
    monkeypatch.setattr(
        svc,
        "_recommend_seeded_concept_set",
        lambda seed_text, **_: {
            "name": seed_text,
            "domain": "Drug",
            "expression": {"items": []},
            "mapping_metadata": None,
        },
    )
    handed: dict[str, Any] = {}

    def rule(*, criterion: dict[str, Any], pre_fetched_candidates=None, **_: Any) -> None:
        handed[str(criterion["id"])] = pre_fetched_candidates
        return None

    monkeypatch.setattr(svc, "_build_seeded_eligibility_rule", rule)
    svc._build_seeded_target_circe(
        {
            "targetCohortName": "linagliptin",
            "inclusionCriteria": [],
            "exclusionCriteria": copy.deepcopy(CANCER_GROUP),
        }
    )
    return handed


def test_should_seed_both_rows_with_one_text_under_two_domains():
    """The fixture is the collision itself, not a constructed one."""
    by_id = {row["id"]: row for row in CANCER_GROUP}
    assert criterion_mapper_seed(by_id[66]) == criterion_mapper_seed(by_id[68]) == "cancer"
    assert (by_id[66]["domain"], by_id[68]["domain"]) == ("Observation", "Condition")


def test_should_hand_the_condition_row_the_condition_pool_when_an_observation_row_shares_its_seed(
    pools,
):
    assert [c.domain_id for c in pools["68"]] == ["Condition"]


def test_should_hand_the_observation_row_the_observation_pool_when_a_condition_row_shares_its_seed(
    pools,
):
    assert [c.domain_id for c in pools["66"]] == ["Observation"]
