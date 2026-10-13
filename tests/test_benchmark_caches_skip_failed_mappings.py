"""The benchmark scripts' Agent2Cache stores a mapping only when no stage of it failed.

``scripts/benchmark_a_direct.py`` stored every non-empty mapping and
``scripts/benchmark_exp_d.py`` every mapping, empty or not, so a mapping built from the
seeds alone (a KG or critic failure), or an Agent 2 exception recorded as an empty list,
was replayed on the next run as that query's answer -- the same defect the criterion
cache was closed against (3b102f5, 61e15d7). Each fix is one condition on the store.

``scripts/verify_leader_design_e2e.py`` is not covered: it maps at import time and reads
``process()``, which returns the ids without the failures, so it cannot be fixed by a
condition or tested without running it.

Nothing reaches a database or a model: Agent 2 and the vocabulary reads are replaced.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.agents.agent2.agent2_cache import Agent2Cache
from src.models.ir import MappingResult

ROOT = Path(__file__).resolve().parents[1]
CRITIC = "OutputParserException: Invalid json output: {\"selected_concepts\": [{\"conc"


@pytest.fixture(autouse=True)
def fixed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run half of the Agent2Cache key, pinned as tests/test_agent2_cache_keys_on_the_run.py pins it."""
    from src.utils.mapping_flags import MAPPING_FLAGS

    monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
    monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER", raising=False)
    monkeypatch.delenv("AGENT2_CRITIC_SELF_REFLECT", raising=False)
    for spec in MAPPING_FLAGS:
        monkeypatch.delenv(spec.name, raising=False)
    # Importing a script runs os.environ.setdefault("PIPELINE_MODE", "benchmark"); pin it
    # so the import cannot leave it set for the rest of the session.
    monkeypatch.setenv("PIPELINE_MODE", "run")


def _script(monkeypatch: pytest.MonkeyPatch, name: str) -> Any:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── benchmark_a_direct ───────────────────────────────────────


def _run_a_direct(monkeypatch, tmp_path, mapping: MappingResult) -> Agent2Cache:
    script = _script(monkeypatch, "benchmark_a_direct")
    monkeypatch.setattr(script, "get_agent2",
                        lambda: SimpleNamespace(process_with_details=lambda *a, **k: mapping))
    monkeypatch.setattr(script, "get_troy_concept_ids", lambda rule, troy: [])
    monkeypatch.setattr(script, "resolve_troy_rule", lambda cur, rule, troy: set())
    monkeypatch.setattr(script, "map_nonstandard_to_standard", lambda cur, ids: (set(ids), {}))
    monkeypatch.setattr(script, "resolve_concept_set", lambda cur, ids, no_expand_ids=None: set(ids))
    monkeypatch.setattr(script, "calculate_semantic_distance",
                        lambda cur, a, b: {"soft_precision_1hop": 0.0, "soft_precision_2hop": 0.0})
    cursor = SimpleNamespace(close=lambda: None)
    pool = SimpleNamespace(getconn=lambda: SimpleNamespace(cursor=lambda: cursor),
                           putconn=lambda conn: None)
    cache = Agent2Cache(cache_path=tmp_path / "agent2_cache.json")
    rule = script.TROYRule(index=0, name="History of stroke", occurrence_type="at_least",
                           concept_set_ids=[], concept_set_names=["History of stroke"],
                           domain="Condition", cs_domains={"History of stroke": "Condition"})
    script.process_single_rule(rule, {}, pool, cache)
    return cache


def test_should_not_store_a_seeds_only_mapping_in_benchmark_a_direct(monkeypatch, tmp_path):
    mapping = MappingResult(concept_ids=[10], seed_concept_ids=[10], critic_failure=CRITIC)

    cache = _run_a_direct(monkeypatch, tmp_path, mapping)

    assert cache.get("History of stroke", "Condition") is None


def test_should_store_a_clean_mapping_in_benchmark_a_direct(monkeypatch, tmp_path):
    cache = _run_a_direct(monkeypatch, tmp_path, MappingResult(concept_ids=[10, 11]))

    assert cache.get("History of stroke", "Condition") == [10, 11]


# ── benchmark_exp_d ──────────────────────────────────────────


def _run_exp_d(monkeypatch, tmp_path, ids: list[int], meta: dict[str, Any]) -> Agent2Cache:
    script = _script(monkeypatch, "benchmark_exp_d")
    monkeypatch.setattr(script, "invoke_agent2", lambda text, domain=None: (ids, meta))
    monkeypatch.setattr(script, "map_nonstandard_to_standard", lambda cur, got: (set(got), {}))
    monkeypatch.setattr(script, "resolve_concept_set", lambda cur, got: set(got))
    cache = Agent2Cache(cache_path=tmp_path / "agent2_cache.json")
    script._invoke_agent2_with_split("History of stroke", "Condition", cur=None, cache=cache)
    return cache


FAILED_META = {
    "seeds only": ([10], {"mapping_failures": [
        {"stage": "critic", "reason": CRITIC, "seedsOnly": True}]}),
    "agent 2 raised": ([], {"mapping_failures": [], "error": "TimeoutError: read timeout"}),
}


@pytest.mark.parametrize("case", sorted(FAILED_META))
def test_should_not_store_a_failed_mapping_in_benchmark_exp_d(monkeypatch, tmp_path, case):
    ids, meta = FAILED_META[case]

    cache = _run_exp_d(monkeypatch, tmp_path, ids, meta)

    assert cache.get("History of stroke", "Condition") is None


def test_should_store_a_clean_mapping_in_benchmark_exp_d(monkeypatch, tmp_path):
    cache = _run_exp_d(monkeypatch, tmp_path, [10, 11], {"mapping_failures": []})

    assert cache.get("History of stroke", "Condition") == [10, 11]
