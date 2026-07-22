"""
Semantic Cache Utility for ConceptSet Recommendations.

Phase 8 P3: Redis-backed caching with semantic hash keys.

Features:
- SHA256 hash of normalized query + options as cache key
- Pydantic model serialization
- 7-day TTL by default
- Graceful fallback if Redis unavailable
"""
import hashlib
import json
from typing import Optional, Any, TypeVar
from pydantic import BaseModel

from src.utils.logging import get_logger
from src.settings import settings

logger = get_logger(__name__)

# Type variable for Pydantic models
T = TypeVar('T', bound=BaseModel)

# Try to import Redis
try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    logger.warning("Redis not installed. Caching disabled.")


class SemanticCache:
    """
    Semantic hash-based cache with Redis backend.
    Falls back gracefully if Redis unavailable.
    """
    
    def __init__(
        self,
        prefix: Optional[str] = None,
        ttl: Optional[int] = None,
        enabled: Optional[bool] = None
    ):
        self.prefix = prefix or settings.REDIS_CACHE_PREFIX
        self.ttl = ttl or settings.CACHE_TTL_SECONDS
        self.enabled = enabled if enabled is not None else settings.CACHE_ENABLED
        self._client: Optional["redis.Redis"] = None
        self._connected = False
    
    def _get_client(self) -> Optional["redis.Redis"]:
        """Lazy initialization of Redis client."""
        if not HAS_REDIS or not self.enabled:
            return None
        
        if self._client is None:
            try:
                self._client = redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_timeout=2.0,
                    socket_connect_timeout=2.0
                )
                # Test connection
                self._client.ping()
                self._connected = True
                logger.info("Redis cache connected", url=settings.REDIS_URL)
            except Exception as e:
                logger.warning("Redis connection failed, caching disabled", error=str(e))
                self._client = None
                self._connected = False
        
        return self._client if self._connected else None
    
    @staticmethod
    def _normalize_query(query: str) -> str:
        """Normalize query for consistent hashing."""
        return query.lower().strip()
    
    @staticmethod
    def _generate_key(query: str, **options) -> str:
        """Generate cache key from query and options."""
        normalized = SemanticCache._normalize_query(query)
        sorted_options = json.dumps(options, sort_keys=True)
        content = f"{normalized}|{sorted_options}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def get(self, query: str, model_class: type[T], **options) -> Optional[T]:
        """
        Get cached result.
        
        Args:
            query: The search query
            model_class: Pydantic model class for deserialization
            **options: Additional options used in cache key
            
        Returns:
            Cached model instance or None
        """
        client = self._get_client()
        if not client:
            return None
        
        key = f"{self.prefix}{self._generate_key(query, **options)}"
        
        try:
            cached = client.get(key)
            if cached:
                logger.info("Cache hit", key=key[:8])
                return model_class.model_validate_json(cached)
        except Exception as e:
            logger.warning("Cache get failed", error=str(e))
        
        return None
    
    def set(self, query: str, value: BaseModel, **options) -> bool:
        """
        Store result in cache.
        
        Args:
            query: The search query
            value: Pydantic model to cache
            **options: Additional options used in cache key
            
        Returns:
            True if cached successfully
        """
        client = self._get_client()
        if not client:
            return False
        
        key = f"{self.prefix}{self._generate_key(query, **options)}"
        
        try:
            serialized = value.model_dump_json()
            client.setex(key, self.ttl, serialized)
            logger.info("Cache set", key=key[:8], ttl=self.ttl)
            return True
        except Exception as e:
            logger.warning("Cache set failed", error=str(e))
            return False
    
    def invalidate(self, query: str, **options) -> bool:
        """Invalidate a specific cache entry."""
        client = self._get_client()
        if not client:
            return False
        
        key = f"{self.prefix}{self._generate_key(query, **options)}"
        
        try:
            client.delete(key)
            logger.info("Cache invalidated", key=key[:8])
            return True
        except Exception as e:
            logger.warning("Cache invalidation failed", error=str(e))
            return False


# Singleton instance
_cache: Optional[SemanticCache] = None


def get_cache() -> SemanticCache:
    """Get the cache instance (lazy singleton)."""
    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache
