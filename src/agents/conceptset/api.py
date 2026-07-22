"""
ConceptSet Recommendation System - FastAPI Router

Phase 7: REST API endpoints
Phase 8 P5: API Hardening (Exception Handlers + Error Codes)
RFC-001 v2.1 + Gemini CLI design review incorporated
"""
from typing import Optional, List, Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.agents.conceptset.recommender import get_recommender
from src.utils.logging import get_logger
from src.utils.exceptions import (
    ArtemisError,
    LLMConfigurationError,
    LLMRateLimitError,
    DBConnectionError,
    DBQueryError,
    VectorSearchError,
    ValidationError,
    IntentParsingError,
    RerankerError
)

logger = get_logger(__name__)


# ============================================================================
# Error Response Models (Phase 8 P5)
# ============================================================================

class ErrorDetail(BaseModel):
    """구조화된 에러 응답"""
    code: str
    message: str
    details: Optional[dict] = None


class ErrorResponse(BaseModel):
    """API 에러 응답 모델"""
    error: ErrorDetail


# Exception → HTTP Status 매핑
EXCEPTION_STATUS_MAP = {
    # 400: Bad Request
    ValidationError: 400,
    IntentParsingError: 400,
    
    # 422: Validation Error (Pydantic handles this)
    
    # 500: Internal Server Error
    RerankerError: 500,
    VectorSearchError: 500,
    DBQueryError: 500,
    
    # 503: Service Unavailable
    LLMConfigurationError: 503,
    LLMRateLimitError: 503,
    DBConnectionError: 503,
}


def get_error_code(exc: Exception) -> str:
    """Exception 클래스명을 ERROR_CODE로 변환"""
    class_name = type(exc).__name__
    # CamelCase → SNAKE_CASE
    import re
    return re.sub(r'(?<!^)(?=[A-Z])', '_', class_name).upper()


# ============================================================================
# API Models
# ============================================================================

class RecommendationOptions(BaseModel):
    """추천 옵션"""
    top_k: int = Field(default=10, ge=1, le=50, description="각 Intent당 반환할 최대 ConceptSet 수")
    include_descendants: bool = Field(default=True, description="Roll-up 최적화 (includeDescendants)")
    domains: Optional[List[str]] = Field(default=None, description="Domain 필터 (Condition, Drug, etc.)")
    use_cache: bool = Field(default=True, description="캐시 사용 여부")


class RecommendationRequest(BaseModel):
    """추천 요청"""
    query: str = Field(..., min_length=2, max_length=500, description="자연어 임상 기준")
    options: RecommendationOptions = Field(default_factory=RecommendationOptions)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "Heart Failure but exclude TZD",
                "options": {
                    "top_k": 10,
                    "include_descendants": True,
                    "domains": ["Condition", "Drug"],
                    "use_cache": True
                }
            }
        }
    )


class ConceptItem(BaseModel):
    """ATLAS Concept 항목"""
    CONCEPT_ID: int
    CONCEPT_NAME: str
    DOMAIN_ID: str
    VOCABULARY_ID: str
    CONCEPT_CLASS_ID: str
    STANDARD_CONCEPT: str = "S"
    CONCEPT_CODE: str = ""


class ExpressionItem(BaseModel):
    """ATLAS Expression 항목"""
    concept: ConceptItem
    includeDescendants: bool = True
    includeMapped: bool = False
    isExcluded: bool = False


class ConceptSetResult(BaseModel):
    """단일 ConceptSet 결과"""
    name: str
    expression: dict  # items array
    defaultLogic: Literal["INCLUDE", "EXCLUDE"]


class RecommendationResponse(BaseModel):
    """추천 응답"""
    query: str
    conceptSets: List[ConceptSetResult]
    cached: bool = False
    fallback: Optional[dict] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "Heart Failure but exclude TZD",
                "conceptSets": [
                    {
                        "name": "Heart Failure",
                        "expression": {"items": []},
                        "defaultLogic": "INCLUDE"
                    }
                ],
                "cached": False,
                "fallback": None
            }
        }
    )


# ============================================================================
# Router with Exception Handlers
# ============================================================================

router = APIRouter(
    prefix="/api/conceptset",
    tags=["ConceptSet Recommendation"]
)


def handle_artemis_error(exc: ArtemisError) -> JSONResponse:
    """ArtemisError를 구조화된 JSON 응답으로 변환"""
    status_code = EXCEPTION_STATUS_MAP.get(type(exc), 500)
    error_code = get_error_code(exc)
    
    logger.error("API error", 
                 error_code=error_code, 
                 status_code=status_code,
                 message=str(exc))
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": error_code,
                "message": str(exc),
                "details": getattr(exc, 'details', None)
            }
        }
    )


