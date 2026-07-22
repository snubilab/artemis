"""
ConceptSet Recommendation System - Stage 2 Pipeline

Phase 3: Stage 1 결과 → PHOEBE 확장 → 통합
RFC-001 v2.1 아키텍처의 직렬 구조 구현
"""
import asyncio
from typing import List, Optional

from src.agents.conceptset.stage1_pipeline import Stage1Pipeline, get_stage1_pipeline
from src.agents.conceptset.phoebe_client import PhoebeClient, get_phoebe_client
from src.agents.conceptset.rag_search import ConceptCandidate
from src.agents.conceptset.rank_fusion import reciprocal_rank_fusion


class Stage2Pipeline:
    """
    Stage 2: PHOEBE 확장 (직렬 실행)
    
    Stage 1 결과를 받아 PHOEBE로 확장하고 최종 후보 생성.
    
    Flow:
        Query → Stage 1 (병렬) → Seed Concepts → PHOEBE (직렬) → Final Candidates
    """
    
    def __init__(
        self,
        stage1: Optional[Stage1Pipeline] = None,
        phoebe: Optional[PhoebeClient] = None
    ):
        self._stage1 = stage1
        self._phoebe = phoebe
    
    @property
    def stage1(self) -> Stage1Pipeline:
        if self._stage1 is None:
            self._stage1 = get_stage1_pipeline()
        return self._stage1
    
    @property
    def phoebe(self) -> PhoebeClient:
        if self._phoebe is None:
            self._phoebe = get_phoebe_client()
        return self._phoebe
    
    def search(
        self,
        query: str,
        top_k: int = 20,
        phoebe_per_seed: int = 5,
        domain_filter: Optional[str] = None
    ) -> List[ConceptCandidate]:
        """
        전체 검색 파이프라인 실행 (동기).
        
        Args:
            query: 검색 쿼리
            top_k: 최종 반환 수
            phoebe_per_seed: PHOEBE에서 Seed당 추천 수
            domain_filter: Domain 필터
            
        Returns:
            최종 ConceptCandidate 리스트
        """
        print(f"[Stage 2] Starting full pipeline for: '{query}'")
        
        # Step 1: Stage 1 (RAG + Ontology 병렬)
        stage1_results = self.stage1.search_sync(query, top_k, domain_filter)
        
        if not stage1_results:
            print("[Stage 2] Stage 1 returned no results")
            return []
        
        print(f"[Stage 2] Stage 1 returned {len(stage1_results)} candidates")
        
        # Step 2: Extract seed concept IDs
        seed_ids = [c.concept_id for c in stage1_results[:10]]  # Top 10 seeds
        
        # Step 3: PHOEBE Expansion (직렬)
        phoebe_results = self.phoebe.expand_seeds(seed_ids, phoebe_per_seed)
        
        print(f"[Stage 2] PHOEBE expanded to {len(phoebe_results)} candidates")
        
        # Step 4: Merge results (Stage 1 + PHOEBE) using RRF
        merged = reciprocal_rank_fusion(stage1_results, phoebe_results)
        
        # Step 5: Return top-k
        final_results = merged[:top_k]
        print(f"[Stage 2] Final: {len(final_results)} candidates")
        
        return final_results
    
    async def search_async(
        self,
        query: str,
        top_k: int = 20,
        phoebe_per_seed: int = 5,
        domain_filter: Optional[str] = None
    ) -> List[ConceptCandidate]:
        """
        전체 검색 파이프라인 실행 (비동기, Circuit Breaker 적용).
        """
        print(f"[Stage 2] Starting async pipeline for: '{query}'")
        
        # Step 1: Stage 1
        stage1_results = await self.stage1.search_async(query, top_k, domain_filter)
        
        if not stage1_results:
            return []
        
        # Step 2: Seed IDs
        seed_ids = [c.concept_id for c in stage1_results[:10]]
        
        # Step 3: PHOEBE with Circuit Breaker
        phoebe_results = await self.phoebe.expand_seeds_with_timeout(
            seed_ids, phoebe_per_seed
        )
        
        # Step 4: Merge
        if phoebe_results:
            merged = reciprocal_rank_fusion(stage1_results, phoebe_results)
        else:
            # PHOEBE timeout - use Stage 1 results only
            print("[Stage 2] PHOEBE skipped (timeout/empty) - using Stage 1 only")
            merged = stage1_results
        
        return merged[:top_k]


# Lazy singleton
_stage2_pipeline: Optional[Stage2Pipeline] = None


def get_stage2_pipeline() -> Stage2Pipeline:
    """Get Stage 2 Pipeline instance (lazy initialization)."""
    global _stage2_pipeline
    if _stage2_pipeline is None:
        _stage2_pipeline = Stage2Pipeline()
    return _stage2_pipeline
