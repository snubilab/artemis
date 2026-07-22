"""
TDD Tests for Subtask 03: CustomEra EndStrategy.
RED phase — Test A should FAIL before implementation.
"""
import pytest
from src.agents.agent3.assembler import CohortAssembler
from src.registry.models import RegisteredConceptSet, RegisteredConcept
from src.models.ir import (
    ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria,
    CohortOutcome, TemporalWindow
)


@pytest.fixture
def concept_sets_with_drug():
    """Concept sets including a drug codeset for CustomEra."""
    return [
        RegisteredConceptSet(
            id=0, name="liraglutide", source_entity_text="liraglutide",
            concepts=[RegisteredConcept(
                concept_id=1503297, concept_name="liraglutide",
                domain_id="Drug", vocabulary_id="RxNorm"
            )]
        ),
        RegisteredConceptSet(
            id=117, name="liraglutide (all forms)",
            source_entity_text="liraglutide (all forms)",
            concepts=[RegisteredConcept(
                concept_id=1503297, concept_name="liraglutide",
                domain_id="Drug", vocabulary_id="RxNorm"
            )]
        ),
    ]


class TestCustomEraEndStrategy:
    """Test CustomEra EndStrategy in Circe JSON output."""

    def test_custom_era_end_strategy_output(self, concept_sets_with_drug):
        """CustomEra exit_strategy should produce the correct Circe JSON block."""
        # Import the new model (will fail before implementation)
        from src.models.ir import ExitStrategy, CustomEraConfig

        ir = ARTEMISRequest(
            target=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug",
                    entity_text="liraglutide",
                    limit="First"
                ),
                exit_strategy=ExitStrategy(
                    strategy_type="CUSTOM_ERA",
                    custom_era=CustomEraConfig(
                        drug_codeset_id=117,
                        gap_days=30,
                        offset=0
                    )
                )
            ),
            comparator=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug", entity_text="placebo"
                )
            ),
            outcome=CohortOutcome(
                name="MACE", domain="Condition", entity_text="MACE",
                time_at_risk=TemporalWindow(start=0, end=365)
            )
        )

        assembler = CohortAssembler()
        result = assembler.assemble(ir, concept_sets_with_drug)

        end_strategy = result.circe_json["EndStrategy"]
        assert end_strategy is not None, "EndStrategy should not be None for CUSTOM_ERA"
        assert "CustomEra" in end_strategy, (
            f"Expected 'CustomEra' key, got: {list(end_strategy.keys())}"
        )
        assert end_strategy["CustomEra"]["DrugCodesetId"] == 117
        assert end_strategy["CustomEra"]["GapDays"] == 30
        assert end_strategy["CustomEra"]["Offset"] == 0

    def test_observation_end_backward_compat(self, concept_sets_with_drug):
        """String 'OBSERVATION_END' should still work (backward compat)."""
        ir = ARTEMISRequest(
            target=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug", entity_text="liraglutide", limit="First"
                ),
                exit_strategy="OBSERVATION_END"
            ),
            comparator=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug", entity_text="placebo"
                )
            ),
            outcome=CohortOutcome(
                name="MACE", domain="Condition", entity_text="MACE",
                time_at_risk=TemporalWindow(start=0, end=365)
            )
        )

        assembler = CohortAssembler()
        result = assembler.assemble(ir, concept_sets_with_drug)
        assert result.circe_json["EndStrategy"] is None

    def test_fixed_duration_backward_compat(self, concept_sets_with_drug):
        """String 'FIXED_DURATION' should still work (backward compat)."""
        ir = ARTEMISRequest(
            target=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug", entity_text="liraglutide", limit="First"
                ),
                exit_strategy="FIXED_DURATION"
            ),
            comparator=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug", entity_text="placebo"
                )
            ),
            outcome=CohortOutcome(
                name="MACE", domain="Condition", entity_text="MACE",
                time_at_risk=TemporalWindow(start=0, end=365)
            )
        )

        assembler = CohortAssembler()
        result = assembler.assemble(ir, concept_sets_with_drug)
        assert result.circe_json["EndStrategy"] is not None
        assert "DateOffset" in result.circe_json["EndStrategy"]

    def test_exit_strategy_model_creation(self):
        """ExitStrategy model should be creatable with all strategy types."""
        from src.models.ir import ExitStrategy, CustomEraConfig

        # OBSERVATION_END
        es1 = ExitStrategy(strategy_type="OBSERVATION_END")
        assert es1.strategy_type == "OBSERVATION_END"
        assert es1.custom_era is None

        # FIXED_DURATION
        es2 = ExitStrategy(strategy_type="FIXED_DURATION", date_offset_days=365)
        assert es2.date_offset_days == 365

        # CUSTOM_ERA
        es3 = ExitStrategy(
            strategy_type="CUSTOM_ERA",
            custom_era=CustomEraConfig(drug_codeset_id=117, gap_days=30)
        )
        assert es3.custom_era.drug_codeset_id == 117
        assert es3.custom_era.gap_days == 30
