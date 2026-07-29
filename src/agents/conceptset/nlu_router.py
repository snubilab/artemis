"""
ConceptSet Recommendation System - NLU Router

Phase 1 구현: Intent 분리 (Include/Exclude) + Temporal Fallback
RFC-001 v2.1에 따른 구현
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from src.utils.llm import get_llm
from src.utils.logging import get_logger

# Module logger
logger = get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class IntentResult(BaseModel):
    """NLU Router의 출력 스키마"""
    include: List[str] = Field(
        default_factory=list,
        description="Conditions/Drugs the patient MUST have"
    )
    exclude: List[str] = Field(
        default_factory=list,
        description="Conditions/Drugs the patient MUST NOT have"
    )
    fallback_to: Optional[Literal["Agent1"]] = Field(
        default=None,
        description="If temporal/complex logic detected, fallback to Agent1"
    )
    fallback_reason: Optional[str] = Field(
        default=None,
        description="Reason for fallback"
    )


# ============================================================================
# Temporal Negation Detector
# ============================================================================

TEMPORAL_KEYWORDS = [
    "history of", "prior", "previous", "currently", "within",
    "before", "after", "at least", "at most", "days", "months", "years"
]


def detect_temporal_negation(query: str) -> bool:
    """
    시계열 로직이 포함된 쿼리 감지.
    RFC-001 부록 B.4에 따라 Agent1으로 Fallback 필요.
    """
    query_lower = query.lower()
    return any(kw in query_lower for kw in TEMPORAL_KEYWORDS)


# ============================================================================
# Intent Separator (LLM-based)
# ============================================================================

class IntentSeparator:
    """
    LLM 기반 Include/Exclude 의도 분리.
    RFC-001 Section 2.2.A 구현.
    """
    
    SYSTEM_PROMPT = """You are a medical terminology expert assisting in cohort definition.
Analyze the user's clinical request and separate it into:
1. 'include': Conditions/Drugs/Procedures the patient MUST have.
2. 'exclude': Conditions/Drugs/Procedures the patient MUST NOT have.

IMPORTANT:
- Extract ONLY medical concepts, not logical operators.
- If the query mentions "exclude", "without", "no", "but not" - put those terms in 'exclude'.
- Expand abbreviations when possible (e.g., "TZD" → "Thiazolidinediones").
- If no exclusions are mentioned, return an empty list for 'exclude'.

{format_instructions}"""

    USER_PROMPT = """User Input: {query}

Extract the include and exclude criteria as JSON."""

    def __init__(self):
        self.llm = get_llm(temperature=0.0, json_mode=True)
        self.parser = JsonOutputParser(pydantic_object=IntentResult)
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self.SYSTEM_PROMPT),
            ("user", self.USER_PROMPT)
        ])
        
        self.chain = self.prompt | self.llm | self.parser
    
    def separate(self, query: str) -> IntentResult:
        """
        자연어 쿼리에서 Include/Exclude 의도 분리.
        
        Args:
            query: 사용자 입력 (예: "Heart Failure but no TZD")
            
        Returns:
            IntentResult with include/exclude lists
        """
        try:
            result = self.chain.invoke({
                "query": query,
                "format_instructions": self.parser.get_format_instructions()
            })
            
            return IntentResult(**result)
            
        except Exception as e:
            logger.error("Intent separation failed", error=str(e), query=query)
            # Fallback: 전체 쿼리를 include로 처리
            return IntentResult(include=[query], exclude=[])


# ============================================================================
# NLU Router (Main Entry Point)
# ============================================================================

class NLURouter:
    """
    ConceptSet 추천 시스템의 첫 번째 관문.
    
    역할:
    1. Temporal 로직 감지 → Agent1 Fallback
    2. Include/Exclude 의도 분리
    3. 후속 검색 파이프라인으로 라우팅
    """
    
    def __init__(self):
        self.intent_separator = IntentSeparator()
    
    def route(self, query: str) -> IntentResult:
        """
        자연어 쿼리를 분석하여 적절한 처리 경로 결정.
        
        Args:
            query: 사용자 입력
            
        Returns:
            IntentResult with routing information
        """
        logger.info("Processing query", query=query)
        
        # Step 1: Temporal Fallback Check
        if detect_temporal_negation(query):
            logger.info("Temporal logic detected, fallback to Agent1", query=query)
            return IntentResult(
                include=[],
                exclude=[],
                fallback_to="Agent1",
                fallback_reason=f"Temporal logic detected in: '{query}'"
            )
        
        # Step 2: Intent Separation (LLM)
        result = self.intent_separator.separate(query)
        
        logger.info("Intent separated", include=result.include, exclude=result.exclude)
        
        return result


# Lazy singleton instance
_nlu_router: Optional[NLURouter] = None


def get_nlu_router() -> NLURouter:
    """Get the NLU Router instance (lazy initialization)."""
    global _nlu_router
    if _nlu_router is None:
        _nlu_router = NLURouter()
    return _nlu_router
