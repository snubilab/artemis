"""
TDD Tests for Agent 3: grouped criteria with sub_criteria → Type: "ANY".
RED phase — tests should FAIL before assembler modification.
"""
import pytest
from src.agents.agent3.assembler import CohortAssembler
from src.registry.models import RegisteredConceptSet, RegisteredConcept
from src.models.ir import (
    ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria,
    CohortOutcome, TemporalWindow
)


@pytest.fixture
def composite_ir():
    """IR with a composite inclusion rule (CV disease → fan-out)."""
    return ARTEMISRequest(
        target=CohortDefinition(
            primary_criteria=PrimaryCriteria(
                domain="Drug", entity_text="liraglutide", limit="First"
            ),
            inclusion_rules=[
                Criteria(
                    name="Established CV Disease",
                    domain="Condition",
                    entity_text="cardiovascular disease",
                    logic_type="PRESENCE",
                    group_type="ANY",
                    sub_criteria=[
                        Criteria(name="MI", domain="Condition", entity_text="Myocardial Infarction"),
                        Criteria(name="Stroke", domain="Condition", entity_text="Stroke"),
                        Criteria(name="CAD", domain="Condition", entity_text="Coronary artery disease"),
                    ]
                ),
                # Atomic rule (no sub_criteria)
                Criteria(
                    name="T2DM",
                    domain="Condition",
                    entity_text="Type 2 Diabetes",
                    logic_type="PRESENCE",
                ),
            ],
        ),
        comparator=CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="placebo")
        ),
        outcome=CohortOutcome(
            name="MACE", domain="Condition", entity_text="MACE",
            time_at_risk=TemporalWindow(start=0, end=365)
        )
    )


@pytest.fixture
def concept_sets_for_composite():
    """Concept sets matching the composite IR."""
    return [
        RegisteredConceptSet(
            id=1, name="liraglutide", source_entity_text="liraglutide",
            concepts=[RegisteredConcept(concept_id=1503297, concept_name="liraglutide",
                                        domain_id="Drug", vocabulary_id="RxNorm")]
        ),
        RegisteredConceptSet(
            id=2, name="Myocardial Infarction", source_entity_text="Myocardial Infarction",
            concepts=[RegisteredConcept(concept_id=4329847, concept_name="Myocardial infarction",
                                        domain_id="Condition", vocabulary_id="SNOMED")]
        ),
        RegisteredConceptSet(
            id=3, name="Stroke", source_entity_text="Stroke",
            concepts=[RegisteredConcept(concept_id=381591, concept_name="Cerebrovascular disease",
                                        domain_id="Condition", vocabulary_id="SNOMED")]
        ),
        RegisteredConceptSet(
            id=4, name="Coronary artery disease", source_entity_text="Coronary artery disease",
            concepts=[RegisteredConcept(concept_id=317576, concept_name="Coronary arteriosclerosis",
                                        domain_id="Condition", vocabulary_id="SNOMED")]
        ),
        RegisteredConceptSet(
            id=5, name="Type 2 Diabetes", source_entity_text="Type 2 Diabetes",
            concepts=[RegisteredConcept(concept_id=201826, concept_name="Type 2 diabetes mellitus",
                                        domain_id="Condition", vocabulary_id="SNOMED")]
        ),
    ]


class TestGroupedCriteriaAssembly:
    """Test Agent 3 assembles grouped criteria with Type: ANY."""

    def test_composite_rule_produces_type_any(self, composite_ir, concept_sets_for_composite):
        """Composite criteria with group_type='ANY' should produce Type: 'ANY' in Circe."""
        assembler = CohortAssembler()
        result = assembler.assemble(composite_ir, concept_sets_for_composite)

        inclusion_rules = result.circe_json["InclusionRules"]
        # First rule is composite (CV Disease)
        cv_rule = inclusion_rules[0]
        assert cv_rule["name"] == "Established CV Disease"
        assert cv_rule["expression"]["Type"] == "ANY", (
            f"Expected Type='ANY', got '{cv_rule['expression']['Type']}'"
        )

    def test_composite_rule_has_multiple_criteria(self, composite_ir, concept_sets_for_composite):
        """Composite rule should have 3 CriteriaList entries (MI, Stroke, CAD)."""
        assembler = CohortAssembler()
        result = assembler.assemble(composite_ir, concept_sets_for_composite)

        cv_rule = result.circe_json["InclusionRules"][0]
        criteria_list = cv_rule["expression"]["CriteriaList"]
        assert len(criteria_list) == 3, (
            f"Expected 3 criteria (MI, Stroke, CAD), got {len(criteria_list)}"
        )

    def test_atomic_rule_still_works(self, composite_ir, concept_sets_for_composite):
        """Atomic criteria (no sub_criteria) should still produce Type: 'ALL'."""
        assembler = CohortAssembler()
        result = assembler.assemble(composite_ir, concept_sets_for_composite)

        # Second rule is atomic (T2DM)
        t2dm_rule = result.circe_json["InclusionRules"][1]
        assert t2dm_rule["name"] == "T2DM"
        assert t2dm_rule["expression"]["Type"] == "ALL"
        assert len(t2dm_rule["expression"]["CriteriaList"]) == 1

    def test_each_sub_criterion_has_correct_codeset_id(self, composite_ir, concept_sets_for_composite):
        """Each sub-criterion should reference the correct CodesetId."""
        assembler = CohortAssembler()
        result = assembler.assemble(composite_ir, concept_sets_for_composite)

        cv_rule = result.circe_json["InclusionRules"][0]
        criteria_list = cv_rule["expression"]["CriteriaList"]

        # MI → concept_set id 2
        mi_criteria = criteria_list[0]["Criteria"]
        assert "ConditionOccurrence" in mi_criteria
        assert mi_criteria["ConditionOccurrence"]["CodesetId"] == 2

        # Stroke → concept_set id 3
        stroke_criteria = criteria_list[1]["Criteria"]
        assert stroke_criteria["ConditionOccurrence"]["CodesetId"] == 3
