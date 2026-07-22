"""
Tests for artemis/scripts/inject_cv_events.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ARTEMIS_DIR / "scripts" / "inject_cv_events.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("inject_cv_events", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def test_ci_width_computation():
    assert MODULE.ci_width(2.0, 3.0) == 1.0
    assert MODULE.ci_width(None, 3.0) is None


def test_parse_args_has_calibration_flags():
    args = MODULE.parse_args(
        [
            "--target-ci-ratio-low",
            "0.9",
            "--target-ci-ratio-high",
            "1.1",
            "--max-calibration-iters",
            "8",
            "--studies",
            "LEADER",
        ]
    )

    assert args.target_ci_ratio_low == 0.9
    assert args.target_ci_ratio_high == 1.1
    assert args.max_calibration_iters == 8
    assert args.studies == ["LEADER"]


def test_assign_events_label_blind_to_ai_gold_membership():
    # Same clinical profile, only AI/Gold membership swapped.
    # Label-blind assignment should yield identical event probabilities.
    df = pd.DataFrame(
        [
            {
                "person_id": 1,
                "treated": 1,
                "age": 70,
                "male": 1,
                "risk_factor_count": 2,
                "ai_member": 1,
                "gold_member": 0,
            },
            {
                "person_id": 2,
                "treated": 1,
                "age": 70,
                "male": 1,
                "risk_factor_count": 2,
                "ai_member": 0,
                "gold_member": 1,
            },
        ]
    )

    out = MODULE.assign_events_label_blind(df, seed=7, base_rate=0.10, true_hr=2.0)

    p1 = out.loc[out.person_id == 1, "event_prob"].item()
    p2 = out.loc[out.person_id == 2, "event_prob"].item()
    assert p1 == p2
