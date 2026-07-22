"""
TDD Tests for Subtask 02: Drug domain PrimaryCriteria → DrugEra.
RED phase — Test A and B should FAIL before implementation.
"""
import pytest
from src.agents.agent3.assembler import CohortAssembler
from src.agents.agent3.mappings import DOMAIN_TO_CRITERIA_TYPE
from src.registry.models import RegisteredConceptSet, RegisteredConcept
from src.models.ir import (
    ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria,
    CohortOutcome, TemporalWindow
)


@pytest.fixture
def drug_primary_ir():
    """IR with Drug domain PrimaryCriteria (LEADER-like)."""
    return ARTEMISRequest(
        target=CohortDefinition(
            primary_criteria=PrimaryCriteria(
                domain="Drug",
                entity_text="liraglutide",
                limit="First"
            ),
            inclusion_rules=[
                Criteria(
                    name="No prior GLP-1RA",
                    domain="Drug",
                    entity_text="GLP-1 receptor agonists",
                    logic_type="ABSENCE",
                    window=TemporalWindow(start=-90, end=0)
                )
            ],
        ),
        comparator=CohortDefinition(
            primary_criteria=PrimaryCriteria(
                domain="Drug",
                entity_text="placebo"
            )
        ),
        outcome=CohortOutcome(
            name="MACE",
            domain="Condition",
            entity_text="MACE",
            time_at_risk=TemporalWindow(start=0, end=365)
        )
    )


@pytest.fixture
def condition_primary_ir():
    """IR with Condition domain PrimaryCriteria."""
    return ARTEMISRequest(
        target=CohortDefinition(
            primary_criteria=PrimaryCriteria(
                domain="Condition",
                entity_text="Type 2 diabetes mellitus",
                limit="First"
            ),
        ),
        comparator=CohortDefinition(
            primary_criteria=PrimaryCriteria(
                domain="Condition",
                entity_text="control"
            )
        ),
        outcome=CohortOutcome(
            name="outcome",
            domain="Condition",
            entity_text="outcome",
            time_at_risk=TemporalWindow(start=0, end=365)
        )
    )


@pytest.fixture
def sample_concept_sets():
    """Sample concept sets."""
    return [
        RegisteredConceptSet(
            id=1, name="liraglutide", source_entity_text="liraglutide",
            concepts=[RegisteredConcept(
                concept_id=1503297, concept_name="liraglutide",
                domain_id="Drug", vocabulary_id="RxNorm"
            )]
        ),
        RegisteredConceptSet(
            id=2, name="GLP-1 receptor agonists",
            source_entity_text="GLP-1 receptor agonists",
            concepts=[RegisteredConcept(
                concept_id=21600381, concept_name="GLP-1 receptor agonists",
                domain_id="Drug", vocabulary_id="RxNorm"
            )]
        ),
        RegisteredConceptSet(
            id=3, name="Type 2 diabetes mellitus",
            source_entity_text="Type 2 diabetes mellitus",
            concepts=[RegisteredConcept(
                concept_id=201826, concept_name="Type 2 diabetes mellitus",
                domain_id="Condition", vocabulary_id="SNOMED"
            )]
        ),
    ]


class TestDrugEraPrimaryCriteria:
    """Drug domain PrimaryCriteria should use DrugEra, not DrugExposure."""

    def test_drug_primary_uses_drug_era(self, drug_primary_ir, sample_concept_sets):
        """PrimaryCriteria with Drug domain must output DrugEra key."""
        assembler = CohortAssembler()
        result = assembler.assemble(drug_primary_ir, sample_concept_sets)

        criteria_list = result.circe_json["PrimaryCriteria"]["CriteriaList"]
        assert len(criteria_list) == 1

        criteria_keys = list(criteria_list[0].keys())
        assert "DrugEra" in criteria_keys, (
            f"Expected 'DrugEra' in PrimaryCriteria, got keys: {criteria_keys}"
        )
        assert "DrugExposure" not in criteria_keys, (
            "DrugExposure should NOT be in PrimaryCriteria for Drug domain"
        )

    def test_condition_primary_still_uses_condition_occurrence(
        self, condition_primary_ir, sample_concept_sets
    ):
        """Condition domain PrimaryCriteria should still use ConditionOccurrence."""
        assembler = CohortAssembler()
        result = assembler.assemble(condition_primary_ir, sample_concept_sets)

        criteria_list = result.circe_json["PrimaryCriteria"]["CriteriaList"]
        criteria_keys = list(criteria_list[0].keys())
        assert "ConditionOccurrence" in criteria_keys

    def test_drug_inclusion_rule_still_uses_drug_exposure(
        self, drug_primary_ir, sample_concept_sets
    ):
        """Drug InclusionRule should still use DrugExposure (not DrugEra)."""
        assembler = CohortAssembler()
        result = assembler.assemble(drug_primary_ir, sample_concept_sets)

        inclusion_rules = result.circe_json["InclusionRules"]
        assert len(inclusion_rules) >= 1

        # Check the drug-based inclusion rule
        drug_rule = inclusion_rules[0]
        criteria = drug_rule["expression"]["CriteriaList"][0]["Criteria"]
        criteria_keys = list(criteria.keys())

        assert "DrugExposure" in criteria_keys, (
            f"Drug InclusionRule should use DrugExposure, got: {criteria_keys}"
        )

    def test_existing_domain_mapping_unchanged(self):
        """Original DOMAIN_TO_CRITERIA_TYPE should remain unchanged."""
        assert DOMAIN_TO_CRITERIA_TYPE["Drug"] == "DrugExposure"
        assert DOMAIN_TO_CRITERIA_TYPE["Condition"] == "ConditionOccurrence"
