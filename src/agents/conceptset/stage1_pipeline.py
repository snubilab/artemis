"""
ConceptSet Recommendation System - Stage 1 Pipeline

Phase 2: RAG + Ontology 병렬 검색 → RRF 통합
RFC-001 v2.1 Section 2.1, 2.2.B에 따른 구현
"""
import asyncio
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from src.agents.conceptset.rag_search import RAGSearch, ConceptCandidate, get_rag_search
from src.agents.conceptset.ontology_search import OntologySearch, get_ontology_search
from src.agents.conceptset.rank_fusion import reciprocal_rank_fusion


class Stage1Pipeline:
    """
    Stage 1: Atomic Retrieval (병렬 실행)
    
    RAG와 Ontology 검색을 병렬로 실행하고 RRF로 통합.
    """
    
    def __init__(
        self, 
        rag_search: Optional[RAGSearch] = None,
        ontology_search: Optional[OntologySearch] = None
    ):
        self._rag_search = rag_search
        self._ontology_search = ontology_search
        self._executor = ThreadPoolExecutor(max_workers=2)
    
    @property
    def rag_search(self) -> RAGSearch:
        if self._rag_search is None:
            self._rag_search = get_rag_search()
        return self._rag_search
    
    @property
    def ontology_search(self) -> OntologySearch:
        if self._ontology_search is None:
            self._ontology_search = get_ontology_search()
        return self._ontology_search
    
    def search_sync(
        self, 
        query: str, 
        top_k: int = 20,
        domain_filter: Optional[str] = None
    ) -> List[ConceptCandidate]:
        """
        동기 방식 Stage 1 검색.
        
        ThreadPoolExecutor로 병렬 실행.
        """
        print(f"[Stage 1] Starting parallel search for: '{query}'")
        
        # Submit parallel tasks
        rag_future = self._executor.submit(
            self.rag_search.search, query, top_k, domain_filter
        )
        onto_future = self._executor.submit(
            self.ontology_search.search_by_name, query, top_k, domain_filter
        )
        
        # Wait for both
        rag_results = rag_future.result(timeout=5.0)
        onto_results = onto_future.result(timeout=5.0)
        
        print(f"[Stage 1] RAG: {len(rag_results)}, Ontology: {len(onto_results)}")
        
        # RRF Fusion
        fused = reciprocal_rank_fusion(rag_results, onto_results)
        
        # Return top-k
        top_results = fused[:top_k]
        print(f"[Stage 1] Fused {len(fused)} → Top-{len(top_results)}")
        
        return top_results
    
    async def search_async(
        self, 
        query: str, 
        top_k: int = 20,
        domain_filter: Optional[str] = None
    ) -> List[ConceptCandidate]:
        """
        비동기 방식 Stage 1 검색.
        
        asyncio.gather로 병렬 실행.
        """
        print(f"[Stage 1] Starting async parallel search for: '{query}'")
        
        loop = asyncio.get_event_loop()
        
        # Run searches in parallel using executor
        rag_task = loop.run_in_executor(
            self._executor,
            lambda: self.rag_search.search(query, top_k, domain_filter)
        )
        onto_task = loop.run_in_executor(
            self._executor,
            lambda: self.ontology_search.search_by_name(query, top_k, domain_filter)
        )
        
        rag_results, onto_results = await asyncio.gather(rag_task, onto_task)
        
        print(f"[Stage 1] RAG: {len(rag_results)}, Ontology: {len(onto_results)}")
        
        # RRF Fusion
        fused = reciprocal_rank_fusion(rag_results, onto_results)
        
        return fused[:top_k]
    
    def __del__(self):
        """Cleanup executor"""
        self._executor.shutdown(wait=False)


# Lazy singleton
_stage1_pipeline: Optional[Stage1Pipeline] = None


def get_stage1_pipeline() -> Stage1Pipeline:
    """Get Stage 1 Pipeline instance (lazy initialization)."""
    global _stage1_pipeline
    if _stage1_pipeline is None:
        _stage1_pipeline = Stage1Pipeline()
    return _stage1_pipeline
