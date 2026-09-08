"""A mapping cached under one pipeline mode must not be replayed under another.

Nine environment settings change the CONTENT of a generated concept set. The criterion
cache key was ``text | domain | EMBEDDING_MODEL | LLM_MODEL | critic_signature``, so
eight of them were in no key part at all. Flipping one changed every freshly-mapped
criterion while every cached criterion replayed the old mode -- one export carrying
both, with nothing in the output saying which criteria came from where.

These tests are the guard. They assert the two halves that make a cache key correct: a
flag that changes the result changes the key, and an unchanged configuration still
hits. The second half is not decoration -- a key that never repeats is a cache that
never works, and would pass every test in the first half.

Order-independent by construction: every test sets the whole environment it depends on
via monkeypatch and imports nothing that mutates ``sys.modules``.
"""

from __future__ import annotations

import pytest

from src.agents.agent2.criterion_cache import (
    CriterionCacheEntry,
    CriterionResultCache,
)
from src.utils.mapping_flags import (
    MAPPING_FLAGS,
    canonical_embedding_model,
    mapping_signature,
)

LOCAL = "vllm/Qwen/Qwen2.5-7B-Instruct"

#: Each keyed flag with two values that select genuinely different pipeline behaviour.
#: Read off the consumer, not guessed: ENABLE_REFINER is compared ``== "1"``,
#: INCLUDE_DESC_SEEDS_ONLY and FOOTPRINT_GUARD_IN_HYBRID ``!= "0"``, DOMAIN_PRECHECK
#: ``== "1"``, the FORCE_* pair on truthiness of the stripped string.
FLAG_VALUE_PAIRS = [
    ("ENABLE_REFINER", "1", "0"),
    ("KG_EXPAND_MODE", "clinical_anchor", "clinical"),
    ("INCLUDE_DESC_SEEDS_ONLY", "1", "0"),
    ("FORCE_SLOW_PATH", "", "1"),
    ("FORCE_FAST_PATH", "", "1"),
    ("DOMAIN_PRECHECK", "0", "1"),
    ("FOOTPRINT_GUARD_IN_HYBRID", "0", "1"),
    ("REFINER_FOOTPRINT_THRESHOLD", "1000", "3000"),
]


@pytest.fixture(autouse=True)
def clean_mapping_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold everything else fixed so the flag under test is the only variable."""
    monkeypatch.setenv("LLM_MODEL", LOCAL)
    monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
    monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER", raising=False)
    monkeypatch.delenv("AGENT2_CRITIC_SELF_REFLECT", raising=False)
    for spec in MAPPING_FLAGS:
        monkeypatch.delenv(spec.name, raising=False)


def _key() -> str:
    return CriterionResultCache._make_key("type 2 diabetes", "Condition", "minilm", LOCAL)


@pytest.mark.parametrize(("flag", "one", "other"), FLAG_VALUE_PAIRS)
def test_should_produce_different_keys_when_a_keyed_flag_changes(
    flag: str, one: str, other: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(flag, one)
    first = _key()
    monkeypatch.setenv(flag, other)
    second = _key()

    assert first != second, (
        f"{flag}={one!r} and {flag}={other!r} collided onto the same criterion cache "
        f"key ({first}). A mapping produced under one would replay under the other."
    )


@pytest.mark.parametrize(("flag", "one", "_other"), FLAG_VALUE_PAIRS)
def test_should_produce_the_same_key_when_a_keyed_flag_is_unchanged(
    flag: str, one: str, _other: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key that never repeats is a cache that never works."""
    monkeypatch.setenv(flag, one)

    assert _key() == _key()


def test_should_produce_the_same_key_when_a_flag_is_set_to_its_own_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naming the default explicitly is the same run, so it must not cost a cold cache.

    A delivery script that writes every flag out for the record would otherwise miss
    every entry it had itself just written.
    """
    monkeypatch.delenv("ENABLE_REFINER", raising=False)
    unset = _key()
    monkeypatch.setenv("ENABLE_REFINER", "1")

    assert _key() == unset


def test_should_keep_worker_count_out_of_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pool size moves wall-clock, not the mapping. Keying it invalidates for nothing."""
    monkeypatch.setenv("TTE_MAPPING_MAX_WORKERS", "48")
    small = _key()
    monkeypatch.setenv("TTE_MAPPING_MAX_WORKERS", "4")

    assert _key() == small


def test_should_treat_default_and_minilm_as_one_embedding_namespace() -> None:
    """settings.py spells the MiniLM default "default"; the cache spelled it "minilm".

    Both select the same all-MiniLM-L6-v2 collection, so keying them apart bought a
    full cold run for a spelling.
    """
    assert canonical_embedding_model("default") == canonical_embedding_model("minilm")
    assert canonical_embedding_model(None) == canonical_embedding_model("minilm")
    assert canonical_embedding_model("medcpt") != canonical_embedding_model("minilm")


def test_should_key_default_and_minilm_alike_but_medcpt_apart() -> None:
    as_default = CriterionResultCache._make_key("diabetes", "Condition", "default", LOCAL)
    as_minilm = CriterionResultCache._make_key("diabetes", "Condition", "minilm", LOCAL)
    as_medcpt = CriterionResultCache._make_key("diabetes", "Condition", "medcpt", LOCAL)

    assert as_default == as_minilm
    assert as_medcpt != as_minilm


def test_should_name_every_keyed_flag_in_the_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """The signature is the audit trail for which flags are keyed; keep it legible."""
    signature = mapping_signature()

    for spec in MAPPING_FLAGS:
        if spec.keyed:
            assert f"{spec.name}=" in signature, f"{spec.name} claims to be keyed but is absent"
        else:
            assert f"{spec.name}=" not in signature, f"{spec.name} is not keyed but appears"


def test_should_miss_the_cache_when_the_flag_changes_after_an_entry_was_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The actual hazard, end to end: cache under one mode, flip, and look it up again.

    Differing keys are a proxy. This is the thing itself -- a real entry stored under
    ENABLE_REFINER=1 must not come back once the refiner is off, because the concept
    ids it holds were produced with subsumed ancestors dropped.
    """
    monkeypatch.setenv("CRITERION_CACHE_ENABLED", "true")
    cache = CriterionResultCache(db_path=str(tmp_path / "criterion_cache.sqlite"))

    monkeypatch.setenv("ENABLE_REFINER", "1")
    refined = CriterionCacheEntry(
        concept_ids=[201826],
        expression={"items": [{"concept": {"CONCEPT_ID": 201826}, "includeDescendants": True}]},
        name="type 2 diabetes",
        domain="Condition",
        created_at="2026-09-08T00:00:00+00:00",
    )
    cache.put("type 2 diabetes", "Condition", refined)

    assert cache.get("type 2 diabetes", "Condition") is not None, (
        "the entry must be readable back under the mode that produced it"
    )

    monkeypatch.setenv("ENABLE_REFINER", "0")
    replayed = cache.get("type 2 diabetes", "Condition")

    assert replayed is None, (
        "an entry mapped with the refiner ON was replayed with the refiner OFF; that is "
        "the single export mixing two modes this change exists to prevent"
    )
