"""The criterion cache answers a seed only with the mapping of that exact seed.

`criterion_cache._normalize` lower-cased the seed before hashing it, so two seeds that differ only
in case shared one entry: whichever was mapped first answered for the other. Agent 2 is handed the
seed as written, so the second seed was served a mapping computed for a different string.
Whitespace runs still collapse: that is the same text.

The real pair, from the 2026-10-12 P3 dry arm A store (one run, one cache): EMPA-REG exclusion #1
is seeded "glucose" and CAROLINA exclusion #11 "Glucose", both Measurement. Rows:
``tests/fixtures/restated_text_key_rows.json``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.agent2 import criterion_cache as cc
from src.utils.criterion_seed import criterion_mapper_seed

ROWS = json.loads(
    (Path(__file__).parent / "fixtures" / "restated_text_key_rows.json").read_text()
)
(EMPA_REG_GLUCOSE,) = ROWS["empa_reg_glucose_row"]["rows"]
(CAROLINA_GLUCOSE,) = ROWS["carolina_glucose_row"]["rows"]


@pytest.fixture(autouse=True)
def _cache_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRITERION_CACHE_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_MODEL", "minilm")


def _entry(name: str) -> cc.CriterionCacheEntry:
    return cc.CriterionCacheEntry(
        concept_ids=[3004501],
        expression={"items": [{"concept": {"CONCEPT_ID": 3004501}}]},
        name=name,
        domain="Measurement",
        created_at="2026-10-14T00:00:00+00:00",
    )


def test_should_seed_the_two_rows_with_texts_that_differ_only_in_case():
    """The fixture is the collision itself, not a constructed one."""
    first, second = criterion_mapper_seed(EMPA_REG_GLUCOSE), criterion_mapper_seed(CAROLINA_GLUCOSE)
    assert (first, second) == ("glucose", "Glucose")
    assert (EMPA_REG_GLUCOSE["domain"], CAROLINA_GLUCOSE["domain"]) == ("Measurement", "Measurement")


def test_should_miss_when_a_seed_differs_from_the_cached_seed_only_in_case():
    cache = cc.CriterionResultCache(max_entries=10, ttl_hours=1)
    cache.put(criterion_mapper_seed(EMPA_REG_GLUCOSE), "Measurement", _entry("glucose"))
    assert cache.get(criterion_mapper_seed(CAROLINA_GLUCOSE), "Measurement") is None
    assert cache.get(criterion_mapper_seed(EMPA_REG_GLUCOSE), "Measurement") is not None


def test_should_hit_when_a_seed_differs_from_the_cached_seed_only_in_whitespace():
    cache = cc.CriterionResultCache(max_entries=10, ttl_hours=1)
    cache.put("  Glucose  ", "Measurement", _entry("Glucose"))
    assert cache.get("Glucose", "Measurement") is not None


def test_should_not_serve_an_entry_written_under_the_case_folded_key_when_the_seed_is_lower_case(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """An all-lower-case seed hashes the same text either way, so an entry another case variant
    wrote under the old key would otherwise be replayed. The entry here is written exactly as
    the old key wrote it: lower-cased seed, the entry shape of that time."""
    cache = cc.CriterionResultCache(max_entries=10, ttl_hours=1, db_path=str(tmp_path / "c.sqlite"))
    with monkeypatch.context() as old:
        old.setattr(cc, "_normalize", lambda text: " ".join(text.lower().split()))
        old.setattr(cc, "ENTRY_SHAPE", "route-free-v1")
        cache.put(criterion_mapper_seed(CAROLINA_GLUCOSE), "Measurement", _entry("Glucose"))
        assert cache.get(criterion_mapper_seed(EMPA_REG_GLUCOSE), "Measurement") is not None
    assert cache.get(criterion_mapper_seed(EMPA_REG_GLUCOSE), "Measurement") is None
