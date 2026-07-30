"""
ConceptSet Recommendation System - PHOEBE Client

Phase 3: Stage 2 직렬 검색, 동시발생 기반 Concept 확장
RFC-001 v2.1 Section 2.2.D에 따른 구현
"""
import asyncio
from typing import List, Optional
from contextlib import contextmanager

from sqlalchemy import text
from src.utils.db import SessionLocal
from src.agents.conceptset.rag_search import ConceptCandidate
from src.settings import settings


@contextmanager
def get_db_session():
    """Database session context manager"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class PhoebeClient:
    """
    PHOEBE (PHenotype Observation Evaluation By Evidence) Client.
    
    concept_recommended 테이블을 활용하여 동시발생 기반 Concept 확장.
    Stage 1 결과의 Seed Concept을 기반으로 관련 Concept 추천.
    """
    
    # Read from settings, not hardcoded. settings.PHOEBE_SCHEMA existed and had
    # exactly one reference -- its own definition. The operator had set
    # PHOEBE_SCHEMA=omop_vocab in .env and in the container, and every call queried
    # demo_cdm anyway, with nothing logged. A configuration that is set, ignored, and
    # silent is worse than one that is absent: the absent one fails loudly on the
    # first call.
    SCHEMA = settings.PHOEBE_SCHEMA
    
    # Circuit Breaker 설정 (RFC-001 부록 B.3)
    DEFAULT_TIMEOUT_MS = 500
    
    def __init__(
        self, 
        schema: Optional[str] = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS
    ):
        self.schema = schema or self.SCHEMA
        self.timeout_ms = timeout_ms
    
    def get_recommendations(
        self, 
        seed_concept_id: int, 
        n_results: int = 10
    ) -> List[ConceptCandidate]:
        """
        단일 Seed Concept에 대한 추천 조회.
        
        Args:
            seed_concept_id: Seed Concept ID
            n_results: 최대 반환 수
            
        Returns:
            추천 ConceptCandidate 리스트
        """
        query = f"""
            SELECT 
                cr.concept_id_2 as concept_id,
                c.concept_name,
                c.domain_id,
                c.vocabulary_id,
                c.concept_class_id
            FROM {self.schema}.concept_recommended cr
            JOIN {self.schema}.concept c ON c.concept_id = cr.concept_id_2
            WHERE cr.concept_id_1 = :seed_id
              AND c.standard_concept = 'S'
              AND c.invalid_reason IS NULL
            LIMIT :limit
        """
        
        try:
            with get_db_session() as db:
                result = db.execute(text(query), {
                    "seed_id": seed_concept_id,
                    "limit": n_results
                })
                rows = result.fetchall()
                
                candidates = []
                for i, row in enumerate(rows):
                    # Score based on PHOEBE ranking
                    score = 1.0 / (1.0 + i * 0.1)
                    
                    candidates.append(ConceptCandidate(
                        concept_id=row.concept_id,
                        concept_name=row.concept_name,
                        domain_id=row.domain_id,
                        vocabulary_id=row.vocabulary_id,
                        concept_class_id=row.concept_class_id,
                        score=score,
                        source="phoebe"
                    ))
                
                return candidates
                
        except Exception as e:
            print(f"[PHOEBE] Query error: {e}")
            return []
    
    def expand_seeds(
        self, 
        seed_concept_ids: List[int], 
        n_results_per_seed: int = 5
    ) -> List[ConceptCandidate]:
        """
        여러 Seed Concept에 대한 추천 조회 및 통합.
        
        Args:
            seed_concept_ids: Seed Concept ID 리스트
            n_results_per_seed: 각 Seed당 최대 반환 수
            
        Returns:
            중복 제거된 추천 리스트
        """
        print(f"[PHOEBE] Expanding {len(seed_concept_ids)} seeds")
        
        all_recommendations = {}
        
        for seed_id in seed_concept_ids:
            recs = self.get_recommendations(seed_id, n_results_per_seed)
            for rec in recs:
                # 중복 시 더 높은 점수 유지
                if rec.concept_id not in all_recommendations:
                    all_recommendations[rec.concept_id] = rec
                elif rec.score > all_recommendations[rec.concept_id].score:
                    all_recommendations[rec.concept_id] = rec
        
        # 점수 순 정렬
        sorted_recs = sorted(
            all_recommendations.values(), 
            key=lambda x: x.score, 
            reverse=True
        )
        
        print(f"[PHOEBE] Expanded to {len(sorted_recs)} unique concepts")
        return sorted_recs
    
    async def expand_seeds_with_timeout(
        self, 
        seed_concept_ids: List[int], 
        n_results_per_seed: int = 5
    ) -> List[ConceptCandidate]:
        """
        Circuit Breaker 패턴 적용 비동기 확장.
        
        RFC-001 부록 B.3 구현:
        - 타임아웃 시 빈 리스트 반환 (Graceful Degradation)
        """
        try:
            # Run with timeout
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.expand_seeds(seed_concept_ids, n_results_per_seed)
                ),
                timeout=self.timeout_ms / 1000.0  # Convert ms to seconds
            )
            return result
            
        except asyncio.TimeoutError:
            print(f"[PHOEBE] Timeout ({self.timeout_ms}ms) - returning empty (Circuit Breaker)")
            return []


# Lazy singleton
_phoebe_client: Optional[PhoebeClient] = None


def get_phoebe_client() -> PhoebeClient:
    """Get PHOEBE Client instance (lazy initialization)."""
    global _phoebe_client
    if _phoebe_client is None:
        _phoebe_client = PhoebeClient()
    return _phoebe_client
