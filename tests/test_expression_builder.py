"""
Phase 4 Unit Tests: Expression Builder

ATLAS ConceptSet Expression 변환 테스트
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from src.agents.conceptset.expression_builder import (
    ExpressionBuilder,
    ConceptExpression,
    ConceptSetExpression,
    RecommendationItem
)
from src.agents.conceptset.rag_search import ConceptCandidate


class TestConceptExpression:
    """ConceptExpression 모델 테스트"""
    
    def test_default_values(self):
        """기본값 확인"""
        expr = ConceptExpression(
            concept_id=201820,
            concept_name="Type 2 Diabetes",
            domain_id="Condition",
            vocabulary_id="SNOMED",
            concept_class_id="Clinical Finding"
        )
        
        assert expr.includeDescendants is True
        assert expr.includeMapped is False
        assert expr.isExcluded is False
        assert expr.standard_concept == "S"
    
    def test_exclude_expression(self):
        """제외 Expression"""
        expr = ConceptExpression(
            concept_id=12345,
            concept_name="TZD",
            domain_id="Drug",
            vocabulary_id="RxNorm",
            concept_class_id="Ingredient",
            isExcluded=True
        )
        
        assert expr.isExcluded is True


class TestConceptSetExpression:
    """ConceptSetExpression 모델 테스트"""
    
    def test_empty_expression(self):
        """빈 Expression"""
        expr = ConceptSetExpression()
        assert expr.items == []
    
    def test_to_atlas_json(self):
        """ATLAS JSON 변환"""
        expr = ConceptSetExpression(items=[
            ConceptExpression(
                concept_id=201820,
                concept_name="T2DM",
                domain_id="Condition",
                vocabulary_id="SNOMED",
                concept_class_id="Finding"
            )
        ])

        json_data = expr.to_atlas_json()
        concept = json_data["items"][0]["concept"]

        assert "items" in json_data
        assert len(json_data["items"]) == 1
        assert concept["CONCEPT_ID"] == 201820
        assert concept["STANDARD_CONCEPT"] == "S"
        assert concept["STANDARD_CONCEPT_CAPTION"] == "Standard"
        assert concept["INVALID_REASON"] is None
        assert concept["INVALID_REASON_CAPTION"] is None
        assert json_data["items"][0]["includeDescendants"] is True

    def test_to_atlas_json_standard_concept_captions(self):
        """STANDARD_CONCEPT_CAPTION mapping for all code values"""
        def make_expr(code):
            return ConceptSetExpression(items=[
                ConceptExpression(
                    concept_id=1,
                    concept_name="Test",
                    domain_id="Condition",
                    vocabulary_id="SNOMED",
                    concept_class_id="Finding",
                    standard_concept=code,
                )
            ])

        assert make_expr("S").to_atlas_json()["items"][0]["concept"]["STANDARD_CONCEPT_CAPTION"] == "Standard"
        assert make_expr("C").to_atlas_json()["items"][0]["concept"]["STANDARD_CONCEPT_CAPTION"] == "Classification"
        assert make_expr("N").to_atlas_json()["items"][0]["concept"]["STANDARD_CONCEPT_CAPTION"] == "Non-Standard"
        assert make_expr("").to_atlas_json()["items"][0]["concept"]["STANDARD_CONCEPT_CAPTION"] == "Non-Standard"


class TestRecommendationItem:
    """RecommendationItem 모델 테스트"""
    
    def test_include_logic(self):
        """INCLUDE 로직"""
        item = RecommendationItem(
            name="Heart Failure",
            expression=ConceptSetExpression(),
            defaultLogic="INCLUDE"
        )
        
        assert item.defaultLogic == "INCLUDE"
    
    def test_exclude_logic(self):
        """EXCLUDE 로직"""
        item = RecommendationItem(
            name="TZD",
            expression=ConceptSetExpression(),
            defaultLogic="EXCLUDE",
            reason="User query specified 'TZD 제외'"
        )
        
        assert item.defaultLogic == "EXCLUDE"
        assert item.reason is not None


class TestExpressionBuilder:
    """Expression Builder 테스트"""
    
    def test_initialization(self):
        """빌더 초기화"""
        builder = ExpressionBuilder(schema="test_schema")
        assert builder.schema == "test_schema"
    
    def test_default_schema(self):
        """기본 스키마 (settings.CDM_SCHEMA 사용)"""
        from src.settings import settings
        builder = ExpressionBuilder()
        assert builder.schema == settings.CDM_SCHEMA
    
    @patch.object(ExpressionBuilder, '_validate_standard_concepts')
    @patch.object(ExpressionBuilder, '_roll_up')
    def test_build_expression_include(self, mock_rollup, mock_validate):
        """INCLUDE Expression 생성"""
        candidates = [
            ConceptCandidate(
                concept_id=316139,
                concept_name="Heart Failure",
                domain_id="Condition",
                vocabulary_id="SNOMED",
                concept_class_id="Clinical Finding"
            )
        ]
        
        mock_validate.return_value = candidates
        mock_rollup.return_value = candidates
        
        builder = ExpressionBuilder()
        result = builder.build_expression(candidates, default_logic="INCLUDE")
        
        assert result.defaultLogic == "INCLUDE"
        assert result.name == "Heart Failure"
        assert len(result.expression.items) == 1
        assert result.expression.items[0].isExcluded is False
    
    @patch.object(ExpressionBuilder, '_validate_standard_concepts')
    @patch.object(ExpressionBuilder, '_roll_up')
    def test_build_expression_exclude(self, mock_rollup, mock_validate):
        """EXCLUDE Expression 생성"""
        candidates = [
            ConceptCandidate(
                concept_id=12345,
                concept_name="Thiazolidinediones",
                domain_id="Drug",
                vocabulary_id="RxNorm",
                concept_class_id="Ingredient"
            )
        ]
        
        mock_validate.return_value = candidates
        mock_rollup.return_value = candidates
        
        builder = ExpressionBuilder()
        result = builder.build_expression(candidates, default_logic="EXCLUDE")
        
        assert result.defaultLogic == "EXCLUDE"
        assert result.expression.items[0].isExcluded is True
    
    def test_build_expression_empty(self):
        """빈 후보 리스트"""
        builder = ExpressionBuilder()
        result = builder.build_expression([])
        
        assert result.name == "Empty"
        assert len(result.expression.items) == 0
    
    @patch('src.agents.conceptset.expression_builder.SessionLocal')
    def test_validate_standard_concepts(self, mock_session_local):
        """Standard Concept 검증"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(concept_id=201820)  # 하나만 valid
        ]
        mock_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_session
        
        candidates = [
            ConceptCandidate(concept_id=201820, concept_name="Valid"),
            ConceptCandidate(concept_id=99999, concept_name="Invalid")
        ]
        
        builder = ExpressionBuilder()
        result = builder._validate_standard_concepts(candidates)
        
        assert len(result) == 1
        assert result[0].concept_id == 201820


