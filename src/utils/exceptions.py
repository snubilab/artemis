"""
Custom exception hierarchy for ARTEMIS 3.1.

Phase 8 P1: Robust Error Handling.

Hierarchy:
    ArtemisError (base)
    ├── LLMError
    │   ├── LLMConfigurationError
    │   └── LLMRateLimitError
    ├── DatabaseError  
    │   ├── DBConnectionError
    │   └── DBQueryError
    ├── SearchError
    │   ├── VectorSearchError
    │   └── OntologySearchError
    └── ValidationError
        ├── ConceptValidationError
        └── ExpressionBuildError
"""
from typing import Optional


class ArtemisError(Exception):
    """Base exception for all ARTEMIS custom errors."""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.original_error = original_error
    
    def __str__(self) -> str:
        if self.original_error:
            return f"{self.message} (caused by: {self.original_error})"
        return self.message


# ============================================================================
# LLM Errors
# ============================================================================

class LLMError(ArtemisError):
    """Base class for LLM-related errors."""
    pass


class LLMConfigurationError(LLMError):
    """Missing API keys or invalid configuration."""
    pass


class LLMRateLimitError(LLMError):
    """Provider rate limits hit."""
    
    def __init__(self, message: str, retry_after: Optional[int] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class LLMTruncationError(LLMError):
    """The completion stopped at the token ceiling, not at an end-of-answer token.

    Its own class because the remedy is its own: a truncated body is a *prefix* of a
    valid answer, so no amount of parser tolerance can recover it and no prompt
    change fixes it either -- the model needs room. Raising ``ValueError`` here would
    put it in the same bucket as malformed generation, which is exactly the confusion
    that let a 16,384-token ceiling read as "the model cannot hold a JSON schema".

    :param prompt_tokens: tokens the request consumed, when the provider reported it.
    :param completion_tokens: tokens generated before the ceiling stopped it.
    :param body_path: file holding the generated prefix verbatim, when it was saved.
        The counts say how much was generated; only the body says WHAT, which is the
        difference between "needs more room" and "never terminated". Tens of thousands
        of tokens do not belong in an exception message, so the body goes to a file and
        the message carries its path.
    """

    def __init__(
        self,
        message: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        body_path: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.body_path = body_path


# ============================================================================
# Database Errors
# ============================================================================

class DatabaseError(ArtemisError):
    """Base class for Database-related errors."""
    pass


class DBConnectionError(DatabaseError):
    """Database connection failed."""
    pass


class DBQueryError(DatabaseError):
    """SQL execution failed."""
    
    def __init__(self, message: str, query: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.query = query


class DBTimeoutError(DatabaseError):
    """Database query timeout."""
    pass


# ============================================================================
# Search Errors
# ============================================================================

class SearchError(ArtemisError):
    """Base class for Search-related errors."""
    pass


class VectorSearchError(SearchError):
    """ChromaDB/Vector store operations failed."""
    pass


class OntologySearchError(SearchError):
    """OMOP CDM ontology search failed."""
    pass


class PHOEBEError(SearchError):
    """PHOEBE recommendation lookup failed."""
    pass


# ============================================================================
# Validation Errors
# ============================================================================

class ValidationError(ArtemisError):
    """Base class for validation errors."""
    pass


class ConceptValidationError(ValidationError):
    """Concept ID validation failed."""
    
    def __init__(self, message: str, concept_id: Optional[int] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.concept_id = concept_id


class ExpressionBuildError(ValidationError):
    """Cohort expression assembly failed."""
    pass


# ============================================================================
# Pipeline Errors
# ============================================================================

class PipelineError(ArtemisError):
    """Pipeline orchestration error."""
    pass


class IntentParsingError(PipelineError):
    """NLU intent parsing failed."""
    pass


class RerankerError(PipelineError):
    """Reranking step failed."""
    pass
