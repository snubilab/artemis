"""Tests for CriterionResultCache — Agent2 criterion-level result caching."""

import os
import threading
import time
from pathlib import Path

import pytest

from src.agents.agent2.criterion_cache import (
    CriterionCacheEntry,
    CriterionResultCache,
    get_criterion_cache,
)


@pytest.fixture()
def cache() -> CriterionResultCache:
    """Fresh cache with short TTL for testing."""
    return CriterionResultCache(max_entries=5, ttl_hours=1.0)


@pytest.fixture()
def sample_entry() -> CriterionCacheEntry:
    return CriterionCacheEntry(
        concept_ids=[201826, 4329847],
        expression={"items": [{"concept": {"CONCEPT_ID": 201826}}]},
        mapping_metadata={"route": "slow", "critic_kept": 2},
        name="Type 2 diabetes mellitus",
        domain="Condition",
        route_path="slow",
        created_at="2026-03-29T12:00:00Z",
    )


class TestCriterionCacheEntry:
    def test_model_creation(self, sample_entry: CriterionCacheEntry) -> None:
        assert sample_entry.concept_ids == [201826, 4329847]
        assert sample_entry.domain == "Condition"
        assert sample_entry.name == "Type 2 diabetes mellitus"

    def test_model_optional_metadata(self) -> None:
        entry = CriterionCacheEntry(
            concept_ids=[100],
            expression={},
            name="test",
            domain="Drug",
            created_at="2026-01-01T00:00:00Z",
        )
        assert entry.mapping_metadata is None
        assert entry.route_path == ""


