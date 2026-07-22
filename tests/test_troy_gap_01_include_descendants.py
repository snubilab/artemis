"""
TROY Gap Closing - Subtask 01: includeDescendants & includeMapped defaults.

Tests that:
  A. RegisteredConcept defaults to include_descendants=True
  B. CohortAssembler._build_concept_sets outputs includeMapped=True
  C. Full Circe JSON has includeDescendants=True for all items
"""
import pytest
from src.registry.models import RegisteredConcept, RegisteredConceptSet
from src.agents.agent3.assembler import CohortAssembler


class TestIncludeDescendantsDefaults:
    """Test A: RegisteredConcept default values."""

    def test_include_descendants_default_true(self):
        """include_descendants should default to True."""
        concept = RegisteredConcept(
            concept_id=201826,
            concept_name="Type 2 diabetes mellitus",
            domain_id="Condition",
            vocabulary_id="SNOMED",
        )
        assert concept.include_descendants is True

    def test_include_descendants_explicit_false(self):
        """Explicit False should still be respected."""
        concept = RegisteredConcept(
            concept_id=201826,
            concept_name="Type 2 diabetes mellitus",
            domain_id="Condition",
            vocabulary_id="SNOMED",
            include_descendants=False,
        )
        assert concept.include_descendants is False


class TestIncludeMappedInConceptSets:
    """Test B & C: Circe ConceptSet items have correct flags."""

    @pytest.fixture
    def assembler(self):
        return CohortAssembler()

    @pytest.fixture
    def sample_concept_sets(self):
        return [
            RegisteredConceptSet(
                id=1,
                name="Liraglutide",
                concepts=[
                    RegisteredConcept(
                        concept_id=1503297,
                        concept_name="liraglutide",
                        domain_id="Drug",
                        vocabulary_id="RxNorm",
                    )
                ],
            ),
            RegisteredConceptSet(
                id=2,
                name="Type 2 DM",
                concepts=[
                    RegisteredConcept(
                        concept_id=201826,
                        concept_name="Type 2 diabetes mellitus",
                        domain_id="Condition",
                        vocabulary_id="SNOMED",
                    ),
                    RegisteredConcept(
                        concept_id=443238,
                        concept_name="DM type 2 without complication",
                        domain_id="Condition",
                        vocabulary_id="SNOMED",
                    ),
                ],
            ),
        ]

    def test_include_mapped_always_true(self, assembler, sample_concept_sets):
        """includeMapped must be True for all ConceptSet items."""
        result = assembler._build_concept_sets(sample_concept_sets)
        for cs in result:
            for item in cs["expression"]["items"]:
                assert item["includeMapped"] is True, (
                    f"includeMapped should be True for concept {item['concept']['CONCEPT_ID']}"
                )

    def test_include_descendants_propagated(self, assembler, sample_concept_sets):
        """includeDescendants must reflect the RegisteredConcept value (default True)."""
        result = assembler._build_concept_sets(sample_concept_sets)
        for cs in result:
            for item in cs["expression"]["items"]:
                assert item["includeDescendants"] is True, (
                    f"includeDescendants should be True for concept {item['concept']['CONCEPT_ID']}"
                )

    def test_include_descendants_false_when_explicit(self, assembler):
        """When a concept explicitly sets include_descendants=False, it should propagate."""
        cs_list = [
            RegisteredConceptSet(
                id=99,
                name="Family Hx CVD",
                concepts=[
                    RegisteredConcept(
                        concept_id=4167217,
                        concept_name="Family history of CVD",
                        domain_id="Observation",
                        vocabulary_id="SNOMED",
                        include_descendants=False,  # explicit override
                    )
                ],
            )
        ]
        result = assembler._build_concept_sets(cs_list)
        item = result[0]["expression"]["items"][0]
        assert item["includeDescendants"] is False
        assert item["includeMapped"] is True  # includeMapped is always True