class TestRollUp:
    """Roll-up 최적화 테스트"""
    
    @patch('src.agents.conceptset.expression_builder.SessionLocal')
    def test_roll_up_removes_descendants(self, mock_session_local):
        """하위 개념 제거"""
        mock_session = MagicMock()

        # _roll_up calls _filter_overbroad first (1st query), then ancestor lookup (2nd query)
        overbroad_result = MagicMock()
        overbroad_result.fetchall.return_value = []  # no overbroad concepts

        ancestor_result = MagicMock()
        # ID 2가 ID 1의 하위 개념
        ancestor_result.fetchall.return_value = [
            MagicMock(descendant_concept_id=2, ancestor_concept_id=1)
        ]

        mock_session.execute.side_effect = [overbroad_result, ancestor_result]
        mock_session_local.return_value = mock_session

        candidates = [
            ConceptCandidate(concept_id=1, concept_name="Parent"),
            ConceptCandidate(concept_id=2, concept_name="Child")
        ]

        builder = ExpressionBuilder()
        result = builder._roll_up(candidates)

        assert len(result) == 1
        assert result[0].concept_id == 1  # Parent만 유지
    
    def test_roll_up_single_concept(self):
        """단일 개념 - Roll-up 불필요"""
        candidates = [
            ConceptCandidate(concept_id=1, concept_name="Single")
        ]

        builder = ExpressionBuilder()
        result = builder._roll_up(candidates)

        assert len(result) == 1


