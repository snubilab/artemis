"""
ConceptSet Recommendation System - Stage 1 Pipeline

Phase 2: RAG 검색 (RFC-001 v2.1 Section 2.1)

Stage 1 is the vector search alone. An ontology search used to run beside it and be
fused by rank: it matched the query inside ``concept_name`` with ``LIKE '%query%'``,
which reads vocabulary names as text (AGENTS.md § PROMPTS AND TEXT RULES, rule 2), and
with ten rows it could take half of the fused top ten. A failed vector search raises
(``RAGSearch.search``), so the caller records a failure instead of a mapping verdict.
"""
import asyncio
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from src.agents.conceptset.rag_search import RAGSearch, ConceptCandidate, get_rag_search


class Stage1Pipeline:
    """
    Stage 1: Atomic Retrieval -- the vector search.
    """

    def __init__(self, rag_search: Optional[RAGSearch] = None):
        self._rag_search = rag_search
        self._executor = ThreadPoolExecutor(max_workers=1)

    @property
    def rag_search(self) -> RAGSearch:
        if self._rag_search is None:
            self._rag_search = get_rag_search()
        return self._rag_search

    def search_sync(
        self,
        query: str,
        top_k: int = 20,
        domain_filter: Optional[str] = None
    ) -> List[ConceptCandidate]:
        """
        동기 방식 Stage 1 검색.

        The search runs on the executor so that a hung index raises ``TimeoutError``
        after five seconds instead of holding the mapping worker.
        """
        print(f"[Stage 1] Starting search for: '{query}'")

        rag_future = self._executor.submit(
            self.rag_search.search, query, top_k, domain_filter
        )
        rag_results = rag_future.result(timeout=5.0)

        top_results = rag_results[:top_k]
        print(f"[Stage 1] RAG: {len(rag_results)} → Top-{len(top_results)}")
        return top_results

    async def search_async(
        self,
        query: str,
        top_k: int = 20,
        domain_filter: Optional[str] = None
    ) -> List[ConceptCandidate]:
        """
        비동기 방식 Stage 1 검색.
        """
        print(f"[Stage 1] Starting async search for: '{query}'")

        loop = asyncio.get_event_loop()
        rag_results = await loop.run_in_executor(
            self._executor,
            lambda: self.rag_search.search(query, top_k, domain_filter)
        )

        print(f"[Stage 1] RAG: {len(rag_results)}")
        return rag_results[:top_k]

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
