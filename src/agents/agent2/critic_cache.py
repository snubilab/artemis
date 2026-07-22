"""
Critic Result Cache — Thread-safe TTL+LRU cache for LLM Critic results.

Avoids redundant LLM calls for identical (query_text, domain_hint) pairs.
Cache key: sha256(query_text.lower().strip() + "|" + domain_hint)

Configuration:
    AGENT2_CRITIC_CACHE_TTL_HOURS: TTL in hours (default: 24)
    Max entries: 500 (LRU eviction)

Uses cachetools.TTLCache if available, otherwise falls back to a dict
with manual timestamp-based TTL enforcement.
"""

import hashlib
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Try cachetools for TTLCache+LRU; fallback to manual implementation
try:
    from cachetools import TTLCache as _TTLCache

    _HAS_CACHETOOLS = True
except ImportError:
    _HAS_CACHETOOLS = False


class CriticCache:
    """Thread-safe cache for Critic LLM evaluation results.

    Uses cachetools.TTLCache when available for efficient TTL+LRU eviction.
    Falls back to a dict with manual timestamp checks otherwise.

    Attributes:
        max_entries: Maximum cache entries before LRU eviction.
        ttl_hours: Time-to-live for cache entries in hours.
    """

    def __init__(
        self,
        max_entries: int = 500,
        ttl_hours: int | None = None,
    ):
        self.max_entries = max_entries
        self.ttl_hours = ttl_hours or int(
            os.environ.get("AGENT2_CRITIC_CACHE_TTL_HOURS", "24")
        )
        self._lock = threading.Lock()

        if _HAS_CACHETOOLS:
            self._cache = _TTLCache(
                maxsize=self.max_entries,
                ttl=self.ttl_hours * 3600,
            )
        else:
            # Fallback: dict with (value, expire_timestamp) tuples
            self._cache: dict[str, tuple[list[int], float]] = {}

    @staticmethod
    def make_key(query_text: str, domain_hint: str | None) -> str:
        """Generate cache key from query text and domain hint.

        Key = sha256(query_text.lower().strip() + "|" + domain_hint_or_empty)

        Args:
            query_text: Clinical query text.
            domain_hint: OMOP domain (e.g., "Condition") or None.

        Returns:
            Hex digest string for cache lookup.
        """
        normalized = query_text.lower().strip()
        domain = domain_hint or ""
        raw = f"{normalized}|{domain}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> list[int] | None:
        """Retrieve cached result.

        Returns:
            List of concept IDs if cache hit (including empty list), None on miss.
        """
        with self._lock:
            if _HAS_CACHETOOLS:
                result = self._cache.get(key)
                if result is not None:
                    logger.info(f"[CACHE HIT] Critic cache hit for key={key[:12]}...")
                    return result
                return None
            else:
                entry = self._cache.get(key)
                if entry is None:
                    return None
                value, expire_at = entry
                if time.time() > expire_at:
                    del self._cache[key]
                    return None
                logger.info(f"[CACHE HIT] Critic cache hit for key={key[:12]}...")
                return value

    def put(self, key: str, value: list[int]) -> None:
        """Store a result in the cache.

        Args:
            key: Cache key from make_key().
            value: List of concept IDs (may be empty).
        """
        with self._lock:
            if _HAS_CACHETOOLS:
                self._cache[key] = value
            else:
                # Manual LRU: evict oldest when at capacity
                if len(self._cache) >= self.max_entries and key not in self._cache:
                    # Evict the entry with the earliest expiry
                    oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                    del self._cache[oldest_key]
                expire_at = time.time() + self.ttl_hours * 3600
                self._cache[key] = (value, expire_at)

    @property
    def size(self) -> int:
        """Current number of entries in the cache."""
        with self._lock:
            return len(self._cache)
