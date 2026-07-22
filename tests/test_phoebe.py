"""
Phase 3 Unit Tests: PHOEBE Client + Stage 2 Pipeline

PHOEBE 클라이언트와 Stage 2 통합 테스트
"""
import pytest
from unittest.mock import patch, MagicMock
import asyncio

from src.agents.conceptset.phoebe_client import PhoebeClient
from src.agents.conceptset.stage2_pipeline import Stage2Pipeline
from src.agents.conceptset.rag_search import ConceptCandidate


class TestPhoebeClient:
    """PHOEBE Client 테스트"""
    
    def test_initialization(self):
        """클라이언트 초기화"""
        client = PhoebeClient(schema="test_schema", timeout_ms=1000)
        
        assert client.schema == "test_schema"
        assert client.timeout_ms == 1000
    
    def test_default_schema(self):
        """기본 스키마"""
        client = PhoebeClient()
        assert client.schema == "demo_cdm"
    
    @patch('src.agents.conceptset.phoebe_client.SessionLocal')
    def test_get_recommendations(self, mock_session_local):
        """추천 조회"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(
                concept_id=12345,
                concept_name="Related Concept",
                domain_id="Condition",
                vocabulary_id="SNOMED",
                concept_class_id="Finding"
            )
        ]
        mock_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_session
        
        client = PhoebeClient()
        results = client.get_recommendations(seed_concept_id=316139)
        
        assert len(results) == 1
        assert results[0].concept_id == 12345
        assert results[0].source == "phoebe"
    
    @patch.object(PhoebeClient, 'get_recommendations')
    def test_expand_seeds(self, mock_get_recs):
        """다중 Seed 확장"""
        mock_get_recs.side_effect = [
            [ConceptCandidate(concept_id=1, concept_name="A", score=0.9)],
            [ConceptCandidate(concept_id=2, concept_name="B", score=0.8)],
            [ConceptCandidate(concept_id=1, concept_name="A", score=0.7)],  # 중복
        ]
        
        client = PhoebeClient()
        results = client.expand_seeds([100, 200, 300])
        
        assert len(results) == 2  # 중복 제거
        assert results[0].concept_id == 1  # 높은 점수 유지
        assert results[0].score == 0.9
    
    @patch.object(PhoebeClient, 'get_recommendations')
    def test_expand_empty_seeds(self, mock_get_recs):
        """빈 Seed 리스트"""
        client = PhoebeClient()
        results = client.expand_seeds([])
        
        assert results == []
        mock_get_recs.assert_not_called()


class TestStage2Pipeline:
    """Stage 2 Pipeline 테스트"""
    
    def test_initialization(self):
        """파이프라인 초기화"""
        mock_stage1 = MagicMock()
        mock_phoebe = MagicMock()
        
        pipeline = Stage2Pipeline(stage1=mock_stage1, phoebe=mock_phoebe)
        
        assert pipeline.stage1 == mock_stage1
        assert pipeline.phoebe == mock_phoebe
    
    def test_search_full_pipeline(self):
        """전체 파이프라인 검색"""
        mock_stage1 = MagicMock()
        mock_phoebe = MagicMock()
        
        # Stage 1 결과
        mock_stage1.search_sync.return_value = [
            ConceptCandidate(concept_id=1, concept_name="Direct Match", score=0.9)
        ]
        
        # PHOEBE 결과
        mock_phoebe.expand_seeds.return_value = [
            ConceptCandidate(concept_id=2, concept_name="PHOEBE Expansion", score=0.8)
        ]
        
        pipeline = Stage2Pipeline(stage1=mock_stage1, phoebe=mock_phoebe)
        results = pipeline.search("Heart Failure")
        
        assert len(results) == 2
        mock_stage1.search_sync.assert_called_once()
        mock_phoebe.expand_seeds.assert_called_once()
    
    def test_search_no_stage1_results(self):
        """Stage 1 결과 없음"""
        mock_stage1 = MagicMock()
        mock_phoebe = MagicMock()
        
        mock_stage1.search_sync.return_value = []
        
        pipeline = Stage2Pipeline(stage1=mock_stage1, phoebe=mock_phoebe)
        results = pipeline.search("Unknown Query")
        
        assert results == []
        mock_phoebe.expand_seeds.assert_not_called()


class TestCircuitBreaker:
    """Circuit Breaker 테스트"""
    
    def test_timeout_parameter(self):
        """타임아웃 파라미터 설정"""
        client = PhoebeClient(timeout_ms=100)
        assert client.timeout_ms == 100
    
    def test_circuit_breaker_method_exists(self):
        """Circuit Breaker 메서드 존재 확인"""
        client = PhoebeClient()
        assert hasattr(client, 'expand_seeds_with_timeout')
        assert callable(client.expand_seeds_with_timeout)
