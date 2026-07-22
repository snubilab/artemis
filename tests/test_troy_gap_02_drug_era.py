"""
TROY Gap Closing - Subtask 02: DrugEra PrimaryCriteria support.

Tests that:
  A. Drug domain → PrimaryCriteria uses "DrugEra"
  B. Condition domain → PrimaryCriteria still uses "ConditionOccurrence"
  C. InclusionRule Drug → still uses "DrugExposure" (not DrugEra)
"""
import pytest
from src.agents.agent3.assembler import CohortAssembler
from src.agents.agent3.mappings import (
    DOMAIN_TO_CRITERIA_TYPE,
    DOMAIN_TO_PRIMARY_CRITERIA_TYPE,
)
from src.registry.models import RegisteredConceptSet, RegisteredConcept
from src.models.ir import (
    ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria,
    CohortOutcome, TemporalWindow,
)


class TestDomainMappings:
    """Verify separate mappings for PrimaryCriteria vs InclusionRules."""

    def test_primary_criteria_drug_is_drug_era(self):
        """PrimaryCriteria mapping: Drug → DrugEra."""
        assert DOMAIN_TO_PRIMARY_CRITERIA_TYPE["Drug"] == "DrugEra"

    def test_primary_criteria_condition_unchanged(self):
        """PrimaryCriteria mapping: Condition → ConditionOccurrence."""
        assert DOMAIN_TO_PRIMARY_CRITERIA_TYPE["Condition"] == "ConditionOccurrence"

    def test_inclusion_rule_drug_is_drug_exposure(self):
        """InclusionRule mapping: Drug → DrugExposure (not DrugEra)."""
        assert DOMAIN_TO_CRITERIA_TYPE["Drug"] == "DrugExposure"


# Helper: dummy comparator for ARTEMISRequest (required field)
_DUMMY_COMPARATOR = CohortDefinition(
    primary_criteria=PrimaryCriteria(domain="Drug", entity_text="Placebo")
)


class TestDrugEraPrimaryCriteria:
    """Integration: assembler produces DrugEra for Drug PrimaryCriteria."""

    @pytest.fixture
    def assembler(self):
        return CohortAssembler()

    @pytest.fixture
    def drug_concept_sets(self):
        return [
            RegisteredConceptSet(
                id=1,
                name="Liraglutide",
                source_entity_text="Liraglutide",
                concepts=[RegisteredConcept(
                    concept_id=1503297,
                    concept_name="liraglutide",
                    domain_id="Drug",
                    vocabulary_id="RxNorm",
                )],
            )
        ]

    @pytest.fixture
    def drug_ir(self):
        return ARTEMISRequest(
            target=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug",
                    entity_text="Liraglutide",
                    limit="First",
                ),
            ),
            comparator=_DUMMY_COMPARATOR,
            outcome=CohortOutcome(
                name="MACE",
                domain="Condition",
                entity_text="MACE",
                time_at_risk=TemporalWindow(start=0, end=365),
            ),
        )

    def test_assemble_drug_primary_uses_drug_era(self, assembler, drug_ir, drug_concept_sets):
        """Full assemble: Drug PrimaryCriteria → DrugEra key in CriteriaList."""
        result = assembler.assemble(drug_ir, drug_concept_sets)
        criteria_list = result.circe_json["PrimaryCriteria"]["CriteriaList"]
        assert len(criteria_list) == 1
        first_criteria = criteria_list[0]
        assert "DrugEra" in first_criteria, (
            f"Expected 'DrugEra' key but got: {list(first_criteria.keys())}"
        )

    def test_assemble_condition_primary_uses_condition_occurrence(self, assembler):
        """Condition PrimaryCriteria → ConditionOccurrence (not ConditionEra)."""
        ir = ARTEMISRequest(
            target=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Condition",
                    entity_text="T2DM",
                    limit="First",
                ),
            ),
            comparator=_DUMMY_COMPARATOR,
            outcome=CohortOutcome(
                name="MACE",
                domain="Condition",
                entity_text="MACE",
                time_at_risk=TemporalWindow(start=0, end=365),
            ),
        )
        cs = [
            RegisteredConceptSet(
                id=1,
                name="T2DM",
                source_entity_text="T2DM",
                concepts=[RegisteredConcept(
                    concept_id=201826,
                    concept_name="Type 2 diabetes mellitus",
                    domain_id="Condition",
                    vocabulary_id="SNOMED",
                )],
            )
        ]
        result = assembler.assemble(ir, cs)
        first_criteria = result.circe_json["PrimaryCriteria"]["CriteriaList"][0]
        assert "ConditionOccurrence" in first_criteria

    def test_inclusion_rule_drug_uses_drug_exposure(self, assembler, drug_concept_sets):
        """InclusionRule with Drug domain → DrugExposure (not DrugEra)."""
        ir = ARTEMISRequest(
            target=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Condition",
                    entity_text="T2DM",
                    limit="First",
                ),
                exclusion_rules=[
                    Criteria(
                        name="No GLP-1",
                        domain="Drug",
                        entity_text="Liraglutide",
                        logic_type="ABSENCE",
                        window=TemporalWindow(start=-90, end=0),
                    )
                ],
            ),
            comparator=_DUMMY_COMPARATOR,
            outcome=CohortOutcome(
                name="MACE",
                domain="Condition",
                entity_text="MACE",
                time_at_risk=TemporalWindow(start=0, end=365),
            ),
        )
        cs = [
            RegisteredConceptSet(
                id=1,
                name="T2DM",
                source_entity_text="T2DM",
                concepts=[RegisteredConcept(
                    concept_id=201826,
                    concept_name="Type 2 diabetes mellitus",
                    domain_id="Condition",
                    vocabulary_id="SNOMED",
                )],
            ),
        ] + drug_concept_sets

        result = assembler.assemble(ir, cs)

        # Check that exclusion rule criteria uses DrugExposure, not DrugEra
        for rule in result.circe_json.get("InclusionRules", []):
            if rule["name"] == "No GLP-1":
                criteria_list = rule["expression"]["CriteriaList"]
                for cl in criteria_list:
                    crit = cl["Criteria"]
                    # Should have DrugExposure key
                    assert "DrugExposure" in crit, (
                        f"InclusionRule Drug should use DrugExposure, got: {list(crit.keys())}"
                    )
