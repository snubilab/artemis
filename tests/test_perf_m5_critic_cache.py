"""
SPEC-PERF-001 M5: Critic Result Cache — Tests for CriticCache class.

Tests:
- Cache key is sha256(query_text.lower().strip() + "|" + domain_hint)
- TTL: configurable via AGENT2_CRITIC_CACHE_TTL_HOURS (default: 24)
- Max entries: 500 (LRU eviction)
- Thread safety
- Cache hit/miss/eviction
"""

import hashlib
import os
import time
import threading
from unittest.mock import patch

import pytest

from src.agents.agent2.critic_cache import CriticCache
from src.utils.llm import resolve_model


class TestCacheKeyGeneration:
    """Verify cache key format."""

    def test_key_is_sha256_of_query_domain_and_model(self):
        """The key is a sha256 hex digest that varies with query, domain and model.

        Deliberately not a formula comparison: the key gained a critic-configuration
        component (tier and self-reflection) after a live probe showed three
        different critic models producing one key. Anything that must change the key
        should be asserted here as a property, not by rebuilding the input string.
        """
        cache = CriticCache(max_entries=10, ttl_hours=1)
        key = cache.make_key("test query", "Condition")

        assert len(key) == 64 and all(c in "0123456789abcdef" for c in key)
        assert key != cache.make_key("other query", "Condition")
        assert key != cache.make_key("test query", "Drug")

    def test_key_with_none_domain(self):
        """None domain is treated as empty string.

        Asserted as a property rather than by rebuilding the digest. The previous
        version duplicated the key formula, so it broke the moment a component was
        added -- and the component added was the critic configuration, without which
        a mapping cached under one critic model replayed under another. A test that
        pins the formula makes the fix for that look like a regression.
        """
        cache = CriticCache(max_entries=10, ttl_hours=1)

        assert cache.make_key("test query", None) == cache.make_key("test query", "")

    def test_key_is_case_insensitive(self):
        """Same query with different case should produce same key."""
        cache = CriticCache(max_entries=10, ttl_hours=1)
        key1 = cache.make_key("History of Stroke", "Condition")
        key2 = cache.make_key("history of stroke", "Condition")
        assert key1 == key2


class TestCacheHitMiss:
    """Verify cache hit and miss behavior."""

    def test_cache_miss_returns_none(self):
        """Non-existent key should return None."""
        cache = CriticCache(max_entries=10, ttl_hours=1)
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_hit_returns_stored_value(self):
        """Stored value should be retrievable."""
        cache = CriticCache(max_entries=10, ttl_hours=1)
        key = cache.make_key("stroke", "Condition")
        cache.put(key, [1, 2, 3])
        result = cache.get(key)
        assert result == [1, 2, 3]

    def test_cache_stores_empty_list(self):
        """Empty list result should be cacheable (not confused with miss)."""
        cache = CriticCache(max_entries=10, ttl_hours=1)
        key = cache.make_key("rare query", "Condition")
        cache.put(key, [])
        result = cache.get(key)
        assert result == []  # not None


class TestCacheTTL:
    """Verify TTL expiration behavior."""

    def test_expired_entry_returns_none(self):
        """Entry past TTL should return None."""
        cache = CriticCache(max_entries=10, ttl_hours=0)  # instant expiry
        key = cache.make_key("test", "Condition")
        cache.put(key, [1, 2, 3])
        time.sleep(0.01)
        result = cache.get(key)
        assert result is None

    def test_ttl_env_var_override(self):
        """AGENT2_CRITIC_CACHE_TTL_HOURS should override default."""
        with patch.dict(os.environ, {"AGENT2_CRITIC_CACHE_TTL_HOURS": "48"}):
            cache = CriticCache()
            assert cache.ttl_hours == 48


class TestCacheLRUEviction:
    """Verify max entries with LRU eviction."""

    def test_eviction_at_max_entries(self):
        """Oldest entry should be evicted when max entries exceeded."""
        cache = CriticCache(max_entries=3, ttl_hours=1)
        for i in range(4):
            key = cache.make_key(f"query_{i}", "Condition")
            cache.put(key, [i])

        # First entry should be evicted
        key0 = cache.make_key("query_0", "Condition")
        assert cache.get(key0) is None

        # Last 3 should still be there
        for i in range(1, 4):
            key = cache.make_key(f"query_{i}", "Condition")
            assert cache.get(key) == [i]

    def test_max_entries_default_is_500(self):
        """Default max_entries should be 500."""
        cache = CriticCache()
        assert cache.max_entries == 500


class TestCacheThreadSafety:
    """Verify thread-safe concurrent access."""

    def test_concurrent_writes_do_not_corrupt(self):
        """Concurrent writes should not corrupt the cache."""
        cache = CriticCache(max_entries=100, ttl_hours=1)
        errors = []

        def writer(thread_id: int):
            try:
                for i in range(50):
                    key = cache.make_key(f"t{thread_id}_q{i}", "Condition")
                    cache.put(key, [thread_id, i])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent write errors: {errors}"
