"""
Critic Result Cache — Thread-safe TTL+LRU cache for LLM Critic results.

Avoids redundant LLM calls for identical critic calls. The key is everything the
answer depends on: the query (case-folded), the context shown before it, the domain, the
resolved model, critic_signature() (model tier, self-reflection, prompt version), the seed
ids, the KG candidate ids and kg_concept_ids. The id lists are sorted, so the same call
with its ids in another order is the same key.

It used to be the query and domain alone. In the P2 NEW re-ingest (2026-10-12) a second
'CABG' call with a different seed set was answered from the first call's entry, so the
critic never saw seed 4231998 and the replayed selection carried 4000733, a seed of the
other call.

Configuration:
    AGENT2_CRITIC_CACHE_TTL_HOURS: TTL in hours (default: 24)
    Max entries: 500 (LRU eviction)

Uses cachetools.TTLCache if available, otherwise falls back to a dict
with manual timestamp-based TTL enforcement.
"""

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Iterable

from src.utils.llm import resolve_model

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
    def make_key(
        query_text: str,
        domain_hint: str | None,
        *,
        context: str | None,
        seed_concept_ids: Iterable[int],
        candidate_concept_ids: Iterable[int],
        kg_concept_ids: Iterable[int] | None,
    ) -> str:
        """Cache key over every input of one critic call.

        Every argument is required so that no call site can build a key without the
        candidates the answer was chosen from.

        :param query_text: clinical query text; case-folded and stripped.
        :param domain_hint: OMOP domain (e.g. "Condition") or None.
        :param context: text shown before the query in the prompt, or None.
        :param seed_concept_ids: the seeds shown to the critic.
        :param candidate_concept_ids: the KG candidates shown to the critic.
        :param kg_concept_ids: the ids whose contradicted verdicts the filter may keep,
            or None for no such set.
        :returns: hex digest.
        """
        # resolve_model() alone was not enough: AGENT2_CRITIC_MODEL_TIER can point
        # the critic at a different model entirely while LLM_MODEL stays put.
        from src.agents.agent2.critic import critic_signature

        raw = json.dumps([
            query_text.lower().strip(),
            context or "",
            domain_hint or "",
            resolve_model(),
            critic_signature(),
            sorted(int(cid) for cid in seed_concept_ids),
            sorted(int(cid) for cid in candidate_concept_ids),
            None if kg_concept_ids is None else sorted(int(cid) for cid in kg_concept_ids),
        ])
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
