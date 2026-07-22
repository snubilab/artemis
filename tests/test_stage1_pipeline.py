"""
Phase 2 Unit Tests: Stage 1 Pipeline

RRF, RAG Search, Ontology Search 단위 테스트
"""
import pytest
from unittest.mock import patch, MagicMock

from src.agents.conceptset.rag_search import RAGSearch, ConceptCandidate
from src.agents.conceptset.ontology_search import OntologySearch
from src.agents.conceptset.rank_fusion import reciprocal_rank_fusion, weighted_reciprocal_rank_fusion
from src.agents.conceptset.stage1_pipeline import Stage1Pipeline


class TestConceptCandidate:
    """ConceptCandidate 모델 테스트"""
    
    def test_default_values(self):
        """기본값 확인"""
        candidate = ConceptCandidate(
            concept_id=12345,
            concept_name="Type 2 Diabetes Mellitus"
        )
        
        assert candidate.concept_id == 12345
        assert candidate.domain_id == "Unknown"
        assert candidate.source == "rag"
        assert candidate.score == 0.0
    
    def test_full_values(self):
        """전체 필드 확인"""
        candidate = ConceptCandidate(
            concept_id=201820,
            concept_name="Type 2 Diabetes Mellitus",
            domain_id="Condition",
            vocabulary_id="SNOMED",
            concept_class_id="Clinical Finding",
            score=0.95,
            source="ontology"
        )
        
        assert candidate.vocabulary_id == "SNOMED"
        assert candidate.source == "ontology"


class TestRRF:
    """Reciprocal Rank Fusion 테스트"""
    
    def test_single_list(self):
        """단일 리스트 RRF"""
        candidates = [
            ConceptCandidate(concept_id=1, concept_name="A", score=0.9),
            ConceptCandidate(concept_id=2, concept_name="B", score=0.8),
        ]
        
        result = reciprocal_rank_fusion(candidates)
        
        assert len(result) == 2
        assert result[0].concept_id == 1  # First rank
        assert result[0].source == "rrf"
    
    def test_two_lists_overlap(self):
        """두 리스트 RRF (겹침 있음)"""
        list1 = [
            ConceptCandidate(concept_id=1, concept_name="A"),
            ConceptCandidate(concept_id=2, concept_name="B"),
        ]
        list2 = [
            ConceptCandidate(concept_id=2, concept_name="B"),  # 겹침
            ConceptCandidate(concept_id=3, concept_name="C"),
        ]
        
        result = reciprocal_rank_fusion(list1, list2)
        
        assert len(result) == 3  # 1, 2, 3 (중복 제거)
        # ID 2는 두 리스트에 모두 있으므로 더 높은 RRF 점수
        assert result[0].concept_id == 2
    
    def test_rrf_score_calculation(self):
        """RRF 점수 계산 검증"""
        list1 = [ConceptCandidate(concept_id=1, concept_name="A")]  # rank 1
        list2 = [ConceptCandidate(concept_id=1, concept_name="A")]  # rank 1
        
        result = reciprocal_rank_fusion(list1, list2, k=60)
        
        # Score = 1/(60+1) + 1/(60+1) = 2/61 ≈ 0.0328
        expected_score = 2.0 / 61.0
        assert abs(result[0].score - expected_score) < 0.0001
    
    def test_empty_lists(self):
        """빈 리스트 처리"""
        result = reciprocal_rank_fusion([], [])
        assert result == []


class TestWeightedRRF:
    """가중치 RRF 테스트"""
    
    def test_weighted_fusion(self):
        """가중치 적용 확인"""
        list1 = [ConceptCandidate(concept_id=1, concept_name="A")]
        list2 = [ConceptCandidate(concept_id=2, concept_name="B")]
        
        # list1에 2배 가중치
        result = weighted_reciprocal_rank_fusion(
            (list1, 2.0),
            (list2, 1.0),
            k=60
        )
        
        # ID 1이 더 높은 점수
        assert result[0].concept_id == 1
        assert result[0].source == "weighted_rrf"


class TestRAGSearch:
    """RAG Search 테스트 (Mocked)"""
    
    @patch('src.agents.conceptset.rag_search.get_collection')
    def test_search_initialization(self, mock_get_collection):
        """RAGSearch 초기화"""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        
        searcher = RAGSearch()
        _ = searcher.collection  # Trigger lazy load
        
        mock_get_collection.assert_called_once_with("omop_concepts")
    
    @patch('src.agents.conceptset.rag_search.get_collection')
    def test_search_returns_candidates(self, mock_get_collection):
        """검색 결과 반환"""
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            'ids': [['12345', '67890']],
            'metadatas': [[
                {'concept_name': 'Heart Failure', 'domain_id': 'Condition'},
                {'concept_name': 'Acute HF', 'domain_id': 'Condition'}
            ]],
            'distances': [[0.1, 0.2]]
        }
        mock_get_collection.return_value = mock_collection
        
        searcher = RAGSearch()
        results = searcher.search("Heart Failure")
        
        assert len(results) == 2
        assert results[0].concept_id == 12345
        assert results[0].domain_id == "Condition"
    
    @patch('src.agents.conceptset.rag_search.get_collection')
    def test_search_empty_db(self, mock_get_collection):
        """빈 DB 처리"""
        mock_collection = MagicMock()
        mock_collection.query.side_effect = Exception("Empty DB")
        mock_get_collection.return_value = mock_collection
        
        searcher = RAGSearch()
        results = searcher.search("anything")
        
        assert results == []


class TestOntologySearch:
    """Ontology Search 테스트 (Mocked)"""
    
    @patch('src.agents.conceptset.ontology_search.SessionLocal')
    def test_search_by_name(self, mock_session_local):
        """이름으로 검색"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(
                concept_id=201820,
                concept_name="Type 2 Diabetes",
                domain_id="Condition",
                vocabulary_id="SNOMED",
                concept_class_id="Clinical Finding"
            )
        ]
        mock_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_session
        
        searcher = OntologySearch()
        results = searcher.search_by_name("diabetes")
        
        assert len(results) == 1
        assert results[0].concept_id == 201820
        assert results[0].source == "ontology"


class TestStage1Pipeline:
    """Stage 1 Pipeline 통합 테스트"""
    
    def test_pipeline_initialization(self):
        """파이프라인 초기화"""
        # Mock으로 의존성 주입
        mock_rag = MagicMock()
        mock_ontology = MagicMock()
        
        pipeline = Stage1Pipeline(
            rag_search=mock_rag,
            ontology_search=mock_ontology
        )
        
        assert pipeline.rag_search == mock_rag
        assert pipeline.ontology_search == mock_ontology
    
    def test_search_sync(self):
        """동기 검색"""
        mock_rag = MagicMock()
        mock_ontology = MagicMock()
        
        mock_rag.search.return_value = [
            ConceptCandidate(concept_id=1, concept_name="A")
        ]
        mock_ontology.search_by_name.return_value = [
            ConceptCandidate(concept_id=2, concept_name="B")
        ]
        
        pipeline = Stage1Pipeline(
            rag_search=mock_rag,
            ontology_search=mock_ontology
        )
        
        results = pipeline.search_sync("test query")
        
        assert len(results) == 2
        mock_rag.search.assert_called_once()
        mock_ontology.search_by_name.assert_called_once()
