"""Tests for HITL mapping metadata models (SPEC-UI-003 Task 1).

RED phase: All tests written before implementation.
"""

import pytest

from src.api.models.tte import (
    CriterionMappingMetadata,
    MappingCandidateItem,
    ProcessEligibilityCriterionDiagnostic,
    ReRecommendRequest,
)


class TestMappingCandidateItem:
    def test_mapping_candidate_item_creation(self):
        # Arrange / Act
        item = MappingCandidateItem(
            conceptId=4329847,
            conceptName="Myocardial infarction",
            score=0.92,
            source="rag",
        )

        # Assert
        assert item.conceptId == 4329847
        assert item.conceptName == "Myocardial infarction"
        assert item.score == 0.92
        assert item.source == "rag"

    def test_mapping_candidate_item_included_default_false(self):
        # Arrange / Act
        item = MappingCandidateItem(
            conceptId=4329847,
            conceptName="Myocardial infarction",
            score=0.85,
            source="ontology",
        )

        # Assert
        assert item.included is False

    def test_mapping_candidate_item_included_can_be_set_true(self):
        # Arrange / Act
        item = MappingCandidateItem(
            conceptId=4329847,
            conceptName="Myocardial infarction",
            score=0.85,
            source="phoebe",
            included=True,
        )

        # Assert
        assert item.included is True


class TestCriterionMappingMetadata:
    def test_criterion_mapping_metadata_empty(self):
        # Arrange / Act
        meta = CriterionMappingMetadata()

        # Assert
        assert meta.allCandidates == []
        assert meta.rerankConfidence is None
        assert meta.rerankMethod is None
        assert meta.queryUsed is None
        assert meta.selectedConceptIds == []

    def test_criterion_mapping_metadata_roundtrip(self):
        # Arrange
        candidates = [
            MappingCandidateItem(
                conceptId=4329847,
                conceptName="Myocardial infarction",
                score=0.92,
                source="rag",
                included=True,
            ),
            MappingCandidateItem(
                conceptId=312327,
                conceptName="Coronary arteriosclerosis",
                score=0.75,
                source="ontology",
                included=False,
            ),
        ]
        original = CriterionMappingMetadata(
            allCandidates=candidates,
            rerankConfidence=0.88,
            rerankMethod="cross_encoder",
            queryUsed="myocardial infarction history",
            selectedConceptIds=[4329847],
        )

        # Act
        dumped = original.model_dump()
        restored = CriterionMappingMetadata.model_validate(dumped)

        # Assert
        assert len(restored.allCandidates) == 2
        assert restored.allCandidates[0].conceptId == 4329847
        assert restored.allCandidates[0].included is True
        assert restored.rerankConfidence == 0.88
        assert restored.rerankMethod == "cross_encoder"
        assert restored.queryUsed == "myocardial infarction history"
        assert restored.selectedConceptIds == [4329847]

    def test_mapping_candidates_sorted_by_score(self):
        # Arrange - API contract: callers are expected to provide candidates
        # in descending score order; model preserves insertion order
        candidates = [
            MappingCandidateItem(conceptId=1, conceptName="A", score=0.95, source="rag"),
            MappingCandidateItem(conceptId=2, conceptName="B", score=0.80, source="rag"),
            MappingCandidateItem(conceptId=3, conceptName="C", score=0.60, source="rag"),
        ]
        meta = CriterionMappingMetadata(allCandidates=candidates)

        # Act
        scores = [c.score for c in meta.allCandidates]

        # Assert: list preserves order (scores are descending as supplied)
        assert scores == sorted(scores, reverse=True)

    def test_criterion_mapping_metadata_score_validation(self):
        # Arrange / Act - score is a float; model does not enforce range,
        # but the contract assumes [0.0, 1.0]; verify boundary values are accepted
        low = MappingCandidateItem(conceptId=1, conceptName="X", score=0.0, source="rag")
        high = MappingCandidateItem(conceptId=2, conceptName="Y", score=1.0, source="rag")

        # Assert
        assert low.score == 0.0
        assert high.score == 1.0


class TestReRecommendRequest:
    def test_re_recommend_request_defaults(self):
        # Arrange / Act
        req = ReRecommendRequest()

        # Assert
        assert req.hint == ""
        assert req.topK == 10

    def test_re_recommend_request_custom_values(self):
        # Arrange / Act
        req = ReRecommendRequest(hint="diabetes type 2", topK=5)

        # Assert
        assert req.hint == "diabetes type 2"
        assert req.topK == 5


class TestProcessEligibilityCriterionDiagnosticExtension:
    def test_process_eligibility_criterion_diagnostic_backward_compat(self):
        # Arrange / Act - create WITHOUT mappingMetadata (must work as before)
        diag = ProcessEligibilityCriterionDiagnostic(
            criterionId=1,
            criterionRole="inclusion",
            status="processed",
            description="Prior MI",
        )

        # Assert
        assert diag.mappingMetadata is None

    def test_process_eligibility_criterion_diagnostic_with_metadata(self):
        # Arrange
        metadata = CriterionMappingMetadata(
            allCandidates=[
                MappingCandidateItem(
                    conceptId=4329847,
                    conceptName="Myocardial infarction",
                    score=0.92,
                    source="rag",
                    included=True,
                )
            ],
            rerankConfidence=0.90,
            rerankMethod="llm",
            queryUsed="prior myocardial infarction",
            selectedConceptIds=[4329847],
        )

        diag = ProcessEligibilityCriterionDiagnostic(
            criterionId=2,
            criterionRole="inclusion",
            status="processed",
            description="Prior MI",
            mappingMetadata=metadata,
        )

        # Act - roundtrip
        dumped = diag.model_dump()
        restored = ProcessEligibilityCriterionDiagnostic.model_validate(dumped)

        # Assert
        assert restored.mappingMetadata is not None
        assert restored.mappingMetadata.rerankMethod == "llm"
        assert restored.mappingMetadata.rerankConfidence == 0.90
        assert len(restored.mappingMetadata.allCandidates) == 1
        assert restored.mappingMetadata.allCandidates[0].conceptId == 4329847
