"""
TDD Tests for Subtask 01: includeDescendants & includeMapped defaults.
RED phase — these tests should FAIL before implementation.
"""
import pytest
from src.registry.models import RegisteredConcept, RegisteredConceptSet
from src.agents.agent3.assembler import CohortAssembler
from src.models.ir import (
    ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria,
    CohortOutcome, TemporalWindow
)


class TestIncludeDescendantsDefault:
    """Test that RegisteredConcept defaults to include_descendants=True."""

    def test_registered_concept_default_include_descendants(self):
        """RegisteredConcept should default to include_descendants=True."""
        concept = RegisteredConcept(
            concept_id=1503297,
            concept_name="liraglutide",
            domain_id="Drug",
            vocabulary_id="RxNorm"
        )
        assert concept.include_descendants is True, (
            f"Expected include_descendants=True, got {concept.include_descendants}"
        )

    def test_registered_concept_explicit_false_still_works(self):
        """Explicitly setting include_descendants=False should still work."""
        concept = RegisteredConcept(
            concept_id=1503297,
            concept_name="liraglutide",
            domain_id="Drug",
            vocabulary_id="RxNorm",
            include_descendants=False
        )
        assert concept.include_descendants is False


class TestIncludeMappedInCirce:
    """Test that assembled Circe JSON includes includeMapped=True."""

    @pytest.fixture
    def assembler_with_data(self):
        """Create assembler with sample LEADER-like data."""
        ir = ARTEMISRequest(
            target=CohortDefinition(
                primary_criteria=PrimaryCriteria(
                    domain="Drug",
                    entity_text="liraglutide",
                    limit="First"
                ),
                inclusion_rules=[
                    Criteria(
                        name="Type 2 diabetes",
                        domain="Condition",
                        entity_text="Type 2 Diabetes",
                        logic_type="PRESENCE",
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
        concept_sets = [
            RegisteredConceptSet(
                id=1,
                name="liraglutide",
                source_entity_text="liraglutide",
                concepts=[RegisteredConcept(
                    concept_id=1503297,
                    concept_name="liraglutide",
                    domain_id="Drug",
                    vocabulary_id="RxNorm",
                    include_descendants=True  # Now default
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
                    vocabulary_id="SNOMED",
                    include_descendants=True
                )]
            )
        ]
        return CohortAssembler(), ir, concept_sets

    def test_include_mapped_is_true_in_circe(self, assembler_with_data):
        """includeMapped should be True in assembled Circe JSON."""
        assembler, ir, concept_sets = assembler_with_data
        result = assembler.assemble(ir, concept_sets)

        for cs in result.circe_json["ConceptSets"]:
            for item in cs["expression"]["items"]:
                assert item["includeMapped"] is True, (
                    f"Expected includeMapped=True for {cs['name']}, "
                    f"got {item['includeMapped']}"
                )

    def test_include_descendants_is_true_in_circe(self, assembler_with_data):
        """includeDescendants should be True in assembled Circe JSON (when concept has it)."""
        assembler, ir, concept_sets = assembler_with_data
        result = assembler.assemble(ir, concept_sets)

        for cs in result.circe_json["ConceptSets"]:
            for item in cs["expression"]["items"]:
                assert item["includeDescendants"] is True, (
                    f"Expected includeDescendants=True for {cs['name']}, "
                    f"got {item['includeDescendants']}"
                )
