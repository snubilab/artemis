"""
Phase 5-7 Unit Tests: Reranker, Full Pipeline, API

Clinical Reranker, ConceptSetRecommender, FastAPI 테스트
"""
import pytest
from unittest.mock import patch, MagicMock
from testclient_compat import CompatTestClient

# Optional FastAPI import
try:
    from fastapi import FastAPI  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.agents.conceptset.clinical_reranker import ClinicalReranker, RerankerResult
from src.agents.conceptset.recommender import ConceptSetRecommender, RecommendationResponse
from src.agents.conceptset.rag_search import ConceptCandidate
from src.agents.conceptset.nlu_router import IntentResult


class TestRerankerResult:
    """RerankerResult 모델 테스트"""
    
    def test_default_values(self):
        """기본값 확인"""
        result = RerankerResult(
            candidates=[],
            method="test"
        )
        
        assert result.confidence == 0.0
        assert result.method == "test"


class TestClinicalReranker:
    """Clinical Reranker 테스트"""
    
    def test_initialization(self):
        """초기화"""
        reranker = ClinicalReranker(
            use_cross_encoder=False,
            use_llm_fallback=False
        )
        
        assert reranker.use_cross_encoder is False
        assert reranker.use_llm_fallback is False
    
    def test_empty_candidates(self):
        """빈 후보 리스트"""
        reranker = ClinicalReranker()
        result = reranker.rerank("test", [])
        
        assert result.method == "empty"
        assert result.candidates == []
    
    def test_single_candidate(self):
        """단일 후보"""
        reranker = ClinicalReranker()
        candidates = [ConceptCandidate(concept_id=1, concept_name="HF")]
        
        result = reranker.rerank("Heart Failure", candidates)
        
        assert result.method == "single"
        assert result.confidence == 1.0
    
    def test_score_based_fallback(self):
        """스코어 기반 Fallback"""
        reranker = ClinicalReranker(
            use_cross_encoder=False,
            use_llm_fallback=False
        )
        
        candidates = [
            ConceptCandidate(concept_id=1, concept_name="A", score=0.5),
            ConceptCandidate(concept_id=2, concept_name="B", score=0.9),
        ]
        
        result = reranker.rerank("test", candidates)
        
        assert result.method == "score"
        assert result.candidates[0].concept_id == 2  # 높은 스코어


class TestConceptSetRecommender:
    """ConceptSet Recommender 테스트"""
    
    def test_initialization(self):
        """초기화"""
        mock_nlu = MagicMock()
        mock_stage2 = MagicMock()
        mock_reranker = MagicMock()
        mock_builder = MagicMock()
        
        recommender = ConceptSetRecommender(
            nlu_router=mock_nlu,
            stage2=mock_stage2,
            reranker=mock_reranker,
            expression_builder=mock_builder
        )
        
        assert recommender.nlu_router == mock_nlu
    
    def test_fallback_triggered(self):
        """Fallback 트리거"""
        mock_nlu = MagicMock()
        mock_nlu.route.return_value = IntentResult(
            include=[],
            exclude=[],
            fallback_to="Agent1",
            fallback_reason="Temporal logic detected"
        )
        
        recommender = ConceptSetRecommender(nlu_router=mock_nlu)
        result = recommender.recommend("history of MI")
        
        assert result.fallback_to == "Agent1"
        assert len(result.include_recommendations) == 0
    
    def test_simple_include_query(self):
        """단순 Include 쿼리"""
        from src.agents.conceptset.expression_builder import RecommendationItem, ConceptSetExpression
        
        mock_nlu = MagicMock()
        mock_nlu.route.return_value = IntentResult(
            include=["Heart Failure"],
            exclude=[]
        )
        
        mock_stage2 = MagicMock()
        mock_stage2.search.return_value = [
            ConceptCandidate(concept_id=316139, concept_name="HF", domain_id="Condition")
        ]
        
        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = RerankerResult(
            candidates=[ConceptCandidate(concept_id=316139, concept_name="HF")],
            method="score",
            confidence=0.9
        )
        
        # 실제 RecommendationItem 반환
        mock_builder = MagicMock()
        mock_builder.build_expression.return_value = RecommendationItem(
            name="Heart Failure",
            expression=ConceptSetExpression(items=[]),
            defaultLogic="INCLUDE"
        )
        
        recommender = ConceptSetRecommender(
            nlu_router=mock_nlu,
            stage2=mock_stage2,
            reranker=mock_reranker,
            expression_builder=mock_builder
        )
        
        result = recommender.recommend("Heart Failure", use_cache=False)
        
        assert len(result.include_recommendations) == 1
        mock_stage2.search.assert_called_once()
        mock_reranker.rerank.assert_called_once()


class TestRecommendationResponse:
    """RecommendationResponse 모델 테스트"""
    
    def test_to_atlas_json(self):
        """ATLAS JSON 변환"""
        response = RecommendationResponse(
            query="test",
            include_recommendations=[],
            exclude_recommendations=[]
        )
        
        json_data = response.to_atlas_json()
        
        assert json_data["query"] == "test"
        assert "conceptSets" in json_data
    
    def test_fallback_json(self):
        """Fallback JSON"""
        response = RecommendationResponse(
            query="history of MI",
            fallback_to="Agent1",
            fallback_reason="Temporal"
        )
        
        json_data = response.to_atlas_json()
        
        assert json_data["fallback"]["to"] == "Agent1"


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestFastAPI:
    """FastAPI 엔드포인트 테스트"""
    
    def test_health_check(self):
        """헬스 체크"""
        from fastapi import FastAPI
        from src.agents.conceptset.api import router
        
        app = FastAPI()
        app.include_router(router)
        
        client = CompatTestClient(app)
        response = client.get("/api/conceptset/health")
        
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    @patch('src.agents.conceptset.api.get_recommender')
    def test_recommend_endpoint(self, mock_get_recommender):
        """추천 엔드포인트"""
        from fastapi import FastAPI
        from src.agents.conceptset.api import router
        
        mock_recommender = MagicMock()
        mock_recommender.recommend.return_value = MagicMock(
            to_atlas_json=lambda: {
                "query": "test",
                "conceptSets": [],
                "fallback": None
            }
        )
        mock_get_recommender.return_value = mock_recommender
        
        app = FastAPI()
        app.include_router(router)
        
        client = CompatTestClient(app)
        response = client.post(
            "/api/conceptset/recommend",
            json={"query": "Heart Failure"}
        )
        
        assert response.status_code == 200
        assert response.json()["query"] == "test"