class TestBasicPutGetMiss:
    """T3.1: Basic put/get/miss."""

    def test_put_and_get(
        self,
        cache: CriterionResultCache,
        sample_entry: CriterionCacheEntry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
        cache.put("type 2 diabetes", "Condition", sample_entry)
        result = cache.get("type 2 diabetes", "Condition")
        assert result is not None
        assert result.concept_ids == [201826, 4329847]

    def test_miss_returns_none(
        self,
        cache: CriterionResultCache,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
        result = cache.get("nonexistent criterion")
        assert result is None

    def test_normalized_text_matches(
        self,
        cache: CriterionResultCache,
        sample_entry: CriterionCacheEntry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
        cache.put("  Type 2   Diabetes  ", "Condition", sample_entry)
        result = cache.get("type 2 diabetes", "Condition")
        assert result is not None


class TestTTLExpiration:
    """T3.2: TTL expiration."""

    def test_expired_entry_returns_none(
        self,
        sample_entry: CriterionCacheEntry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
        tiny_ttl_cache = CriterionResultCache(max_entries=5, ttl_hours=0.0001)
        tiny_ttl_cache.put("diabetes", "Condition", sample_entry)
        time.sleep(0.5)
        result = tiny_ttl_cache.get("diabetes", "Condition")
        assert result is None


class TestLRUEviction:
    """T3.3: LRU eviction when max_entries exceeded."""

    def test_evicts_oldest_when_full(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
        small_cache = CriterionResultCache(max_entries=3, ttl_hours=1.0)

        for i in range(4):
            entry = CriterionCacheEntry(
                concept_ids=[i],
                expression={},
                name=f"criterion_{i}",
                domain="Condition",
                created_at="2026-01-01T00:00:00Z",
            )
            small_cache.put(f"criterion {i}", "Condition", entry)

        stats = small_cache.stats()
        assert stats["current_size"] <= 3

        # First entry should have been evicted
        result = small_cache.get("criterion 0", "Condition")
        assert result is None


class TestThreadSafety:
    """T3.4: Concurrent put/get from multiple threads."""

    def test_concurrent_access(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
        cache = CriterionResultCache(max_entries=200, ttl_hours=1.0)
        errors: list[str] = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(20):
                    entry = CriterionCacheEntry(
                        concept_ids=[thread_id * 100 + i],
                        expression={},
                        name=f"t{thread_id}_c{i}",
                        domain="Condition",
                        created_at="2026-01-01T00:00:00Z",
                    )
                    cache.put(f"thread_{thread_id}_criterion_{i}", "Condition", entry)
            except Exception as exc:
                errors.append(f"writer {thread_id}: {exc}")

        def reader(thread_id: int) -> None:
            try:
                for i in range(20):
                    cache.get(f"thread_{thread_id}_criterion_{i}", "Condition")
            except Exception as exc:
                errors.append(f"reader {thread_id}: {exc}")

        threads = []
        for tid in range(8):
            threads.append(threading.Thread(target=writer, args=(tid,)))
            threads.append(threading.Thread(target=reader, args=(tid,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"


class TestEmbeddingModelKey:
    """T3.5: Different embedding_model produces cache miss."""

    def test_different_model_misses(
        self,
        cache: CriterionResultCache,
        sample_entry: CriterionCacheEntry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
        cache.put("diabetes", "Condition", sample_entry)

        monkeypatch.setenv("EMBEDDING_MODEL", "medcpt")
        result = cache.get("diabetes", "Condition")
        assert result is None


class TestStats:
    """T3.6: stats() returns correct hit/miss counts."""

    def test_stats_tracking(
        self,
        cache: CriterionResultCache,
        sample_entry: CriterionCacheEntry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")

        cache.put("diabetes", "Condition", sample_entry)
        cache.get("diabetes", "Condition")  # hit
        cache.get("nonexistent")  # miss
        cache.get("also missing", "Drug")  # miss

        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["current_size"] == 1


class TestSqlitePersistence:
    """Persistent sqlite-backed cache should survive new instances."""

    def test_sqlite_cache_reuses_entries_across_instances(
        self,
        sample_entry: CriterionCacheEntry,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
        db_path = tmp_path / "criterion-cache.sqlite"

        writer_cache = CriterionResultCache(max_entries=5, ttl_hours=1.0, db_path=str(db_path))
        writer_cache.put("History of Stroke", "Condition", sample_entry)

        reader_cache = CriterionResultCache(max_entries=5, ttl_hours=1.0, db_path=str(db_path))
        result = reader_cache.get("History of Stroke", "Condition")

        assert result is not None
        assert result.concept_ids == sample_entry.concept_ids
        assert reader_cache.stats()["current_size"] == 1


class TestClear:
    """T3.7: clear() removes all entries."""

    def test_clear_removes_all(
        self,
        cache: CriterionResultCache,
        sample_entry: CriterionCacheEntry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMBEDDING_MODEL", "minilm")

        cache.put("a", "Condition", sample_entry)
        cache.put("b", "Drug", sample_entry)
        cleared = cache.clear()
        assert cleared == 2

        stats = cache.stats()
        assert stats["current_size"] == 0
        assert cache.get("a", "Condition") is None


class TestSingleton:
    """Test get_criterion_cache singleton."""

    def test_returns_same_instance(self) -> None:
        import src.agents.agent2.criterion_cache as mod

        mod._instance = None
        c1 = get_criterion_cache()
        c2 = get_criterion_cache()
        assert c1 is c2

    def test_respects_env_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.agents.agent2.criterion_cache as mod

        mod._instance = None
        monkeypatch.setenv("CRITERION_CACHE_MAX_ENTRIES", "42")
        monkeypatch.setenv("CRITERION_CACHE_TTL_HOURS", "2.5")
        c = get_criterion_cache()
        assert c.max_entries == 42
        assert c.ttl_hours == 2.5
        mod._instance = None  # cleanup

    def test_respects_env_db_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import src.agents.agent2.criterion_cache as mod

        mod._instance = None
        db_path = tmp_path / "criterion-cache.sqlite"
        monkeypatch.setenv("CRITERION_CACHE_DB_PATH", str(db_path))
        c = get_criterion_cache()
        assert getattr(c, "_db_path", None) == db_path
        mod._instance = None
