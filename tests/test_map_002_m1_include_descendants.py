"""
Tests for SPEC-MAP-002 M1: data-driven includeDescendants in ConceptSetRefiner.

Validates that the refiner uses concept_ancestor descendant counts to decide
whether to set includeDescendants=True or False for ancestor/climb concepts,
instead of blanket False.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from src.agents.agent2.concept_set_refiner import ConceptSetRefiner


@pytest.fixture
def refiner():
    return ConceptSetRefiner()


class TestShouldIncludeDescendants:
    """Test _should_include_descendants data-driven decision."""

    def test_ancestor_with_moderate_descendants_returns_true(self, refiner):
        """Ancestor with 500 descendants (1 < 500 < 50000) -> include."""
        with patch.object(refiner, "_get_single_descendant_count", return_value=500):
            assert refiner._should_include_descendants(12345, "Condition") is True

    def test_ancestor_with_zero_descendants_returns_false(self, refiner):
        """Ancestor with 0 descendants -> do not include."""
        with patch.object(refiner, "_get_single_descendant_count", return_value=0):
            assert refiner._should_include_descendants(12345, "Condition") is False

    def test_ancestor_with_one_descendant_returns_false(self, refiner):
        """Ancestor with exactly 1 descendant (not > 1) -> do not include."""
        with patch.object(refiner, "_get_single_descendant_count", return_value=1):
            assert refiner._should_include_descendants(12345, "Condition") is False

    def test_ancestor_with_too_many_descendants_returns_false(self, refiner):
        """Ancestor with 60000 descendants (>= 50000) -> too broad."""
        with patch.object(refiner, "_get_single_descendant_count", return_value=60000):
            assert refiner._should_include_descendants(12345, "Condition") is False

    def test_drug_domain_always_true(self, refiner):
        """Drug domain always includes descendants regardless of count."""
        # Should not even query DB
        assert refiner._should_include_descendants(12345, "Drug") is True

    def test_db_failure_defaults_true_for_condition(self, refiner):
        """When DB query fails (returns None), Condition defaults to True."""
        with patch.object(refiner, "_get_single_descendant_count", return_value=None):
            assert refiner._should_include_descendants(12345, "Condition") is True

    def test_db_failure_defaults_false_for_procedure(self, refiner):
        """When DB query fails, non-Condition/non-Drug defaults to False."""
        with patch.object(refiner, "_get_single_descendant_count", return_value=None):
            assert refiner._should_include_descendants(12345, "Procedure") is False

    def test_env_var_false_reverts_to_old_behavior(self, refiner):
        """When AGENT2_INCLUDE_DESCENDANTS_AUTO=false, always return False."""
        with patch.dict(os.environ, {"AGENT2_INCLUDE_DESCENDANTS_AUTO": "false"}):
            # Even with moderate descendants, should return False
            with patch.object(refiner, "_get_single_descendant_count", return_value=500):
                assert refiner._should_include_descendants(12345, "Condition") is False

    def test_env_var_true_uses_data_driven(self, refiner):
        """When AGENT2_INCLUDE_DESCENDANTS_AUTO=true (default), uses data-driven."""
        with patch.dict(os.environ, {"AGENT2_INCLUDE_DESCENDANTS_AUTO": "true"}):
            with patch.object(refiner, "_get_single_descendant_count", return_value=500):
                assert refiner._should_include_descendants(12345, "Condition") is True


class TestGetSingleDescendantCount:
    """Test _get_single_descendant_count database query."""

    def test_returns_count_on_success(self, refiner):
        """Should return integer count from concept_ancestor."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (500,)
        mock_conn.cursor.return_value = mock_cur

        with patch.object(refiner, "_get_db_connection", return_value=mock_conn), \
             patch.object(refiner, "_get_schema", return_value="cdm"):
            count = refiner._get_single_descendant_count(12345)

        assert count == 500
        mock_cur.execute.assert_called_once()
        assert "concept_ancestor" in mock_cur.execute.call_args[0][0]
        mock_conn.close.assert_called_once()

    def test_returns_none_on_db_failure(self, refiner):
        """Should return None when database query fails."""
        with patch.object(refiner, "_get_db_connection", side_effect=Exception("DB down")):
            count = refiner._get_single_descendant_count(12345)

        assert count is None


class TestRefineWithDataDrivenDescendants:
    """Integration-level tests for the refine() method with data-driven descendant logic."""

    def _make_kg_concept(self, concept_id, relationship="sibling", domain_id="Condition"):
        """Create a mock KGConcept."""
        mock = MagicMock()
        mock.concept_id = concept_id
        mock.relationship = relationship
        mock.descendant_count = 0
        mock.concept_name = f"Concept {concept_id}"
        mock.domain_id = domain_id
        mock.vocabulary_id = "SNOMED"
        return mock

    def test_ancestor_with_moderate_desc_not_overbroad(self, refiner):
        """Ancestor with moderate descendants should NOT be in overbroad_ids."""
        seed_ids = [100]
        kg = [
            self._make_kg_concept(100, relationship="seed"),
            self._make_kg_concept(200, relationship="ancestor"),
        ]

        with patch.object(refiner, "_find_subsumed_ancestors", return_value=set()), \
             patch.object(refiner, "_should_include_descendants", return_value=True):
            result = refiner.refine(seed_ids, kg, "CV disease", domain_hint="Condition")

        assert 200 not in result.overbroad_ids
        assert 200 in result.kept_ids

    def test_ancestor_with_huge_desc_is_overbroad(self, refiner):
        """Ancestor with too many descendants should be in overbroad_ids."""
        seed_ids = [100]
        kg = [
            self._make_kg_concept(100, relationship="seed"),
            self._make_kg_concept(200, relationship="ancestor"),
        ]

        with patch.object(refiner, "_find_subsumed_ancestors", return_value=set()), \
             patch.object(refiner, "_should_include_descendants", return_value=False):
            result = refiner.refine(seed_ids, kg, "CV disease", domain_hint="Condition")

        assert 200 in result.overbroad_ids
