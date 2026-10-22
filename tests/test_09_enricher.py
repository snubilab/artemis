"""
Test 09: Agent 1 Multi-Source Merge (Subtask 03).
Tests that parse_nct can enrich TrialData with PubMed design paper criteria.
"""
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

    def test_should_keep_every_paper_criterion_when_its_wording_resembles_a_held_one(self):
        """
        Given: A held criterion and a paper criterion whose wording is close
        When:  enrich_trial_data merges the two sources
        Then:  Both survive, held first, each source in its own order

        PLATO's merge is the real event: the design paper's "Increased risk of
        bradycardiac events" scored 0.83 against the main paper's "an increased
        risk of bradycardia," and was dropped, while the same merge kept "Oral
        anticoagulation therapy that cannot be stopped" beside "a need for oral
        anticoagulation" (0.44). How alike two strings read decides nothing here;
        restatements are collapsed downstream on the extraction's own fields.
        """
        from src.agents.agent1.enricher import enrich_trial_data

        held = ["an increased risk of bradycardia,", "Dialysis required"]
        paper = ["Increased risk of bradycardiac events", "Pregnancy or lactation"]
        trial_data = TrialData(nct_id="NCT00391872", inclusion_criteria=[], exclusion_criteria=held)

        enriched = enrich_trial_data(
            trial_data, {"inclusion": [], "exclusion": paper}, strategy="merge"
        )

        assert enriched.exclusion_criteria == held + paper


class TestListedMembersSurviveEnrichment:
    """A criterion's listed members ride in it as its own tab-indented lines (section_rules S10).
    Every step between the section rules and the prompt must keep each member exactly once."""

    ENTRY = "High risk of CV events (I and/or II):\n\tAlbuminuria\n\t\tConfirmed history of MI"

    def test_should_keep_each_member_once_through_every_strategy_and_the_prompt_cleaning(self):
        from src.agents.agent1.enricher import enrich_trial_data
        from src.agents.agent1.parser import LogicDecomposer, _normalize_trial_data_for_stable_hash

        held = TrialData(nct_id="NCT01897532", title="CARMELINA",
                         inclusion_criteria=["Age >= 18", self.ENTRY], exclusion_criteria=[])
        pdf = {"inclusion": ["Age >= 18", self.ENTRY], "exclusion": []}
        for strategy in ("replace", "merge", "supplement_priority"):
            enriched = _normalize_trial_data_for_stable_hash(
                enrich_trial_data(held, pdf, strategy=strategy)
            )
            assert enriched.inclusion_criteria.count(self.ENTRY) == 1, strategy
            rendered = LogicDecomposer._format_criteria(enriched.inclusion_criteria).split("\n")
            assert rendered[-2:] == ["  2.1 Albuminuria", "  2.1.1 Confirmed history of MI"], strategy
