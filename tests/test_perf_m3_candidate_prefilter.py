"""
SPEC-PERF-001 M3: Candidate Pre-Filtering Before Critic — Tests.

Tests:
- Pre-filter caps candidates at AGENT2_MAX_CRITIC_CANDIDATES (default: 30)
- Seed concepts are never filtered out
- Relevance scoring priority: seed > child/sibling > ancestor_climb > 2-hop
- Env var override works
"""

import os
from unittest.mock import patch

import pytest

from src.agents.agent2.kg_expander import KGConcept


def _make_concepts(n: int, relationship: str = "descendant", start_id: int = 100) -> list[KGConcept]:
    """Helper to create a list of KGConcept objects."""
    return [
        KGConcept(
            concept_id=start_id + i,
            concept_name=f"Concept_{start_id + i}",
            domain_id="Condition",
            vocabulary_id="SNOMED",
            relationship=relationship,
        )
        for i in range(n)
    ]


class TestPreFilterDefault:
    """Verify default max critic candidates is 30."""

    def test_default_max_candidates(self):
        """Default AGENT2_MAX_CRITIC_CANDIDATES should be 30 for narrow queries (<= 40 candidates)."""
        os.environ.pop("AGENT2_MAX_CRITIC_CANDIDATES", None)
        from src.agents.agent2.workflow import _prefilter_candidates
        # With 40 candidates (not exceeding broad-query threshold), cap stays at 30
        seeds = [1, 2, 3]
        kg_concepts = _make_concepts(40, "descendant")
        result = _prefilter_candidates(seeds, kg_concepts)
        assert len(result) <= 30

    def test_broad_query_cap_increase(self):
        """Broad queries (> 40 KG candidates) get cap raised to 50 when using default."""
        os.environ.pop("AGENT2_MAX_CRITIC_CANDIDATES", None)
        from src.agents.agent2.workflow import _prefilter_candidates
        seeds = [1, 2, 3]
        kg_concepts = _make_concepts(60, "descendant")
        result = _prefilter_candidates(seeds, kg_concepts)
        # Cap raised to 50 for broad queries; should not exceed 50
        assert len(result) <= 50
        assert len(result) > 30  # broad heuristic fired


class TestPreFilterEnvOverride:
    """Verify AGENT2_MAX_CRITIC_CANDIDATES env var override."""

    def test_env_var_override(self):
        """Setting AGENT2_MAX_CRITIC_CANDIDATES should change the cap."""
        with patch.dict(os.environ, {"AGENT2_MAX_CRITIC_CANDIDATES": "10"}):
            from src.agents.agent2.workflow import _prefilter_candidates
            seeds = [1, 2, 3]
            kg_concepts = _make_concepts(50, "descendant")
            result = _prefilter_candidates(seeds, kg_concepts)
            assert len(result) <= 10


class TestPreFilterSeedPreservation:
    """Verify seed concepts are never filtered out."""

    def test_seeds_always_preserved(self):
        """Seed concepts must always appear in the filtered output."""
        from src.agents.agent2.workflow import _prefilter_candidates
        seeds = [1, 2, 3]
        # Create KG concepts that include seed IDs
        kg_concepts = [
            KGConcept(concept_id=1, concept_name="Seed1", domain_id="Condition",
                      vocabulary_id="SNOMED", relationship="seed"),
            KGConcept(concept_id=2, concept_name="Seed2", domain_id="Condition",
                      vocabulary_id="SNOMED", relationship="seed"),
            KGConcept(concept_id=3, concept_name="Seed3", domain_id="Condition",
                      vocabulary_id="SNOMED", relationship="seed"),
        ] + _make_concepts(50, "ancestor_climb (via Disease, IC=5.0)")

        with patch.dict(os.environ, {"AGENT2_MAX_CRITIC_CANDIDATES": "5"}):
            result = _prefilter_candidates(seeds, kg_concepts)
            result_ids = {c.concept_id for c in result}
            for sid in seeds:
                assert sid in result_ids, f"Seed {sid} was filtered out!"


class TestPreFilterRelevancePriority:
    """Verify relevance scoring priority."""

    def test_priority_order(self):
        """Priority: seed > sibling > ancestor_climb > 2-hop."""
        from src.agents.agent2.workflow import _prefilter_candidates
        seeds = [1]
        kg_concepts = [
            KGConcept(concept_id=1, concept_name="Seed", domain_id="Condition",
                      vocabulary_id="SNOMED", relationship="seed"),
            KGConcept(concept_id=10, concept_name="Sibling", domain_id="Condition",
                      vocabulary_id="SNOMED", relationship="sibling (parent: X)"),
            KGConcept(concept_id=20, concept_name="Climb", domain_id="Condition",
                      vocabulary_id="SNOMED", relationship="ancestor_climb (via Y, IC=10.0)"),
            KGConcept(concept_id=30, concept_name="TwoHop", domain_id="Condition",
                      vocabulary_id="SNOMED", relationship="2-hop (via parent: Z)"),
        ]

        with patch.dict(os.environ, {"AGENT2_MAX_CRITIC_CANDIDATES": "3"}):
            result = _prefilter_candidates(seeds, kg_concepts)
            result_ids = [c.concept_id for c in result]
            # Seed always first, then sibling, then ancestor_climb
            assert result_ids[0] == 1  # seed
            assert 10 in result_ids  # sibling kept
            # 2-hop should be dropped (lowest priority)
            if len(result_ids) == 3:
                assert 30 not in result_ids or 20 in result_ids


class TestPreFilterNoTruncation:
    """Verify no truncation when candidates are under limit."""

    def test_no_truncation_under_limit(self):
        """When candidates < limit, all should be returned."""
        from src.agents.agent2.workflow import _prefilter_candidates
        seeds = [1]
        kg_concepts = _make_concepts(5, "descendant")
        result = _prefilter_candidates(seeds, kg_concepts)
        assert len(result) == 5
