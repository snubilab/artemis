"""
ConceptSet Recommendation System - Full Pipeline

Phase 6: 전체 파이프라인 통합
Phase 8 P3: Semantic Cache 통합
NLU → Stage 1 → PHOEBE → Reranker → Expression Builder
"""
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

from src.agents.conceptset.nlu_router import NLURouter, IntentResult, get_nlu_router
from src.agents.conceptset.stage2_pipeline import Stage2Pipeline, get_stage2_pipeline
from src.agents.conceptset.clinical_reranker import ClinicalReranker, get_clinical_reranker
from src.agents.conceptset.expression_builder import (
    ExpressionBuilder, get_expression_builder, RecommendationItem
)
from src.utils.logging import get_logger
from src.utils.cache import get_cache, SemanticCache

logger = get_logger(__name__)


class RecommendationResponse(BaseModel):
    """API 응답 모델"""
    query: str
    include_recommendations: List[RecommendationItem] = Field(default_factory=list)
    exclude_recommendations: List[RecommendationItem] = Field(default_factory=list)
    fallback_to: Optional[str] = None
    fallback_reason: Optional[str] = None
    cached: bool = False  # Phase 8 P3: cache hit indicator
    
    def to_atlas_json(self) -> dict:
        """ATLAS 호환 JSON (ConceptSets 배열)"""
        concept_sets = []
        
        for rec in self.include_recommendations:
            concept_sets.append({
                "name": rec.name,
                "expression": rec.expression.to_atlas_json(),
                "defaultLogic": "INCLUDE"
            })
        
        for rec in self.exclude_recommendations:
            concept_sets.append({
                "name": rec.name,
                "expression": rec.expression.to_atlas_json(),
                "defaultLogic": "EXCLUDE"
            })
        
        return {
            "query": self.query,
            "conceptSets": concept_sets,
            "cached": self.cached,
            "fallback": {
                "to": self.fallback_to,
                "reason": self.fallback_reason
            } if self.fallback_to else None
        }


class ConceptSetRecommender:
    """
    ConceptSet Recommendation System - Full Pipeline.
    
    RFC-001 v2.1 아키텍처 구현:
    
    Query → Cache Check → [Hit: Return cached]
                           ↓ (Miss)
                     NLU Router → [Include/Exclude 분리]
                           ↓
                     Stage 2 (RAG ∥ Ontology → RRF → PHOEBE)
                           ↓
                     Clinical Reranker
                           ↓
                     Expression Builder
                           ↓
                     Cache Set → RecommendationResponse
    """
    
    def __init__(
        self,
        nlu_router: Optional[NLURouter] = None,
        stage2: Optional[Stage2Pipeline] = None,
        reranker: Optional[ClinicalReranker] = None,
        expression_builder: Optional[ExpressionBuilder] = None,
        cache: Optional[SemanticCache] = None
    ):
        self._nlu_router = nlu_router
        self._stage2 = stage2
        self._reranker = reranker
        self._expression_builder = expression_builder
        self._cache = cache
    
    @property
    def nlu_router(self) -> NLURouter:
        if self._nlu_router is None:
            self._nlu_router = get_nlu_router()
        return self._nlu_router
    
    @property
    def stage2(self) -> Stage2Pipeline:
        if self._stage2 is None:
            self._stage2 = get_stage2_pipeline()
        return self._stage2
    
    @property
    def reranker(self) -> ClinicalReranker:
        if self._reranker is None:
            self._reranker = get_clinical_reranker()
        return self._reranker
    
    @property
    def expression_builder(self) -> ExpressionBuilder:
        if self._expression_builder is None:
            self._expression_builder = get_expression_builder()
        return self._expression_builder
    
    @property
    def cache(self) -> SemanticCache:
        if self._cache is None:
            self._cache = get_cache()
        return self._cache
    
    def recommend(
        self,
        query: str,
        top_k: int = 10,
        include_descendants: bool = True,
        use_cache: bool = True
    ) -> RecommendationResponse:
        """
        자연어 쿼리를 ConceptSet 추천으로 변환.
        
        Args:
            query: 자연어 임상 기준 (예: "Heart Failure but exclude TZD")
            top_k: 각 Intent당 반환할 ConceptSet 수
            include_descendants: Roll-up 최적화 적용 여부
            use_cache: 캐시 사용 여부
            
        Returns:
            RecommendationResponse
        """
        logger.info("Starting recommendation", query=query, top_k=top_k)
        
        # Phase 8 P3: Cache Check
        cache_options = {"top_k": top_k, "include_descendants": include_descendants}
        if use_cache:
            cached = self.cache.get(query, RecommendationResponse, **cache_options)
            if cached:
                cached.cached = True
                logger.info("Cache hit", query=query)
                return cached
        
        # Step 1: NLU Router - Intent Separation
        logger.info("Step 1: NLU Router")
        intent_result = self.nlu_router.route(query)
        
        # Fallback 체크
        if intent_result.fallback_to:
            logger.info("Fallback triggered", reason=intent_result.fallback_reason)
            return RecommendationResponse(
                query=query,
                fallback_to=intent_result.fallback_to,
                fallback_reason=intent_result.fallback_reason
            )
        
        # Step 2: Process Include Intents
        include_recs = []
        for include_query in intent_result.include:
            logger.info("Processing INCLUDE", intent=include_query)
            rec = self._process_intent(include_query, "INCLUDE", top_k, include_descendants)
            if rec:
                include_recs.append(rec)
        
        # Step 3: Process Exclude Intents
        exclude_recs = []
        for exclude_query in intent_result.exclude:
            logger.info("Processing EXCLUDE", intent=exclude_query)
            rec = self._process_intent(exclude_query, "EXCLUDE", top_k, include_descendants)
            if rec:
                exclude_recs.append(rec)
        
        logger.info("Pipeline complete", includes=len(include_recs), excludes=len(exclude_recs))
        
        response = RecommendationResponse(
            query=query,
            include_recommendations=include_recs,
            exclude_recommendations=exclude_recs
        )
        
        # Phase 8 P3: Cache Set
        if use_cache:
            self.cache.set(query, response, **cache_options)
        
        return response
    
    def _process_intent(
        self,
        intent_query: str,
        logic: str,
        top_k: int,
        include_descendants: bool
    ) -> Optional[RecommendationItem]:
        """단일 Intent 처리 (Include 또는 Exclude)"""
        
        # Stage 2: Search Pipeline
        candidates = self.stage2.search(intent_query, top_k=top_k * 2)  # 여유분
        
        if not candidates:
            logger.warning("No candidates found", query=intent_query)
            return None
        
        logger.info("Stage 2 complete", candidates=len(candidates))
        
        # Reranker
        rerank_result = self.reranker.rerank(intent_query, candidates, top_k)
        logger.info("Reranker complete", 
                    method=rerank_result.method, 
                    candidates=len(rerank_result.candidates),
                    confidence=f"{rerank_result.confidence:.3f}")
        
        # Expression Builder
        recommendation = self.expression_builder.build_expression(
            rerank_result.candidates,
            roll_up=include_descendants,
            default_logic=logic,
            criterion_name=intent_query,
        )
        
        logger.info("Expression built", items=len(recommendation.expression.items))
        
        return recommendation


# Lazy singleton
_recommender: Optional[ConceptSetRecommender] = None


def get_recommender() -> ConceptSetRecommender:
    """Get ConceptSet Recommender instance (lazy initialization)."""
    global _recommender
    if _recommender is None:
        _recommender = ConceptSetRecommender()
    return _recommender