class TestFilterOverbroad:
    """Overbroad ancestor filtering tests"""

    @patch('src.agents.conceptset.expression_builder.SessionLocal')
    def test_overbroad_concepts_removed(self, mock_session_local):
        """Concepts with descendants > threshold are removed"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        # Clinical finding has 133K descendants (above 500 threshold)
        mock_result.fetchall.return_value = [
            MagicMock(ancestor_concept_id=441840)  # overbroad
        ]
        mock_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_session

        candidates = [
            ConceptCandidate(concept_id=441840, concept_name="Clinical finding",
                           domain_id="Condition", vocabulary_id="SNOMED", concept_class_id="Clinical Finding"),
            ConceptCandidate(concept_id=443454, concept_name="Cerebral infarction",
                           domain_id="Condition", vocabulary_id="SNOMED", concept_class_id="Clinical Finding"),
        ]

        builder = ExpressionBuilder(schema="test")
        result = builder._filter_overbroad(candidates)

        assert len(result) == 1
        assert result[0].concept_id == 443454

    @patch('src.agents.conceptset.expression_builder.SessionLocal')
    def test_no_overbroad_keeps_all(self, mock_session_local):
        """When no concepts exceed threshold, all are kept"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []  # none exceed threshold
        mock_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_session

        candidates = [
            ConceptCandidate(concept_id=443454, concept_name="Cerebral infarction"),
            ConceptCandidate(concept_id=373503, concept_name="Transient cerebral ischemia"),
        ]

        builder = ExpressionBuilder(schema="test")
        result = builder._filter_overbroad(candidates)

        assert len(result) == 2

    @patch('src.agents.conceptset.expression_builder.SessionLocal')
    def test_all_overbroad_keeps_originals(self, mock_session_local):
        """Safety guard: if ALL candidates are overbroad, keep originals"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(ancestor_concept_id=441840),
            MagicMock(ancestor_concept_id=4180628),
        ]
        mock_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_session

        candidates = [
            ConceptCandidate(concept_id=441840, concept_name="Clinical finding"),
            ConceptCandidate(concept_id=4180628, concept_name="Disorder of body system"),
        ]

        builder = ExpressionBuilder(schema="test")
        result = builder._filter_overbroad(candidates)

        assert len(result) == 2  # kept because ALL were overbroad

    def test_single_candidate_skips_filter(self):
        """Single candidate bypasses overbroad check"""
        candidates = [
            ConceptCandidate(concept_id=441840, concept_name="Clinical finding"),
        ]

        builder = ExpressionBuilder(schema="test")
        result = builder._filter_overbroad(candidates)

        assert len(result) == 1

    @patch.dict('os.environ', {'AGENT2_ROLLUP_MAX_DESCENDANTS': '100'})
    @patch('src.agents.conceptset.expression_builder.SessionLocal')
    def test_env_var_threshold(self, mock_session_local):
        """Threshold respects AGENT2_ROLLUP_MAX_DESCENDANTS env var"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        # With threshold=100, concept with 200 descendants is overbroad
        mock_result.fetchall.return_value = [
            MagicMock(ancestor_concept_id=4185932)  # Ischemic heart disease (206 desc)
        ]
        mock_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_session

        candidates = [
            ConceptCandidate(concept_id=4185932, concept_name="Ischemic heart disease"),
            ConceptCandidate(concept_id=312327, concept_name="Acute MI"),
        ]

        builder = ExpressionBuilder(schema="test")
        result = builder._filter_overbroad(candidates)

        assert len(result) == 1
        assert result[0].concept_id == 312327

    @patch('src.agents.conceptset.expression_builder.SessionLocal')
    def test_db_error_returns_candidates(self, mock_session_local):
        """DB error falls back to returning all candidates"""
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("connection refused")
        mock_session_local.return_value = mock_session

        candidates = [
            ConceptCandidate(concept_id=441840, concept_name="Clinical finding"),
            ConceptCandidate(concept_id=443454, concept_name="Cerebral infarction"),
        ]

        builder = ExpressionBuilder(schema="test")
        result = builder._filter_overbroad(candidates)

        assert len(result) == 2  # fallback: all kept
