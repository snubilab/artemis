"""
ConceptSet Recommendation System - RAG Search

Phase 2: Stage 1 병렬 검색 (RAG 부분)
RFC-001 v2.1에 따른 구현
"""
from typing import List, Optional
from pydantic import BaseModel, Field

from src.utils.vector import get_collection


class ConceptCandidate(BaseModel):
    """검색 후보 Concept"""
    concept_id: int
    concept_name: str
    domain_id: str = "Unknown"
    vocabulary_id: str = "Unknown"
    concept_class_id: str = "Unknown"
    score: float = Field(default=0.0, description="Similarity score (higher is better)")
    source: str = Field(default="rag", description="Source of candidate: rag, ontology, phoebe")


class RAGSearch:
    """
    ChromaDB 기반 Vector Search.
    
    기존 Agent2의 retriever.py 패턴을 재사용.
    """
    
    def __init__(self, collection_name: str = "omop_concepts"):
        self.collection_name = collection_name
        self._collection = None
    
    @property
    def collection(self):
        """Lazy loading of collection"""
        if self._collection is None:
            self._collection = get_collection(self.collection_name)
        return self._collection
    
    def search(
        self, 
        query_text: str, 
        n_results: int = 20,
        domain_filter: Optional[str] = None
    ) -> List[ConceptCandidate]:
        """
        Vector DB에서 의미적으로 유사한 ConceptSet 검색.
        
        Args:
            query_text: 검색 쿼리 (예: "Heart Failure")
            n_results: 반환할 최대 결과 수
            domain_filter: Domain 필터 (예: "Condition", "Drug")
            
        Returns:
            ConceptCandidate 리스트 (score 높은 순)
        """
        print(f"[RAG Search] Query: '{query_text}' (n={n_results})")
        
        try:
            # Build where clause for filtering
            where_clause = None
            if domain_filter:
                where_clause = {"domain_id": domain_filter}
            
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_clause,
                include=["metadatas", "distances", "documents"]
            )
        except Exception as e:
            print(f"[RAG Search] Failed (DB might be empty): {e}")
            return []
        
        candidates = []
        if results and results['ids'] and results['ids'][0]:
            ids = results['ids'][0]
            metadatas = results['metadatas'][0] if results.get('metadatas') else [{}] * len(ids)
            distances = results['distances'][0] if results.get('distances') else [1.0] * len(ids)
            documents = results['documents'][0] if results.get('documents') else [""] * len(ids)

            for i, cid in enumerate(ids):
                meta = metadatas[i] if i < len(metadatas) else {}
                dist = distances[i] if i < len(distances) else 1.0
                doc = documents[i] if i < len(documents) else ""

                # Convert distance to score (lower distance = higher score)
                # ChromaDB uses L2 distance by default
                score = 1.0 / (1.0 + dist)

                candidates.append(ConceptCandidate(
                    concept_id=int(cid),
                    concept_name=meta.get("concept_name") or doc or "Unknown",
                    domain_id=meta.get("domain_id", "Unknown"),
                    vocabulary_id=meta.get("vocabulary_id", "Unknown"),
                    concept_class_id=meta.get("concept_class_id", "Unknown"),
                    score=score,
                    source="rag"
                ))
        
        print(f"[RAG Search] Found {len(candidates)} candidates")
        return candidates


# Lazy singleton
_rag_search: Optional[RAGSearch] = None


def get_rag_search() -> RAGSearch:
    """Get RAG Search instance (lazy initialization)."""
    global _rag_search
    if _rag_search is None:
        _rag_search = RAGSearch()
    return _rag_search
