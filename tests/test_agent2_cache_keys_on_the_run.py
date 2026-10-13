"""Agent2Cache answers only a lookup made under the run, text and domain that filled it.

``Agent2Cache`` (``data/cache/agent2_cache.json``, read by ``scripts/benchmark_a_direct.py``,
``scripts/benchmark_exp_d.py`` and ``scripts/verify_leader_design_e2e.py``) keyed on
``text | domain`` alone. The Agent 2 mapping it stores also depends on the LLM model, the
embedding model, the critic configuration and the mapping flags -- the same parts the
criterion cache keys on -- so a benchmark run under one configuration replayed another's
mappings as cache hits.

``benchmark_a_direct.process_single_rule`` also looked entries up and stored them without
the domain it passed to Agent 2 (``get(qt)``, ``domain_hint: None``), so one concept-set
name used under two domains got the first domain's mapping.

The model half of the key is asserted with the other caches in
``tests/test_cache_keys_carry_model.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.agents.agent2.agent2_cache import Agent2Cache

ROOT = Path(__file__).resolve().parents[1]
TEXT = "type 2 diabetes"


@pytest.fixture(autouse=True)
def fixed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.utils.mapping_flags import MAPPING_FLAGS

    monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
    monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER", raising=False)
    monkeypatch.delenv("AGENT2_CRITIC_SELF_REFLECT", raising=False)
    for spec in MAPPING_FLAGS:
        monkeypatch.delenv(spec.name, raising=False)


def _filled(tmp_path: Path) -> Agent2Cache:
    cache = Agent2Cache(cache_path=tmp_path / "agent2_cache.json")
    cache.put(TEXT, "Condition", [201826])
    return cache


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("ENABLE_REFINER", "0"),
        ("EMBEDDING_MODEL", "medcpt"),
        ("AGENT2_CRITIC_MODEL_TIER", "gpt-4o"),
    ],
)
def test_should_miss_when_the_run_configuration_changes(
    variable: str, value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = _filled(tmp_path)
    monkeypatch.setenv(variable, value)

    assert cache.get(TEXT, "Condition") is None


def test_should_hit_when_text_domain_and_run_are_unchanged(tmp_path: Path) -> None:
    cache = _filled(tmp_path)

    assert cache.get(TEXT, "Condition") == [201826]
    assert Agent2Cache(cache_path=tmp_path / "agent2_cache.json").get(TEXT, "Condition") == [201826]


def _benchmark_a_direct(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "benchmark_a_direct_under_test", ROOT / "scripts" / "benchmark_a_direct.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Agent2:
    """Maps by domain, so a replayed entry is visible as the other domain's ids."""

    def __init__(self) -> None:
        self.domains: list[str | None] = []

    def process_with_details(self, text: str, domain_hint: str | None = None) -> Any:
        self.domains.append(domain_hint)
        return SimpleNamespace(
            concept_ids=[100 if domain_hint == "Measurement" else 200],
            processing_time_ms=0.0,
            overbroad_concept_ids=[],
        )


def test_should_map_again_when_benchmark_a_direct_meets_one_name_under_another_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _benchmark_a_direct(monkeypatch)
    agent2 = _Agent2()
    monkeypatch.setattr(script, "get_agent2", lambda: agent2)
    monkeypatch.setattr(script, "get_troy_concept_ids", lambda rule, troy: [])
    monkeypatch.setattr(script, "resolve_troy_rule", lambda cur, rule, troy: set())
    monkeypatch.setattr(script, "map_nonstandard_to_standard", lambda cur, ids: (set(ids), {}))
    monkeypatch.setattr(
        script, "resolve_concept_set", lambda cur, ids, no_expand_ids=None: set(ids)
    )
    monkeypatch.setattr(
        script, "calculate_semantic_distance",
        lambda cur, a, b: {"soft_precision_1hop": 0.0, "soft_precision_2hop": 0.0},
    )
    cursor = SimpleNamespace(close=lambda: None)
    pool = SimpleNamespace(getconn=lambda: SimpleNamespace(cursor=lambda: cursor),
                           putconn=lambda conn: None)
    cache = Agent2Cache(cache_path=tmp_path / "agent2_cache.json")

    def rule(index: int, domain: str) -> Any:
        return script.TROYRule(
            index=index, name="Glucose", occurrence_type="at_least", concept_set_ids=[],
            concept_set_names=["Glucose"], domain=domain, cs_domains={"Glucose": domain},
        )

    script.process_single_rule(rule(0, "Measurement"), {}, pool, cache)
    second = script.process_single_rule(rule(1, "Drug"), {}, pool, cache)

    assert agent2.domains == ["Measurement", "Drug"]
    assert second["agent2"]["raw_ids"] == [200]
