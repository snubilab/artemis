"""
SPEC-PERF-001 M2: KG Expansion Breadth Limit — Tests for ancestor_climb limit reduction.

Tests:
- Default climb limit is 40 (configurable via AGENT2_KG_CLIMB_LIMIT)
- When results exceed limit, they are sorted by IC descending and truncated
- IC formula: IC(c) = -log2(descendants(c) / TOTAL_STANDARD_CONCEPTS)
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from src.agents.agent2.kg_expander import KGExpander, KGConcept, TOTAL_STANDARD_CONCEPTS


class TestKGClimbLimitDefault:
    """Verify default climb limit is 40."""

    def test_default_limit_is_40(self):
        """ancestor_climb default limit should be 40."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT2_KG_CLIMB_LIMIT", None)
            import src.agents.agent2.kg_expander as mod
            import importlib
            mod = importlib.reload(mod)
            assert mod.DEFAULT_KG_CLIMB_LIMIT == 40


class TestKGClimbLimitEnvOverride:
    """Verify AGENT2_KG_CLIMB_LIMIT env var overrides the default."""

    def test_env_var_override(self):
        """Setting AGENT2_KG_CLIMB_LIMIT should change DEFAULT_KG_CLIMB_LIMIT."""
        with patch.dict(os.environ, {"AGENT2_KG_CLIMB_LIMIT": "60"}):
            import src.agents.agent2.kg_expander as mod
            import importlib
            mod = importlib.reload(mod)
            assert mod.DEFAULT_KG_CLIMB_LIMIT == 60


class TestICBasedTruncation:
    """Verify IC-based sorting and truncation when results exceed limit."""

    def test_compute_ic_leaf_node(self):
        """Leaf node (0 descendants) should have maximum IC (20.0)."""
        ic = KGExpander.compute_ic(0)
        assert ic == 20.0

    def test_compute_ic_moderate_concept(self):
        """Concept with 100 descendants should have IC around 14.7."""
        ic = KGExpander.compute_ic(100)
        assert 14.0 < ic < 16.0

    def test_compute_ic_broad_concept(self):
        """Concept with 100,000 descendants should have low IC."""
        ic = KGExpander.compute_ic(100_000)
        assert ic < 6.0

    def test_truncation_sorts_by_ic_descending(self):
        """When results > limit, more specific concepts (higher IC) should be kept."""
        concepts = [
            KGConcept(concept_id=1, concept_name="Broad", domain_id="Condition",
                      vocabulary_id="SNOMED", descendant_count=50000),
            KGConcept(concept_id=2, concept_name="Specific", domain_id="Condition",
                      vocabulary_id="SNOMED", descendant_count=10),
            KGConcept(concept_id=3, concept_name="Medium", domain_id="Condition",
                      vocabulary_id="SNOMED", descendant_count=500),
        ]
        # With limit=2, should keep the 2 most specific (lowest descendant_count)
        from src.agents.agent2.kg_expander import _truncate_by_ic
        result = _truncate_by_ic(concepts, limit=2)
        assert len(result) == 2
        result_ids = [c.concept_id for c in result]
        # Concept 2 (IC highest) and Concept 3 (IC second-highest) should be kept
        assert 2 in result_ids
        assert 3 in result_ids

    def test_no_truncation_when_under_limit(self):
        """When results <= limit, no truncation should occur."""
        concepts = [
            KGConcept(concept_id=1, concept_name="A", domain_id="Condition",
                      vocabulary_id="SNOMED", descendant_count=100),
            KGConcept(concept_id=2, concept_name="B", domain_id="Condition",
                      vocabulary_id="SNOMED", descendant_count=200),
        ]
        from src.agents.agent2.kg_expander import _truncate_by_ic
        result = _truncate_by_ic(concepts, limit=5)
        assert len(result) == 2
