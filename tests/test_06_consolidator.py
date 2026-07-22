"""
Test 06: Post-Mapping Consolidator.
Tests the ConceptSet consolidation logic that merges sibling concepts
into a common ancestor ConceptSet.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestConsolidatorLogic:
    """Test the core consolidation algorithm."""

    def test_find_common_ancestor_simple(self):
        """
        Given: 3 concept_ids that share a common ancestor
        When: Consolidator finds LCA
        Then: Returns the lowest common ancestor
        """
        from src.agents.consolidator.consolidator import ConceptSetConsolidator

        # Mock OntologySearch
        mock_ontology = MagicMock()
        # lung cancer (200) -> ancestors: [100(neoplasm), 50(clinical finding)]
        # breast cancer (201) -> ancestors: [100(neoplasm), 50(clinical finding)]
        # colon cancer (202) -> ancestors: [100(neoplasm), 50(clinical finding)]
        mock_ontology.get_ancestors.side_effect = lambda cid, max_levels=5: {
            200: [100, 50],
            201: [100, 50],
            202: [100, 50],
        }.get(cid, [])

        consolidator = ConceptSetConsolidator(ontology_search=mock_ontology)
        lca = consolidator.find_lowest_common_ancestor([200, 201, 202])
        assert lca == 100  # neoplasm, not clinical finding (too broad)

    def test_find_lca_no_common_ancestor(self):
        """
        Given: concept_ids with no common ancestor (different domains)
        When: Consolidator tries to find LCA
        Then: Returns None
        """
        from src.agents.consolidator.consolidator import ConceptSetConsolidator

        mock_ontology = MagicMock()
        mock_ontology.get_ancestors.side_effect = lambda cid, max_levels=5: {
            200: [100, 50],  # Condition hierarchy
            300: [250, 150], # Drug hierarchy (no overlap)
        }.get(cid, [])

        consolidator = ConceptSetConsolidator(ontology_search=mock_ontology)
        lca = consolidator.find_lowest_common_ancestor([200, 300])
        assert lca is None

    def test_consolidate_sibling_concepts(self):
        """
        Given: mapped_sets with sibling concepts from same parent rule
        When: Consolidator processes them
        Then: Siblings merged into 1 set with ancestor concept
        """
        from src.agents.consolidator.consolidator import ConceptSetConsolidator

        mock_ontology = MagicMock()
        mock_ontology.get_ancestors.side_effect = lambda cid, max_levels=5: {
            200: [100, 50],
            201: [100, 50],
            202: [100, 50],
        }.get(cid, [])

        # Mock concept name lookup
        mock_ontology.get_concept_name = MagicMock(return_value="Malignant neoplasm")

        consolidator = ConceptSetConsolidator(ontology_search=mock_ontology)

        mapped_sets = [
            {"id": 1, "name": "lung cancer", "domain": "Condition",
             "concept_ids": [200], "source": "target", "parent_rule": "malignant_neoplasm"},
            {"id": 2, "name": "breast cancer", "domain": "Condition",
             "concept_ids": [201], "source": "target", "parent_rule": "malignant_neoplasm"},
            {"id": 3, "name": "colon cancer", "domain": "Condition",
             "concept_ids": [202], "source": "target", "parent_rule": "malignant_neoplasm"},
        ]

        result = consolidator.consolidate(mapped_sets)
        # Should merge 3 into 1
        assert len(result) == 1
        assert result[0]["concept_ids"] == [100]
        assert result[0]["include_descendants"] is True

    def test_no_consolidation_for_unrelated(self):
        """
        Given: mapped_sets from different parent rules
        When: Consolidator processes them
        Then: Each set remains independent
        """
        from src.agents.consolidator.consolidator import ConceptSetConsolidator

        mock_ontology = MagicMock()
        consolidator = ConceptSetConsolidator(ontology_search=mock_ontology)

        mapped_sets = [
            {"id": 1, "name": "Type 2 Diabetes", "domain": "Condition",
             "concept_ids": [100], "source": "target", "parent_rule": "t2dm"},
            {"id": 2, "name": "HbA1c", "domain": "Measurement",
             "concept_ids": [200], "source": "target", "parent_rule": "hba1c"},
        ]

        result = consolidator.consolidate(mapped_sets)
        assert len(result) == 2  # No consolidation

    def test_mixed_consolidation(self):
        """
        Given: Some sets are siblings (same parent_rule), others are independent
        When: Consolidator processes them
        Then: Siblings merged, independents kept
        """
        from src.agents.consolidator.consolidator import ConceptSetConsolidator

        mock_ontology = MagicMock()
        mock_ontology.get_ancestors.side_effect = lambda cid, max_levels=5: {
            200: [100],
            201: [100],
        }.get(cid, [])
        mock_ontology.get_concept_name = MagicMock(return_value="Malignant neoplasm")

        consolidator = ConceptSetConsolidator(ontology_search=mock_ontology)

        mapped_sets = [
            {"id": 1, "name": "T2DM", "domain": "Condition",
             "concept_ids": [50], "source": "target", "parent_rule": "t2dm"},
            {"id": 2, "name": "lung cancer", "domain": "Condition",
             "concept_ids": [200], "source": "target", "parent_rule": "neoplasm"},
            {"id": 3, "name": "breast cancer", "domain": "Condition",
             "concept_ids": [201], "source": "target", "parent_rule": "neoplasm"},
        ]

        result = consolidator.consolidate(mapped_sets)
        assert len(result) == 2  # T2DM + merged neoplasm
