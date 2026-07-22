"""
ConceptSet Recommendation System

RFC-001 구현: 자연어 임상 기준을 OMOP ConceptSet으로 매핑하는 추천 시스템
"""
import logging

logger = logging.getLogger(__name__)

# Phase 1: NLU Router
from src.agents.conceptset.nlu_router import NLURouter, IntentResult, get_nlu_router

# Phase 2: Stage 1 검색
from src.agents.conceptset.rag_search import RAGSearch, ConceptCandidate, get_rag_search
from src.agents.conceptset.ontology_search import OntologySearch, get_ontology_search
from src.agents.conceptset.rank_fusion import reciprocal_rank_fusion
from src.agents.conceptset.stage1_pipeline import Stage1Pipeline, get_stage1_pipeline

# Phase 3: PHOEBE + Stage 2
from src.agents.conceptset.phoebe_client import PhoebeClient, get_phoebe_client
from src.agents.conceptset.stage2_pipeline import Stage2Pipeline, get_stage2_pipeline

# Phase 4: Expression Builder
from src.agents.conceptset.expression_builder import (
    ExpressionBuilder, get_expression_builder,
    ConceptExpression, ConceptSetExpression, RecommendationItem
)

# Phase 5: Clinical Reranker
from src.agents.conceptset.clinical_reranker import ClinicalReranker, get_clinical_reranker

# Phase 6: Full Pipeline
from src.agents.conceptset.recommender import ConceptSetRecommender, get_recommender

# Phase 7: API (Optional - requires FastAPI)
try:
    from src.agents.conceptset.api import router as conceptset_router
    _HAS_API = True
except ImportError as e:
    conceptset_router = None
    _HAS_API = False
    logger.warning(
        "[ConceptSet] FastAPI router unavailable; API routes disabled. "
        f"error_type={type(e).__name__} error={e}"
    )

__all__ = [
    # Phase 1
    "NLURouter", "IntentResult", "get_nlu_router",
    # Phase 2
    "RAGSearch", "ConceptCandidate", "get_rag_search",
    "OntologySearch", "get_ontology_search",
    "reciprocal_rank_fusion",
    "Stage1Pipeline", "get_stage1_pipeline",
    # Phase 3
    "PhoebeClient", "get_phoebe_client",
    "Stage2Pipeline", "get_stage2_pipeline",
    # Phase 4
    "ExpressionBuilder", "get_expression_builder",
    "ConceptExpression", "ConceptSetExpression", "RecommendationItem",
    # Phase 5
    "ClinicalReranker", "get_clinical_reranker",
    # Phase 6
    "ConceptSetRecommender", "get_recommender",
    # Phase 7 (Optional)
    "conceptset_router",
]
