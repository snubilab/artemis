"""
ConceptSet Recommendation System - Reciprocal Rank Fusion (RRF)

Phase 2: 점수 통합 알고리즘
RFC-001 v2.1 Section 2.2.C에 따른 구현
"""
from typing import List, Dict
from collections import defaultdict

from src.agents.conceptset.rag_search import ConceptCandidate


def reciprocal_rank_fusion(
    *result_lists: List[ConceptCandidate],
    k: int = 60
) -> List[ConceptCandidate]:
    """
    Reciprocal Rank Fusion (RRF) 알고리즘.
    
    서로 다른 스케일의 점수를 등수(Rank) 기반으로 통합한다.
    
    Formula:
        Score(d) = Σ 1 / (k + rank(d))
    
    Args:
        result_lists: 여러 검색 결과 리스트 (RAG, Ontology 등)
        k: 스무딩 파라미터 (default: 60, 논문 표준)
        
    Returns:
        RRF 점수로 재순위화된 ConceptCandidate 리스트
    """
    rrf_scores: Dict[int, float] = defaultdict(float)
    concept_details: Dict[int, ConceptCandidate] = {}
    
    for results in result_lists:
        for rank, candidate in enumerate(results, start=1):
            # RRF score contribution
            rrf_scores[candidate.concept_id] += 1.0 / (k + rank)
            
            # Keep first appearance details (source tracking)
            if candidate.concept_id not in concept_details:
                concept_details[candidate.concept_id] = candidate
    
    # Sort by RRF score (descending)
    sorted_ids = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    
    # Build final list with updated scores
    fused_results = []
    for concept_id, rrf_score in sorted_ids:
        original = concept_details[concept_id]
        fused_results.append(ConceptCandidate(
            concept_id=original.concept_id,
            concept_name=original.concept_name,
            domain_id=original.domain_id,
            vocabulary_id=original.vocabulary_id,
            concept_class_id=original.concept_class_id,
            score=rrf_score,
            source="rrf"  # Mark as fused result
        ))
    
    return fused_results


def weighted_reciprocal_rank_fusion(
    *result_tuples: tuple[List[ConceptCandidate], float],
    k: int = 60
) -> List[ConceptCandidate]:
    """
    가중치 적용 RRF.
    
    Args:
        result_tuples: (결과 리스트, 가중치) 튜플들
        k: 스무딩 파라미터
        
    Returns:
        가중 RRF 점수로 재순위화된 리스트
        
    Example:
        weighted_reciprocal_rank_fusion(
            (rag_results, 1.5),    # RAG에 높은 가중치
            (ontology_results, 1.0)
        )
    """
    rrf_scores: Dict[int, float] = defaultdict(float)
    concept_details: Dict[int, ConceptCandidate] = {}
    
    for results, weight in result_tuples:
        for rank, candidate in enumerate(results, start=1):
            rrf_scores[candidate.concept_id] += weight * (1.0 / (k + rank))
            
            if candidate.concept_id not in concept_details:
                concept_details[candidate.concept_id] = candidate
    
    sorted_ids = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    
    fused_results = []
    for concept_id, rrf_score in sorted_ids:
        original = concept_details[concept_id]
        fused_results.append(ConceptCandidate(
            concept_id=original.concept_id,
            concept_name=original.concept_name,
            domain_id=original.domain_id,
            vocabulary_id=original.vocabulary_id,
            concept_class_id=original.concept_class_id,
            score=rrf_score,
            source="weighted_rrf"
        ))
    
    return fused_results
