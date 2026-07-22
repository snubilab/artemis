"""
Tests for artemis/scripts/calibrate_cv_event_injection.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ARTEMIS_DIR / "scripts" / "calibrate_cv_event_injection.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("calibrate_cv_event_injection", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def test_update_rates_increases_events_when_ai_ci_wider_than_gold():
    rates = MODULE.RateParams(base_rate=0.10, true_hr=2.0)

    updated = MODULE.update_rates(
        rates,
        ai_ci_width=1.8,
        gold_ci_width=1.0,
        ai_events=40,
        gold_events=120,
    )

    assert updated.base_rate > rates.base_rate


def test_update_rates_decreases_events_when_ai_ci_narrower_than_gold():
    rates = MODULE.RateParams(base_rate=0.20, true_hr=2.0)

    updated = MODULE.update_rates(
        rates,
        ai_ci_width=0.7,
        gold_ci_width=1.2,
        ai_events=200,
        gold_events=80,
    )

    assert updated.base_rate < rates.base_rate


def test_ci_width_ratio_none_when_any_ci_missing():
    assert MODULE.compute_ci_width_ratio(None, 2.0, 1.0, 2.0) is None
