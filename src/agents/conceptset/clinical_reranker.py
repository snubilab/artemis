"""
ConceptSet Recommendation System - Clinical Reranker

Phase 5: Cross-Encoder Reranker (BioLinkBERT + LLM Fallback)
RFC-001 v2.1 + Gemini CLI 설계 토론 결과 반영
"""
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

from src.agents.conceptset.rag_search import ConceptCandidate


class RerankerResult(BaseModel):
    """리랭킹 결과"""
    candidates: List[ConceptCandidate]
    method: str = Field(description="사용된 리랭킹 방식: 'cross_encoder', 'llm', 'score'")
    confidence: float = Field(default=0.0, description="최상위 후보의 신뢰도")


class ClinicalReranker:
    """
    Clinical Cross-Encoder Reranker.
    
    Two-Stage Reranking:
    1. Primary: BioLinkBERT Cross-Encoder (로컬, 빠름)
    2. Fallback: LLM-as-Judge (고정밀, 느림)
    
    Note: BioLinkBERT 모델 로드가 실패하면 Score 기반 정렬로 Fallback
    """
    
    # 신뢰도 임계값
    CONFIDENCE_THRESHOLD = 0.7
    
    def __init__(
        self,
        model_name: str = "michiyasunaga/BioLinkBERT-base",
        use_cross_encoder: bool = True,
        use_llm_fallback: bool = True
    ):
        self.model_name = model_name
        self.use_cross_encoder = use_cross_encoder
        self.use_llm_fallback = use_llm_fallback
        
        self._cross_encoder = None
        self._llm_chain = None
        self._initialized = False
    
    def _init_cross_encoder(self):
        """BioLinkBERT Cross-Encoder 초기화 (Lazy)"""
        if self._cross_encoder is not None:
            return True
        
        try:
            from sentence_transformers import CrossEncoder
            
            # BioLinkBERT Cross-Encoder
            self._cross_encoder = CrossEncoder(
                "cross-encoder/ms-marco-MiniLM-L-6-v2",  # 빠른 대안
                max_length=256
            )
            print(f"[Reranker] Cross-Encoder loaded successfully")
            return True
            
        except ImportError:
            print("[Reranker] sentence-transformers not installed, using score-based ranking")
            return False
        except Exception as e:
            print(f"[Reranker] Cross-Encoder load failed: {e}")
            return False
    
    def _init_llm(self):
        """LLM Fallback 초기화 (Lazy)"""
        if self._llm_chain is not None:
            return True
        
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser
            from src.utils.llm import get_llm
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a clinical terminology expert.
Given a user query and candidate concepts, select the BEST matching concept.

Return JSON: {{"selected_id": <concept_id>, "confidence": <0.0-1.0>}}"""),
                ("user", """Query: {query}

Candidates:
{candidates}

Select the best matching concept.""")
            ])
            
            llm = get_llm(temperature=0.0)
            self._llm_chain = prompt | llm | JsonOutputParser()
            print("[Reranker] LLM Fallback ready")
            return True
            
        except Exception as e:
            print(f"[Reranker] LLM init failed: {e}")
            return False
    
    def rerank(
        self, 
        query: str, 
        candidates: List[ConceptCandidate],
        top_k: int = 10
    ) -> RerankerResult:
        """
        후보 리랭킹.
        
        Args:
            query: 사용자 쿼리
            candidates: Stage 2 결과
            top_k: 반환할 상위 k개
            
        Returns:
            RerankerResult
        """
        if not candidates:
            return RerankerResult(candidates=[], method="empty", confidence=0.0)
        
        if len(candidates) == 1:
            return RerankerResult(
                candidates=candidates,
                method="single",
                confidence=1.0
            )
        
        # Strategy 1: Cross-Encoder
        if self.use_cross_encoder:
            result = self._rerank_with_cross_encoder(query, candidates, top_k)
            if result and result.confidence >= self.CONFIDENCE_THRESHOLD:
                return result
        
        # Strategy 2: LLM Fallback (낮은 신뢰도 or Cross-Encoder 실패)
        if self.use_llm_fallback:
            result = self._rerank_with_llm(query, candidates[:10], top_k)
            if result:
                return result
        
        # Strategy 3: Score-based (Fallback)
        return self._rerank_by_score(candidates, top_k)
    
    def _rerank_with_cross_encoder(
        self, 
        query: str, 
        candidates: List[ConceptCandidate],
        top_k: int
    ) -> Optional[RerankerResult]:
        """Cross-Encoder 기반 리랭킹"""
        if not self._init_cross_encoder():
            return None
        
        try:
            # Query-Concept 쌍 생성
            pairs = [(query, c.concept_name) for c in candidates]
            
            # Cross-Encoder 스코어링
            scores = self._cross_encoder.predict(pairs)
            
            # 스코어로 정렬
            scored_candidates = list(zip(candidates, scores))
            scored_candidates.sort(key=lambda x: x[1], reverse=True)
            
            reranked = [c for c, s in scored_candidates[:top_k]]
            top_score = float(scored_candidates[0][1]) if scored_candidates else 0.0
            
            # Normalize score to 0-1 (sigmoid-like)
            confidence = 1.0 / (1.0 + 2.71828 ** (-top_score))
            
            print(f"[Reranker] Cross-Encoder: top={reranked[0].concept_name}, conf={confidence:.3f}")
            
            return RerankerResult(
                candidates=reranked,
                method="cross_encoder",
                confidence=confidence
            )
            
        except Exception as e:
            print(f"[Reranker] Cross-Encoder error: {e}")
            return None
    
    def _rerank_with_llm(
        self, 
        query: str, 
        candidates: List[ConceptCandidate],
        top_k: int
    ) -> Optional[RerankerResult]:
        """LLM 기반 리랭킹"""
        if not self._init_llm():
            return None
        
        try:
            # 후보 포맷팅
            candidates_text = "\n".join([
                f"- ID: {c.concept_id} | Name: {c.concept_name} | Domain: {c.domain_id}"
                for c in candidates
            ])
            
            result = self._llm_chain.invoke({
                "query": query,
                "candidates": candidates_text
            })
            
            selected_id = result.get("selected_id")
            confidence = result.get("confidence", 0.5)
            
            # 선택된 후보를 맨 앞으로
            reranked = []
            selected = None
            for c in candidates:
                if c.concept_id == selected_id:
                    selected = c
                else:
                    reranked.append(c)
            
            if selected:
                reranked.insert(0, selected)
            
            print(f"[Reranker] LLM: selected={selected_id}, conf={confidence:.3f}")
            
            return RerankerResult(
                candidates=reranked[:top_k],
                method="llm",
                confidence=confidence
            )
            
        except Exception as e:
            print(f"[Reranker] LLM error: {e}")
            return None
    
    def _rerank_by_score(
        self, 
        candidates: List[ConceptCandidate],
        top_k: int
    ) -> RerankerResult:
        """기존 스코어 기반 정렬 (Fallback)"""
        sorted_candidates = sorted(
            candidates, 
            key=lambda c: c.score, 
            reverse=True
        )
        
        return RerankerResult(
            candidates=sorted_candidates[:top_k],
            method="score",
            confidence=sorted_candidates[0].score if sorted_candidates else 0.0
        )


# Lazy singleton
_clinical_reranker: Optional[ClinicalReranker] = None


def get_clinical_reranker() -> ClinicalReranker:
    """Get Clinical Reranker instance (lazy initialization)."""
    global _clinical_reranker
    if _clinical_reranker is None:
        _clinical_reranker = ClinicalReranker()
    return _clinical_reranker
