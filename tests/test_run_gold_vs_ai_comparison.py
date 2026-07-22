"""
Tests for artemis/scripts/run_gold_vs_ai_comparison.py helper behavior.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ARTEMIS_DIR / "scripts" / "run_gold_vs_ai_comparison.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_gold_vs_ai_comparison", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def test_build_fixed_rest_comparator_ids_is_deterministic_and_excludes_ids():
    all_ids = set(range(1, 51))
    excluded = {1, 2, 3, 4, 5}

    first = MODULE.build_fixed_rest_comparator_ids(
        all_person_ids=all_ids,
        excluded_ids=excluded,
        max_comparator=10,
        seed=123,
    )
    second = MODULE.build_fixed_rest_comparator_ids(
        all_person_ids=all_ids,
        excluded_ids=excluded,
        max_comparator=10,
        seed=123,
    )

    assert first == second
    assert len(first) == 10
    assert not (set(first) & excluded)


def test_parse_args_defaults_to_fixed_rest_mode():
    args = MODULE.parse_args([])
    assert args.comparator_mode == "fixed_rest"
