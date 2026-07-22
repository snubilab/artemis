"""
Unit tests for mapping_retry — selective per-entity retry planning.
No DB/LLM dependency. Pure logic tests.
"""
import sys
import types

import pytest

# ── pandas stub to avoid import error from src.pipeline.__init__ ──
_injected_pandas = False
if "pandas" not in sys.modules:
    pd_stub = types.ModuleType("pandas")
    pd_stub.DataFrame = type("DataFrame", (), {"__init__": lambda self, *a, **k: None})  # type: ignore
    sys.modules["pandas"] = pd_stub
    _injected_pandas = True

from src.pipeline.mapping_retry import (
    build_retry_plan,
    RetryCandidate,
    RetryPlan,
    MAX_ENTITY_RETRIES,
)


def teardown_module():
    if _injected_pandas:
        sys.modules.pop("pandas", None)


class TestBuildRetryPlan:
    """Tests for build_retry_plan() policy."""

    def test_empty_mapping_creates_candidate(self):
        """Entity with no mapping → retry candidate (slow path)."""
        audit = {"domain_mismatches": [], "too_few": [], "high_risk_entities": [], "overbroad_entities": []}
        raw_mapped_sets = []  # nothing mapped
        entities = [
            {"text": "Metformin", "domain": "Drug", "source": "target", "entity_key": "target:primary:0:0"},
        ]
        plan = build_retry_plan(audit, raw_mapped_sets, entities, retry_counts={})

        assert plan.has_candidates
        assert len(plan.candidates) == 1
        assert plan.candidates[0].entity_text == "Metformin"
        assert plan.candidates[0].reason == "empty_mapping"
        assert plan.candidates[0].force_slow_path is True

    def test_empty_mapping_prefers_entity_key_when_duplicate_text_exists(self):
        audit = {"domain_mismatches": [], "too_few": [], "high_risk_entities": [], "overbroad_entities": []}
        raw_mapped_sets = [
            {"name": "Heart Failure", "domain": "Condition", "concept_ids": [1], "entity_key": "target:inclusion:0:0"},
        ]
        entities = [
            {"text": "Heart Failure", "domain": "Condition", "source": "target", "entity_key": "target:inclusion:0:0"},
            {"text": "Heart Failure", "domain": "Condition", "source": "target", "entity_key": "target:inclusion:1:0"},
        ]

        plan = build_retry_plan(audit, raw_mapped_sets, entities, retry_counts={})

        assert plan.has_candidates
        assert len(plan.candidates) == 1
        assert plan.candidates[0].entity_key == "target:inclusion:1:0"
        assert plan.candidates[0].entity_text == "Heart Failure"

    def test_domain_mismatch_first_retry_keeps_original_domain(self):
        """First domain mismatch retry should stay in the original domain."""
        audit = {
            "domain_mismatches": [
                {
                    "entity": "Metformin",
                    "entity_domain": "Drug",
                    "concept_domains": ["Condition", "Condition", "Observation"],
                    "mismatch_count": 3,
                    "total_concepts": 3,
                    "expected_domain_count": 0,
                    "known_concept_count": 3,
                    "unknown_domain_count": 0,
                    "domain_counts": {"Condition": 2, "Observation": 1},
                    "dominant_domain": "Condition",
                    "dominant_ratio": 2 / 3,
                },
            ],
            "too_few": [], "high_risk_entities": [], "overbroad_entities": [],
        }
        raw_mapped_sets = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2, 3], "entity_key": "target:primary:0:0"},
        ]
        entities = [
            {"text": "Metformin", "domain": "Drug", "source": "target", "entity_key": "target:primary:0:0"},
        ]
        plan = build_retry_plan(audit, raw_mapped_sets, entities, retry_counts={})

        assert plan.has_candidates
        assert len(plan.candidates) == 1
        assert plan.candidates[0].reason == "domain_mismatch"
        assert plan.candidates[0].strategy == "same_domain"
        assert plan.candidates[0].corrected_domain is None

    def test_domain_mismatch_prefers_entity_key_when_duplicate_text_exists(self):
        audit = {
            "domain_mismatches": [
                {
                    "entity": "Heart Failure",
                    "entity_key": "target:inclusion:0:0",
                    "entity_domain": "Condition",
                    "concept_domains": ["Drug"],
                    "mismatch_count": 1,
                    "total_concepts": 1,
                    "expected_domain_count": 0,
                    "known_concept_count": 1,
                    "unknown_domain_count": 0,
                    "domain_counts": {"Drug": 1},
                    "dominant_domain": "Drug",
                    "dominant_ratio": 1.0,
                },
            ],
            "too_few": [], "high_risk_entities": [], "overbroad_entities": [],
        }
        raw_mapped_sets = [
            {"name": "Heart Failure", "domain": "Condition", "concept_ids": [1], "entity_key": "target:inclusion:0:0"},
            {"name": "Heart Failure", "domain": "Condition", "concept_ids": [2], "entity_key": "target:inclusion:1:0"},
        ]
        entities = [
            {"text": "Heart Failure", "domain": "Condition", "source": "target", "entity_key": "target:inclusion:0:0"},
            {"text": "Heart Failure", "domain": "Condition", "source": "target", "entity_key": "target:inclusion:1:0"},
        ]

        plan = build_retry_plan(audit, raw_mapped_sets, entities, retry_counts={})

        assert plan.has_candidates
        assert len(plan.candidates) == 1
        assert plan.candidates[0].entity_key == "target:inclusion:0:0"

    def test_domain_mismatch_second_retry_allows_strong_correction(self):
        """Second mismatch retry may correct domain only with strong evidence."""
        audit = {
            "domain_mismatches": [
                {
                    "entity": "Metformin",
                    "entity_domain": "Drug",
                    "concept_domains": ["Condition", "Condition", "Condition", "Condition"],
                    "mismatch_count": 4,
                    "total_concepts": 4,
                    "expected_domain_count": 0,
                    "known_concept_count": 4,
                    "unknown_domain_count": 0,
                    "domain_counts": {"Condition": 4},
                    "dominant_domain": "Condition",
                    "dominant_ratio": 1.0,
                },
            ],
            "too_few": [], "high_risk_entities": [], "overbroad_entities": [],
        }
        raw_mapped_sets = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2, 3, 4], "entity_key": "target:primary:0:0"},
        ]
        entities = [
            {"text": "Metformin", "domain": "Drug", "source": "target", "entity_key": "target:primary:0:0"},
        ]

        plan = build_retry_plan(
            audit,
            raw_mapped_sets,
            entities,
            retry_counts={"domain_mismatch:target:primary:0:0": 1},
        )

        assert plan.has_candidates
        assert plan.candidates[0].strategy == "corrected_domain"
        assert plan.candidates[0].corrected_domain == "Condition"

    def test_domain_mismatch_second_retry_refuses_correction_if_expected_domain_still_present(self):
        """Domain correction must stay off if the expected domain still appears in results."""
        audit = {
            "domain_mismatches": [
                {
                    "entity": "Metformin",
                    "entity_domain": "Drug",
                    "concept_domains": ["Condition", "Condition", "Condition"],
                    "mismatch_count": 3,
                    "total_concepts": 4,
                    "expected_domain_count": 1,
                    "known_concept_count": 4,
                    "unknown_domain_count": 0,
                    "domain_counts": {"Condition": 3, "Drug": 1},
                    "dominant_domain": "Condition",
                    "dominant_ratio": 0.75,
                },
            ],
            "too_few": [], "high_risk_entities": [], "overbroad_entities": [],
        }
        raw_mapped_sets = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2, 3, 4], "entity_key": "target:primary:0:0"},
        ]
        entities = [
            {"text": "Metformin", "domain": "Drug", "source": "target", "entity_key": "target:primary:0:0"},
        ]

        plan = build_retry_plan(
            audit,
            raw_mapped_sets,
            entities,
            retry_counts={"domain_mismatch:target:primary:0:0": 1},
        )

        assert plan.has_candidates
        assert plan.candidates[0].strategy == "same_domain"
        assert plan.candidates[0].corrected_domain is None

    def test_domain_mismatch_correction_thresholds_are_configurable_via_env(self, monkeypatch):
        """Env thresholds should control when corrected_domain becomes available."""
        audit = {
            "domain_mismatches": [
                {
                    "entity": "Metformin",
                    "entity_domain": "Drug",
                    "concept_domains": ["Condition", "Condition", "Condition"],
                    "mismatch_count": 3,
                    "total_concepts": 3,
                    "expected_domain_count": 0,
                    "known_concept_count": 3,
                    "unknown_domain_count": 0,
                    "domain_counts": {"Condition": 3},
                    "dominant_domain": "Condition",
                    "dominant_ratio": 1.0,
                },
            ],
            "too_few": [], "high_risk_entities": [], "overbroad_entities": [],
        }
        raw_mapped_sets = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2, 3], "entity_key": "target:primary:0:0"},
        ]
        entities = [
            {"text": "Metformin", "domain": "Drug", "source": "target", "entity_key": "target:primary:0:0"},
        ]

        monkeypatch.setenv("SUPERVISOR_DOMAIN_CORRECTION_MIN_COUNT", "4")

        plan = build_retry_plan(
            audit,
            raw_mapped_sets,
            entities,
            retry_counts={"domain_mismatch:target:primary:0:0": 1},
        )

        assert plan.has_candidates
        assert plan.candidates[0].strategy == "same_domain"
        assert plan.candidates[0].corrected_domain is None

    def test_domain_mismatch_correction_stage_is_configurable_via_env(self, monkeypatch):
        """Env should control after how many mismatch retries domain correction can start."""
        audit = {
            "domain_mismatches": [
                {
                    "entity": "Metformin",
                    "entity_domain": "Drug",
                    "concept_domains": ["Condition", "Condition", "Condition", "Condition"],
                    "mismatch_count": 4,
                    "total_concepts": 4,
                    "expected_domain_count": 0,
                    "known_concept_count": 4,
                    "unknown_domain_count": 0,
                    "domain_counts": {"Condition": 4},
                    "dominant_domain": "Condition",
                    "dominant_ratio": 1.0,
                },
            ],
            "too_few": [], "high_risk_entities": [], "overbroad_entities": [],
        }
        raw_mapped_sets = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2, 3, 4], "entity_key": "target:primary:0:0"},
        ]
        entities = [
            {"text": "Metformin", "domain": "Drug", "source": "target", "entity_key": "target:primary:0:0"},
        ]

        monkeypatch.setenv("SUPERVISOR_DOMAIN_CORRECTION_AFTER_RETRIES", "2")

        plan = build_retry_plan(
            audit,
            raw_mapped_sets,
            entities,
            retry_counts={"domain_mismatch:target:primary:0:0": 1},
        )

        assert plan.has_candidates
        assert plan.candidates[0].strategy == "same_domain"
        assert plan.candidates[0].corrected_domain is None

    def test_too_few_is_report_only(self):
        """too_few_concepts → report-only (skipped signal), no retry."""
        audit = {
            "domain_mismatches": [],
            "too_few": [{"entity": "Aspirin"}],
            "high_risk_entities": [], "overbroad_entities": [],
        }
        raw_mapped_sets = [
            {"name": "Aspirin", "domain": "Drug", "concept_ids": [1], "entity_key": "target:inclusion:0:0"},
        ]
        entities = [
            {"text": "Aspirin", "domain": "Drug", "source": "target", "entity_key": "target:inclusion:0:0"},
        ]
        plan = build_retry_plan(audit, raw_mapped_sets, entities, retry_counts={})

        assert not plan.has_candidates
        assert any("too_few" in s for s in plan.skipped_signals)

    def test_too_few_concepts_key_is_report_only(self):
        """Producer audit key too_few_concepts should also be honored."""
        audit = {
            "domain_mismatches": [],
            "too_few_concepts": [{"entity": "Aspirin"}],
            "high_risk_entities": [],
            "overbroad_entities": [],
        }

        plan = build_retry_plan(audit, [], [], retry_counts={})

        assert not plan.has_candidates
        assert any("too_few:Aspirin" == s for s in plan.skipped_signals)

    def test_high_risk_is_report_only(self):
        """High-risk entities → report-only."""
        audit = {
            "domain_mismatches": [],
            "too_few": [],
            "high_risk_entities": [{"entity": "T2DM", "triggers": ["fast_path", "critic_skipped"]}],
            "overbroad_entities": [],
        }
        plan = build_retry_plan(audit, [], [], retry_counts={})
        assert not plan.has_candidates
        assert any("high_risk" in s for s in plan.skipped_signals)

    def test_max_retries_exhausted_skips(self):
        """Entity at max retries → skip (report-only)."""
        audit = {"domain_mismatches": [], "too_few": [], "high_risk_entities": [], "overbroad_entities": []}
        entities = [
            {"text": "Unknown", "domain": "Drug", "source": "target", "entity_key": "target:inclusion:0:0"},
        ]
        retry_counts = {f"entity:target:inclusion:0:0": MAX_ENTITY_RETRIES}

        plan = build_retry_plan(audit, [], entities, retry_counts)

        assert not plan.has_candidates
        assert any("max retries exhausted" in s for s in plan.skipped_signals)

    def test_no_signals_empty_plan(self):
        """No issues → empty plan."""
        audit = {"domain_mismatches": [], "too_few": [], "high_risk_entities": [], "overbroad_entities": []}
        entities = [
            {"text": "Metformin", "domain": "Drug", "source": "target", "entity_key": "target:primary:0:0"},
        ]
        raw = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2], "entity_key": "target:primary:0:0"},
        ]
        plan = build_retry_plan(audit, raw, entities, retry_counts={})

        assert not plan.has_candidates
        assert len(plan.skipped_signals) == 0


class TestRetryPlan:
    """RetryPlan dataclass tests."""

    def test_has_candidates_true(self):
        plan = RetryPlan(candidates=[RetryCandidate(entity_key="a", entity_text="X")])
        assert plan.has_candidates is True

    def test_has_candidates_false(self):
        plan = RetryPlan()
        assert plan.has_candidates is False

    def test_max_entity_retries_default(self):
        assert MAX_ENTITY_RETRIES == 2
