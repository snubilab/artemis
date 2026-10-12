"""Signature tests for the seeded outcome builders.

The outcome-eligibility bridge (outcome label split on or/and/,/; and matched against
criterion descriptions, RFC-016 A23) was deleted; ``tests/test_p5_on_path_deletions.py``
judges that on the candidate rows.
"""

import inspect

import pytest

from src.services.tte_service import TTEService


class TestBuildSeededConditionCirceSignature:
    """Verify _build_seeded_condition_circe accepts new params."""

    def test_accepts_pre_fetched_candidates_param(self):
        svc = TTEService.__new__(TTEService)
        sig = inspect.signature(svc._build_seeded_condition_circe)
        assert "pre_fetched_candidates" in sig.parameters
        assert "expected_domain" in sig.parameters

    def test_single_codeset_circe_accepts_pre_fetched(self):
        svc = TTEService.__new__(TTEService)
        sig = inspect.signature(svc._build_seeded_single_codeset_circe)
        assert "pre_fetched_candidates" in sig.parameters
