"""
ConceptSet Recommendation System - Ontology Search

Phase 2: Stage 1 병렬 검색 (Ontology 부분)
RFC-001 v2.1에 따른 구현 - OMOP concept_ancestor 활용
"""
from typing import List, Optional
from contextlib import contextmanager

from sqlalchemy import text
from src.utils.db import SessionLocal


@contextmanager
def get_db_session():
    """Database session context manager"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class OntologySearch:
    """
    OMOP CDM 기반 Ontology Search.
    
    concept_ancestor, concept_relationship 테이블을 활용하여
    계층적 관계의 Concept을 검색.
    """
    
    def __init__(self, max_levels: int = 3, schema: Optional[str] = None):
        """
        Args:
            max_levels: 최대 계층 깊이 (default: 3)
            schema: CDM 스키마 (default: settings.CDM_SCHEMA)
        """
        from src.settings import settings
        self.max_levels = max_levels
        self.schema = schema or settings.CDM_SCHEMA
    
    def get_descendants(
        self, 
        concept_id: int, 
        max_levels: Optional[int] = None
    ) -> List[int]:
        """
        concept_ancestor를 사용하여 하위 개념 조회.
        
        Args:
            concept_id: 상위 Concept ID
            max_levels: 최대 계층 깊이 (default: self.max_levels)
            
        Returns:
            하위 Concept ID 리스트
        """
        levels = max_levels or self.max_levels
        
        query = f"""
            SELECT ca.descendant_concept_id
            FROM {self.schema}.concept_ancestor ca
            JOIN {self.schema}.concept c ON c.concept_id = ca.descendant_concept_id
            WHERE ca.ancestor_concept_id = :concept_id
              AND ca.min_levels_of_separation <= :max_levels
              AND c.standard_concept = 'S'
              AND c.invalid_reason IS NULL
        """
        
        try:
            with get_db_session() as db:
                result = db.execute(text(query), {
                    "concept_id": concept_id,
                    "max_levels": levels
                })
                return [row.descendant_concept_id for row in result.fetchall()]
        except Exception as e:
            print(f"[Ontology Search] Descendant query error: {e}")
            return []
    
    def get_ancestors(
        self, 
        concept_id: int, 
        max_levels: Optional[int] = None
    ) -> List[int]:
        """
        concept_ancestor를 사용하여 상위 개념 조회.
        Roll-up 최적화를 위해 사용.
        
        Args:
            concept_id: 하위 Concept ID
            max_levels: 최대 계층 깊이
            
        Returns:
            상위 Concept ID 리스트
        """
        levels = max_levels or self.max_levels
        
        query = f"""
            SELECT ca.ancestor_concept_id
            FROM {self.schema}.concept_ancestor ca
            JOIN {self.schema}.concept c ON c.concept_id = ca.ancestor_concept_id
            WHERE ca.descendant_concept_id = :concept_id
              AND ca.min_levels_of_separation <= :max_levels
              AND c.standard_concept = 'S'
              AND c.invalid_reason IS NULL
            ORDER BY ca.min_levels_of_separation ASC
        """
        
        try:
            with get_db_session() as db:
                result = db.execute(text(query), {
                    "concept_id": concept_id,
                    "max_levels": levels
                })
                return [row.ancestor_concept_id for row in result.fetchall()]
        except Exception as e:
            print(f"[Ontology Search] Ancestor query error: {e}")
            return []


# Lazy singleton
_ontology_search: Optional[OntologySearch] = None


def get_ontology_search() -> OntologySearch:
    """Get Ontology Search instance (lazy initialization)."""
    global _ontology_search
    if _ontology_search is None:
        _ontology_search = OntologySearch()
    return _ontology_search