@router.post(
    "/recommend",
    response_model=RecommendationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        503: {"model": ErrorResponse, "description": "Service Unavailable"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"}
    },
    summary="자연어에서 ConceptSet 추천 생성",
    description="""
자연어 임상 기준을 ATLAS 호환 ConceptSet Expression으로 변환합니다.

**Features:**
- Include/Exclude 자동 분리 (NLU)
- RAG + Ontology 하이브리드 검색
- PHOEBE 동시발생 확장
- Clinical Cross-Encoder 리랭킹
- Roll-up 최적화
- Semantic Cache (7일 TTL)

**Example queries:**
- "Type 2 Diabetes Mellitus"
- "Heart Failure but exclude Thiazolidinediones"
- "Metformin OR Sulfonylureas, 당뇨 제외"
"""
)
async def recommend_conceptset(request: RecommendationRequest):
    """ConceptSet 추천 엔드포인트"""
    logger.info("Recommend request received", query=request.query)
    
    try:
        recommender = get_recommender()
        
        result = recommender.recommend(
            query=request.query,
            top_k=request.options.top_k,
            include_descendants=request.options.include_descendants,
            use_cache=request.options.use_cache
        )
        
        logger.info("Recommend complete", 
                    query=request.query,
                    includes=len(result.include_recommendations),
                    excludes=len(result.exclude_recommendations))
        
        return result.to_atlas_json()
        
    except ArtemisError as e:
        return handle_artemis_error(e)
    except Exception as e:
        logger.error("Unexpected error", error=str(e), type=type(e).__name__)
        raise HTTPException(status_code=500, detail=str(e))


class RecommendAndSaveRequest(BaseModel):
    """Recommend and save request"""
    query: str = Field(..., min_length=2, max_length=500)
    top_k: int = Field(default=3, ge=1, le=10)


class RecommendAndSaveResponse(BaseModel):
    """Recommend and save response"""
    id: int
    name: str


@router.post(
    "/recommend-and-save",
    response_model=RecommendAndSaveResponse,
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Recommend a concept set and save it to Atlas",
    description="Recommends the best concept set from a natural-language clinical criterion and saves it to Atlas WebAPI, returning the saved ID."
)
async def recommend_and_save_conceptset(request: RecommendAndSaveRequest):
    """Recommend a concept set and save it to Atlas WebAPI.

    Runs the recommender for the given query, picks the top result,
    POSTs it to Atlas WebAPI /conceptset/, and returns the saved ID + name.
    """
    import os
    import httpx

    logger.info("Recommend-and-save request", query=request.query)

    try:
        recommender = get_recommender()
        result = recommender.recommend(query=request.query, top_k=request.top_k, use_cache=False)
        atlas_json = result.to_atlas_json()

        if not atlas_json.get("conceptSets"):
            raise HTTPException(status_code=404, detail="No concept sets found")

        top = atlas_json["conceptSets"][0]
        name = top["name"]
        expression = top["expression"]

        webapi_url = os.environ.get("WEBAPI_URL", "http://ohdsi-webapi:8080/WebAPI")
        from urllib.parse import urlparse as _urlparse
        parsed_url = _urlparse(webapi_url)
        if parsed_url.scheme not in ('http', 'https'):
            raise HTTPException(status_code=500, detail="Invalid WEBAPI_URL configuration")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{webapi_url}/conceptset/",
                json={"name": name, "expression": expression}
            )
            if resp.status_code not in (200, 201):
                raise HTTPException(status_code=502, detail=f"Atlas WebAPI error: {resp.status_code}")
            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type:
                raise HTTPException(
                    status_code=502,
                    detail="Atlas WebAPI returned unexpected content type"
                )
            saved = resp.json()
            concept_set_id = saved.get("id")
            if not concept_set_id:
                raise HTTPException(status_code=502, detail="Atlas WebAPI returned no ID")

        logger.info("Recommend-and-save complete", concept_set_id=concept_set_id, name=name)
        return RecommendAndSaveResponse(id=concept_set_id, name=name)

    except HTTPException:
        raise
    except ArtemisError as e:
        return handle_artemis_error(e)
    except Exception as e:
        logger.error("Recommend-and-save error", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/health",
    summary="Health Check",
    description="API 상태 확인"
)
async def health_check():
    """헬스 체크"""
    return {
        "status": "healthy", 
        "service": "conceptset-recommender",
        "version": "1.0.0"
    }


# Global catch-all must stay last so specific endpoints match first.
@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
async def catch_all_handler(request: Request):
    """Fallback for unmatched routes"""
    raise HTTPException(status_code=404, detail="Endpoint not found")


# ============================================================================
# Optional: NLU Debug Endpoint
# ============================================================================

class NLUDebugRequest(BaseModel):
    """NLU 디버그 요청"""
    query: str


class NLUDebugResponse(BaseModel):
    """NLU 디버그 응답"""
    include: List[str]
    exclude: List[str]
    fallback_to: Optional[str] = None
    fallback_reason: Optional[str] = None


@router.post(
    "/debug/nlu",
    response_model=NLUDebugResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        503: {"model": ErrorResponse, "description": "LLM Unavailable"}
    },
    summary="NLU 파싱 결과 확인 (디버그용)",
    description="쿼리의 Include/Exclude 분리 결과를 확인합니다."
)
async def debug_nlu(request: NLUDebugRequest):
    """NLU 디버그 엔드포인트"""
    from src.agents.conceptset.nlu_router import get_nlu_router
    
    logger.info("NLU debug request", query=request.query)
    
    try:
        nlu = get_nlu_router()
        result = nlu.route(request.query)
        
        return NLUDebugResponse(
            include=result.include,
            exclude=result.exclude,
            fallback_to=result.fallback_to,
            fallback_reason=result.fallback_reason
        )
        
    except ArtemisError as e:
        return handle_artemis_error(e)
    except Exception as e:
        logger.error("NLU debug error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
