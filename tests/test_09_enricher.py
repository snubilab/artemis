"""
Test 09: Agent 1 Multi-Source Merge (Subtask 03).
Tests that parse_nct can enrich TrialData with PubMed design paper criteria.
"""
import pytest
from unittest.mock import patch, MagicMock

from src.agents.agent1.nct_fetcher import TrialData


class TestTrialDataEnrichment:
    """Tests for TrialData enrichment from PubMed."""

    def test_enrich_trial_data_replaces_when_richer(self):
        """
        Given: TrialData with 3 inclusion criteria + PubMed paper with 8
        When:  enrich_trial_data is called
        Then:  Replaces with richer (PubMed) criteria
        """
        from src.agents.agent1.enricher import enrich_trial_data

        trial_data = TrialData(
            nct_id="NCT01179048",
            title="LEADER",
            inclusion_criteria=[
                "Adults with type 2 diabetes",
                "HbA1c >= 7.0%",
                "Age >= 50 years",
            ],
            exclusion_criteria=[
                "Type 1 diabetes",
            ],
        )

        pubmed_criteria = {
            "inclusion": [
                "Adults with type 2 diabetes",
                "HbA1c >= 7.0%",
                "Age >= 50 years with cardiovascular disease",
                "Age >= 50 with cerebrovascular disease",
                "Age >= 50 with peripheral vascular disease",
                "Chronic heart failure NYHA II-III",
                "Chronic kidney disease stage >= 3",
                "Age >= 60 with cardiovascular risk factor",
            ],
            "exclusion": [
                "Type 1 diabetes",
                "GLP-1 receptor agonist use within 90 days",
                "Acute coronary event within 14 days",
                "Planned revascularization",
                "Medullary thyroid carcinoma",
                "Malignant neoplasm requiring treatment in last 5 years",
            ],
        }

        enriched = enrich_trial_data(trial_data, pubmed_criteria)

        # PubMed had more criteria → should replace
        assert len(enriched.inclusion_criteria) == 8
        assert len(enriched.exclusion_criteria) == 6
        # Original NCT_ID preserved
        assert enriched.nct_id == "NCT01179048"

    def test_enrich_trial_data_keeps_nct_when_richer(self):
        """
        Given: TrialData with 10 criteria + PubMed paper with 3
        When:  enrich_trial_data is called
        Then:  Keeps original (richer) NCT criteria
        """
        from src.agents.agent1.enricher import enrich_trial_data

        trial_data = TrialData(
            nct_id="NCT01179048",
            inclusion_criteria=[f"Criteria {i}" for i in range(10)],
            exclusion_criteria=[f"Exclusion {i}" for i in range(5)],
        )

        pubmed_criteria = {
            "inclusion": ["Only one item"],
            "exclusion": [],
        }

        enriched = enrich_trial_data(trial_data, pubmed_criteria)

        # NCT had more → keep NCT
        assert len(enriched.inclusion_criteria) == 10
        assert len(enriched.exclusion_criteria) == 5

    def test_enrich_merges_unique_criteria(self):
        """
        Given: Some criteria overlap between NCT and PubMed
        When:  enrich_trial_data is called with merge mode
        Then:  Combines unique criteria from both sources
        """
        from src.agents.agent1.enricher import enrich_trial_data

        trial_data = TrialData(
            nct_id="NCT01179048",
            inclusion_criteria=["Type 2 diabetes", "HbA1c >= 7.0%"],
            exclusion_criteria=["Type 1 diabetes"],
        )

        pubmed_criteria = {
            "inclusion": ["Type 2 diabetes", "Age >= 50 with CVD"],
            "exclusion": ["Type 1 diabetes", "GLP-1 use within 90 days"],
        }

        enriched = enrich_trial_data(
            trial_data, pubmed_criteria, strategy="merge"
        )

        # Merged: 2 NCT + 1 unique from PubMed = 3
        assert len(enriched.inclusion_criteria) >= 3
        # Both sources' exclusions
        assert len(enriched.exclusion_criteria) >= 2
