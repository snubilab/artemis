"""
TROY Gap Closing - Subtask 03: CustomEra EndStrategy.

Tests that:
  A. CustomEra EndStrategy → Circe CustomEra block
  B. Legacy str "OBSERVATION_END" → backward compatible (returns None)
  C. Legacy str "FIXED_DURATION" → backward compatible
  D. ExitStrategy(OBSERVATION_END) → returns None
  E. ExitStrategy(FIXED_DURATION) → DateOffset block
"""
import pytest
from src.agents.agent3.assembler import CohortAssembler
from src.models.ir import (
    CohortDefinition, PrimaryCriteria,
    ExitStrategy, CustomEraConfig,
)


class TestCustomEraEndStrategy:
    """Test _build_end_strategy for all strategy types."""

    @pytest.fixture
    def assembler(self):
        return CohortAssembler()

    def test_custom_era_generates_correct_block(self, assembler):
        """CustomEra → Circe CustomEra JSON block with DrugCodesetId, GapDays, Offset."""
        strategy = ExitStrategy(
            strategy_type="CUSTOM_ERA",
            custom_era=CustomEraConfig(
                drug_codeset_id=117,
                gap_days=30,
                offset=0,
            ),
        )
        result = assembler._build_end_strategy(strategy)
        assert result is not None
        assert "CustomEra" in result
        era = result["CustomEra"]
        assert era["DrugCodesetId"] == 117
        assert era["GapDays"] == 30
        assert era["Offset"] == 0

    def test_custom_era_custom_gap_days(self, assembler):
        """CustomEra with non-default GapDays."""
        strategy = ExitStrategy(
            strategy_type="CUSTOM_ERA",
            custom_era=CustomEraConfig(
                drug_codeset_id=5,
                gap_days=90,
                offset=7,
            ),
        )
        result = assembler._build_end_strategy(strategy)
        era = result["CustomEra"]
        assert era["GapDays"] == 90
        assert era["Offset"] == 7

    def test_exit_strategy_observation_end_returns_none(self, assembler):
        """ExitStrategy(OBSERVATION_END) → None (no EndStrategy in JSON)."""
        strategy = ExitStrategy(strategy_type="OBSERVATION_END")
        result = assembler._build_end_strategy(strategy)
        assert result is None

    def test_exit_strategy_fixed_duration(self, assembler):
        """ExitStrategy(FIXED_DURATION) → DateOffset block."""
        strategy = ExitStrategy(
            strategy_type="FIXED_DURATION",
            date_offset_days=180,
        )
        result = assembler._build_end_strategy(strategy)
        assert result is not None
        assert "DateOffset" in result
        assert result["DateOffset"]["Offset"] == 180

    def test_legacy_string_observation_end(self, assembler):
        """Legacy str 'OBSERVATION_END' → backward compat (None)."""
        result = assembler._build_end_strategy("OBSERVATION_END")
        assert result is None

    def test_legacy_string_fixed_duration(self, assembler):
        """Legacy str 'FIXED_DURATION' → backward compat (DateOffset)."""
        result = assembler._build_end_strategy("FIXED_DURATION")
        assert result is not None
        assert "DateOffset" in result

    def test_cohort_definition_accepts_exit_strategy_object(self):
        """CohortDefinition.exit_strategy accepts ExitStrategy model."""
        cd = CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="Liraglutide"),
            exit_strategy=ExitStrategy(
                strategy_type="CUSTOM_ERA",
                custom_era=CustomEraConfig(drug_codeset_id=0, gap_days=30),
            ),
        )
        assert isinstance(cd.exit_strategy, ExitStrategy)

    def test_cohort_definition_accepts_legacy_string(self):
        """CohortDefinition.exit_strategy still accepts plain str."""
        cd = CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="Liraglutide"),
            exit_strategy="OBSERVATION_END",
        )
        assert cd.exit_strategy == "OBSERVATION_END"
