"""
ConceptSet Recommendation System - Expression Builder

Phase 4: 추천 결과를 ATLAS ConceptSet Expression 형태로 변환
RFC-001 v2.1 Section 2.2 (Roll-up 최적화) 구현
"""
import logging
import os
import time
from typing import List, Optional, Literal

logger = logging.getLogger(__name__)
from pydantic import BaseModel, ConfigDict, Field
from contextlib import contextmanager

from sqlalchemy import text
from src.utils.db import SessionLocal
from src.agents.conceptset.rag_search import ConceptCandidate


@contextmanager
def get_db_session():
    """Database session context manager"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# ATLAS ConceptSet Expression Models
# ============================================================================

class ConceptExpression(BaseModel):
    """
    ATLAS ConceptSet Expression 단일 항목.
    
    RFC-001 Section 2.2: Roll-up 최적화
    - includeDescendants: True로 설정하여 하위 개념 자동 포함
    - isExcluded: ConceptSet 내부 제외 표시
    """
    concept_id: int = Field(alias="CONCEPT_ID")
    concept_name: str = Field(alias="CONCEPT_NAME")
    domain_id: str = Field(alias="DOMAIN_ID")
    vocabulary_id: str = Field(alias="VOCABULARY_ID")
    concept_class_id: str = Field(alias="CONCEPT_CLASS_ID")
    standard_concept: str = Field(default="S", alias="STANDARD_CONCEPT")
    concept_code: str = Field(default="", alias="CONCEPT_CODE")
    
    # ConceptSet Expression 속성
    includeDescendants: bool = Field(default=True)
    includeMapped: bool = Field(default=False)
    isExcluded: bool = Field(default=False)
    
    model_config = ConfigDict(populate_by_name=True)


class ConceptSetExpression(BaseModel):
    """
    ATLAS ConceptSet 전체 Expression.
    """
    items: List[ConceptExpression] = Field(default_factory=list)
    
    @staticmethod
    def _standard_concept_caption(code: str) -> str:
        """Map single-character standard_concept code to human-readable caption."""
        return {"S": "Standard", "C": "Classification"}.get(code, "Non-Standard")

    def to_atlas_json(self) -> dict:
        """ATLAS 호환 JSON 형식으로 변환"""
        return {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": item.concept_id,
                        "CONCEPT_NAME": item.concept_name,
                        "DOMAIN_ID": item.domain_id,
                        "VOCABULARY_ID": item.vocabulary_id,
                        "CONCEPT_CLASS_ID": item.concept_class_id,
                        "STANDARD_CONCEPT": item.standard_concept,
                        "STANDARD_CONCEPT_CAPTION": self._standard_concept_caption(
                            item.standard_concept
                        ),
                        "CONCEPT_CODE": item.concept_code,
                        "INVALID_REASON": None,
                        "INVALID_REASON_CAPTION": None,
                    },
                    "includeDescendants": item.includeDescendants,
                    "includeMapped": item.includeMapped,
                    "isExcluded": item.isExcluded
                }
                for item in self.items
            ]
        }


class RecommendationItem(BaseModel):
    """
    API 응답용 추천 항목.
    
    RFC-001 Section 2.2.A: defaultLogic 태깅
    """
    conceptSetId: Optional[int] = None
    name: str
    expression: ConceptSetExpression
    defaultLogic: Literal["INCLUDE", "EXCLUDE"] = "INCLUDE"
    reason: Optional[str] = None


# ============================================================================
# Expression Builder
# ============================================================================

class ExpressionBuilder:
    """
    추천 결과를 ATLAS ConceptSet Expression으로 변환.
    
    주요 기능:
    1. Flat List → Roll-up: 하위 개념들을 상위 개념 + includeDescendants로 압축
    2. Standard Concept 검증: 비표준 개념 필터링
    3. defaultLogic 태깅: Include/Exclude 구분
    """
    
    def __init__(self, schema: Optional[str] = None):
        from src.settings import settings
        self.schema = schema or settings.CDM_SCHEMA
    
    def build_expression(
        self,
        candidates: List[ConceptCandidate],
        roll_up: bool = True,
        default_logic: Literal["INCLUDE", "EXCLUDE"] = "INCLUDE",
        criterion_name: Optional[str] = None,
    ) -> RecommendationItem:
        """
        ConceptCandidate 리스트를 Expression으로 변환.
        
        Args:
            candidates: Stage 2 결과
            roll_up: Roll-up 최적화 적용 여부
            default_logic: INCLUDE 또는 EXCLUDE
            
        Returns:
            RecommendationItem with Expression
        """
        if not candidates:
            return RecommendationItem(
                name="Empty",
                expression=ConceptSetExpression(items=[]),
                defaultLogic=default_logic
            )
        
        # Step 1: Standard Concept 검증
        validated = self._validate_standard_concepts(candidates)
        
        if not validated:
            logger.warning("[Expression Builder] No valid standard concepts")
            return RecommendationItem(
                name="No Valid Concepts",
                expression=ConceptSetExpression(items=[]),
                defaultLogic=default_logic
            )
        
        # Step 2: Roll-up 최적화 (선택적)
        if roll_up:
            optimized = self._roll_up(validated)
        else:
            optimized = validated
        
        # Step 3: Expression 생성
        items = []
        for candidate in optimized:
            items.append(ConceptExpression(
                concept_id=candidate.concept_id,
                concept_name=candidate.concept_name,
                domain_id=candidate.domain_id,
                vocabulary_id=candidate.vocabulary_id,
                concept_class_id=candidate.concept_class_id,
                includeDescendants=roll_up,
                isExcluded=(default_logic == "EXCLUDE")
            ))
        
        # 대표 이름: criterion_name이 있으면 사용, 없으면 첫 concept 이름
        primary_name = criterion_name or (optimized[0].concept_name if optimized else "Unknown")
        
        return RecommendationItem(
            name=primary_name,
            expression=ConceptSetExpression(items=items),
            defaultLogic=default_logic
        )
    
    def _validate_standard_concepts(
        self, 
        candidates: List[ConceptCandidate]
    ) -> List[ConceptCandidate]:
        """
        Standard Concept만 필터링.
        
        RFC-001 부록 B.2: includeDescendants는 Standard Concept에서만 동작
        """
        concept_ids = [c.concept_id for c in candidates]
        
        query = f"""
            SELECT concept_id
            FROM {self.schema}.concept
            WHERE concept_id = ANY(:ids)
              AND standard_concept = 'S'
              AND invalid_reason IS NULL
        """
        
        for attempt in range(2):
            try:
                with get_db_session() as db:
                    result = db.execute(text(query), {"ids": concept_ids})
                    valid_ids = {row.concept_id for row in result.fetchall()}

                validated = [c for c in candidates if c.concept_id in valid_ids]

                if len(validated) < len(candidates):
                    logger.info(f"[Expression Builder] Filtered {len(candidates) - len(validated)} non-standard concepts")

                return validated

            except Exception as e:
                if attempt == 0 and "QueuePool" in str(e):
                    logger.warning(f"[Expression Builder] Pool timeout on attempt 1, retrying in 2s: {e}")
                    time.sleep(2)
                    continue
                logger.warning(f"[Expression Builder] Validation error (attempt {attempt + 1}): {e}")
                return candidates  # Fallback: assume all valid
    
    def _filter_overbroad(
        self,
        candidates: List[ConceptCandidate],
    ) -> List[ConceptCandidate]:
        """Remove candidates whose descendant count exceeds the configured threshold.

        This prevents overbroad ancestors like "Clinical finding" or "Disease"
        from surviving roll-up and replacing clinically specific concepts.
        """
        threshold = int(os.environ.get("AGENT2_ROLLUP_MAX_DESCENDANTS", "500"))
        if len(candidates) <= 1:
            return candidates

        concept_ids = [c.concept_id for c in candidates]
        query = f"""
            SELECT ancestor_concept_id, COUNT(*) AS desc_count
            FROM {self.schema}.concept_ancestor
            WHERE ancestor_concept_id = ANY(:ids)
              AND ancestor_concept_id != descendant_concept_id
            GROUP BY ancestor_concept_id
            HAVING COUNT(*) > :threshold
        """

        try:
            with get_db_session() as db:
                result = db.execute(
                    text(query),
                    {"ids": concept_ids, "threshold": threshold},
                )
                overbroad_ids = {row.ancestor_concept_id for row in result.fetchall()}

            if overbroad_ids:
                candidate_map = {c.concept_id: c for c in candidates}
                for cid in overbroad_ids:
                    name = getattr(candidate_map.get(cid), "concept_name", cid)
                    logger.info(
                        "[Expression Builder] Filtered overbroad concept %s (%s) — descendants exceed %d",
                        cid,
                        name,
                        threshold,
                    )
                filtered = [c for c in candidates if c.concept_id not in overbroad_ids]
                if not filtered:
                    logger.info(
                        "[Expression Builder] All candidates were overbroad; keeping originals"
                    )
                    return candidates
                return filtered

            return candidates

        except Exception as e:
            logger.warning("[Expression Builder] Overbroad filter error: %s", e)
            return candidates

    def _roll_up(
        self,
        candidates: List[ConceptCandidate]
    ) -> List[ConceptCandidate]:
        """
        Roll-up 최적화: 중복되는 하위 개념을 상위 개념으로 압축.

        알고리즘:
        0. 과도하게 넓은 조상 개념 먼저 제거 (descendant_count 기준)
        1. 각 개념의 조상(ancestor) 확인
        2. 후보 중 조상이 있으면 해당 개념 제거
        3. 최상위 개념만 유지
        """
        candidates = self._filter_overbroad(candidates)

        if len(candidates) <= 1:
            return candidates

        concept_ids = [c.concept_id for c in candidates]
        candidate_map = {c.concept_id: c for c in candidates}
        
        # 각 개념이 다른 후보의 하위 개념인지 확인
        query = f"""
            SELECT 
                descendant_concept_id,
                ancestor_concept_id
            FROM {self.schema}.concept_ancestor
            WHERE descendant_concept_id = ANY(:ids)
              AND ancestor_concept_id = ANY(:ids)
              AND descendant_concept_id != ancestor_concept_id
              AND min_levels_of_separation > 0
        """
        
        try:
            with get_db_session() as db:
                result = db.execute(text(query), {"ids": concept_ids})
                
                # 다른 후보의 하위 개념인 ID 수집
                descendant_ids = set()
                for row in result.fetchall():
                    descendant_ids.add(row.descendant_concept_id)
            
            # 상위 개념만 유지
            rolled_up = [
                c for c in candidates 
                if c.concept_id not in descendant_ids
            ]
            
            if len(rolled_up) < len(candidates):
                logger.info(f"[Expression Builder] Rolled up {len(candidates)} → {len(rolled_up)} concepts")
            
            return rolled_up
            
        except Exception as e:
            logger.warning(f"[Expression Builder] Roll-up error: {e}")
            return candidates  # Fallback


# Lazy singleton
_expression_builder: Optional[ExpressionBuilder] = None


def get_expression_builder() -> ExpressionBuilder:
    """Get Expression Builder instance (lazy initialization)."""
    global _expression_builder
    if _expression_builder is None:
        _expression_builder = ExpressionBuilder()
    return _expression_builder
