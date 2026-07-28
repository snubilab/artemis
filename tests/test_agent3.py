"""
Unit tests for Agent 3 (Cohort Assembler) - Phase 2.2.
"""
import pytest
from src.agents.agent3.assembler import CohortAssembler, AssemblyResult, HealAction
from src.agents.agent3.mappings import DOMAIN_TO_CRITERIA_TYPE, GENDER_MAP, OPERATOR_MAP
from src.registry.models import RegisteredConceptSet, RegisteredConcept
from src.services.value_constraint import build_measurement_value_filter
from src.models.ir import (
    ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria, 
    CohortOutcome, TemporalWindow, ValueConstraint
)


class TestMappings:
    """Test static mappings."""
    
    def test_domain_to_criteria_type(self):
        """Test domain mapping."""
        assert DOMAIN_TO_CRITERIA_TYPE["Condition"] == "ConditionOccurrence"
        assert DOMAIN_TO_CRITERIA_TYPE["Drug"] == "DrugExposure"
        assert DOMAIN_TO_CRITERIA_TYPE["Measurement"] == "Measurement"
    
    def test_gender_map(self):
        """Test gender mapping."""
        assert GENDER_MAP["MALE"] == 8507
        assert GENDER_MAP["FEMALE"] == 8532
    
    def test_operator_map(self):
        """Test operator mapping."""
        assert OPERATOR_MAP["gt"] == "gt"
        assert OPERATOR_MAP["lt"] == "lt"
        assert OPERATOR_MAP["eq"] == "eq"


class TestCohortAssembler:
    """Test CohortAssembler."""
    
    @pytest.fixture
    def sample_ir(self):
        """Create sample IR for testing."""
        return ARTEMISRequest(
            target=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug",
                    entity_text="Metformin",
                    limit="First"
                ),
                inclusion_rules=[
                    Criteria(
                        name="T2DM Diagnosis",
                        domain="Condition",
                        entity_text="Type 2 Diabetes",
                        logic_type="PRESENCE",
                        window=TemporalWindow(start=-365, end=0)
                    )
                ],
                exclusion_rules=[]
            ),
            comparator=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug",
                    entity_text="Placebo"
                )
            ),
            outcome=CohortOutcome(
                name="CV Death",
                domain="Condition",
                entity_text="Cardiovascular Death",
                time_at_risk=TemporalWindow(start=0, end=365)
            )
        )
    
    @pytest.fixture
    def sample_concept_sets(self):
        """Create sample ConceptSets."""
        return [
            RegisteredConceptSet(
                id=1,
                name="Metformin",
                source_entity_text="Metformin",
                concepts=[RegisteredConcept(
                    concept_id=21600381,
                    concept_name="Metformin",
                    domain_id="Drug",
                    vocabulary_id="RxNorm"
                )]
            ),
            RegisteredConceptSet(
                id=2,
                name="Type 2 Diabetes",
                source_entity_text="Type 2 Diabetes",
                concepts=[RegisteredConcept(
                    concept_id=201826,
                    concept_name="Type 2 diabetes mellitus",
                    domain_id="Condition",
                    vocabulary_id="SNOMED"
                )]
            )
        ]
    
    def test_assemble_produces_valid_structure(self, sample_ir, sample_concept_sets):
        """Test that assemble produces valid Circe structure."""
        assembler = CohortAssembler()
        result = assembler.assemble(sample_ir, sample_concept_sets)
        
        assert isinstance(result, AssemblyResult)
        # Check required top-level fields
        assert "ConceptSets" in result.circe_json
        assert "PrimaryCriteria" in result.circe_json
        assert "InclusionRules" in result.circe_json
    
    def test_assemble_concept_sets_format(self, sample_ir, sample_concept_sets):
        """Test ConceptSets are properly formatted."""
        assembler = CohortAssembler()
        result = assembler.assemble(sample_ir, sample_concept_sets)
        
        concept_sets = result.circe_json["ConceptSets"]
        assert len(concept_sets) == 2
        
        cs = concept_sets[0]
        assert "id" in cs
        assert "name" in cs
        assert "expression" in cs
        assert "items" in cs["expression"]
    
    def test_assemble_inclusion_rules(self, sample_ir, sample_concept_sets):
        """Test inclusion rules are properly built."""
        assembler = CohortAssembler()
        result = assembler.assemble(sample_ir, sample_concept_sets)
        
        inclusion_rules = result.circe_json["InclusionRules"]
        assert len(inclusion_rules) == 1
        
        rule = inclusion_rules[0]
        assert rule["name"] == "T2DM Diagnosis"
        assert "expression" in rule
    
    def test_build_value_constraint(self):
        """Value filters come from the shared module, with Unit as a sibling.

        This test previously asserted Value, Op and Unit on one dict, which only
        holds when Unit is nested inside ValueAsNumber — the shape Circe ignores,
        and the reason the unit filter never took effect. See ADR-031 D4.
        """
        fragment = build_measurement_value_filter(
            ValueConstraint(op="gt", value=7.0, unit_text="%")
        )

        assert fragment["ValueAsNumber"] == {"Value": 7.0, "Op": "gt"}
        assert fragment["Unit"][0]["CONCEPT_ID"] == 8554
        assert "Unit" not in fragment["ValueAsNumber"]

    def test_build_value_constraint_uln_uses_range_high_ratio(self):
        """"3x ULN" must not survive as the absolute number 3.

        Real ALT runs 10-40 U/L, so ValueAsNumber > 3 matches every patient with
        a liver panel; as an exclusion that empties the cohort.
        """
        fragment = build_measurement_value_filter(
            ValueConstraint(op="gt", value=3.0, reference_bound="uln")
        )

        assert fragment == {"RangeHighRatio": {"Value": 3.0, "Op": "gt"}}


    def test_assemble_reports_dropped_rules(self, sample_ir):
        """Test that rules with missing concepts are reported in heal_log."""
        # With empty concept_sets, all CodesetId will be 0
        empty_concept_sets = []
        
        assembler = CohortAssembler()
        result = assembler.assemble(sample_ir, empty_concept_sets)
        
        # heal_log should contain at least the T2DM rule as SKIP
        assert len(result.heal_log) > 0
        skipped = [h for h in result.heal_log if h.action == "SKIP"]
        assert len(skipped) >= 1
        assert any("T2DM" in h.rule_name for h in skipped)
        
        # InclusionRules should be empty (all rules dropped)
        assert len(result.circe_json["InclusionRules"]) == 0
        
        # has_failures should be True
        assert result.has_failures
    
    def test_assemble_all_valid_empty_heal_log(self, sample_ir, sample_concept_sets):
        """Test that successful assembly has no SKIP entries in heal_log."""
        assembler = CohortAssembler()
        result = assembler.assemble(sample_ir, sample_concept_sets)
        
        # No rules should be skipped
        assert not result.has_failures
        assert len(result.failed_entities) == 0
        
        # heal_log should have entries (KEEP), but none SKIP
        for h in result.heal_log:
            assert h.action in ("KEEP", "PARTIAL")
