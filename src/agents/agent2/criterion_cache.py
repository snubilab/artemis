"""
Criterion Result Cache -- Thread-safe TTL+LRU cache for Agent2 mapping results.

Caches the full output of Agent2 mapping per criterion text so re-runs of
process_eligibility can skip Agent2 for unchanged criteria.

Cache key: SHA256(normalize(text) + "|" + domain + "|" + EMBEDDING_MODEL + "|" + LLM_MODEL)

Configuration (env vars):
    CRITERION_CACHE_TTL_HOURS:   TTL in hours (default: 24)
    CRITERION_CACHE_MAX_ENTRIES: Max entries before LRU eviction (default: 1000)
    CRITERION_CACHE_ENABLED:     Enable/disable flag (default: "true")
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.utils.llm import resolve_model

logger = logging.getLogger(__name__)


def _cache_enabled() -> bool:
    return os.environ.get("CRITERION_CACHE_ENABLED", "true").lower() == "true"

try:
    from cachetools import TTLCache as _TTLCache

    _HAS_CACHETOOLS = True
except ImportError:
    _HAS_CACHETOOLS = False


class CriterionCacheEntry(BaseModel):
    """Cached result of a single criterion mapping by Agent2."""

    concept_ids: list[int]
    expression: dict[str, Any]
    mapping_metadata: dict[str, Any] | None = None
    name: str
    domain: str
    route_path: str = ""
    created_at: str


_MULTI_SPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Normalize text for cache key: lowercase, strip, collapse whitespace."""
    return _MULTI_SPACE.sub(" ", text.lower().strip())


class CriterionResultCache:
    """Thread-safe cache for Agent2 criterion mapping results.

    Uses cachetools.TTLCache when available for efficient TTL+LRU eviction.
    Falls back to a dict with manual timestamp checks otherwise.
    """

    def __init__(
        self,
        max_entries: int = 1000,
        ttl_hours: float = 24.0,
        db_path: str | None = None,
    ):
        self.max_entries = max_entries
        self.ttl_hours = ttl_hours
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._db_path = Path(db_path).expanduser() if db_path else None

        if self._db_path is not None:
            self._cache = None
            self._init_sqlite()
        elif _HAS_CACHETOOLS:
            self._cache: Any = _TTLCache(
                maxsize=self.max_entries,
                ttl=self.ttl_hours * 3600,
            )
        else:
            self._cache: dict[str, tuple[CriterionCacheEntry, float]] = {}

    def _connect(self) -> sqlite3.Connection:
        assert self._db_path is not None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_sqlite(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS criterion_cache (
                    key TEXT PRIMARY KEY,
                    entry_json TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    last_accessed REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_criterion_cache_expires_at "
                "ON criterion_cache (expires_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_criterion_cache_last_accessed "
                "ON criterion_cache (last_accessed)"
            )

    def _sqlite_delete_expired(self, conn: sqlite3.Connection, now: float) -> None:
        conn.execute("DELETE FROM criterion_cache WHERE expires_at <= ?", (now,))

    @staticmethod
    def _make_key(
        text: str, domain: str | None, embedding_model: str, llm_model: str
    ) -> str:
        """SHA256 hash of normalized(text) + domain + embedding_model + llm_model."""
        normalized = _normalize(text)
        raw = f"{normalized}|{domain or ''}|{embedding_model}|{llm_model}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _embedding_model(self) -> str:
        return os.environ.get("EMBEDDING_MODEL", "minilm")

    def _llm_model(self) -> str:
        return resolve_model()

    def get(self, text: str, domain: str | None = None) -> CriterionCacheEntry | None:
        """Return cached entry or None. Auto-reads EMBEDDING_MODEL/LLM_MODEL."""
        if not _cache_enabled():
            return None
        key = self._make_key(text, domain, self._embedding_model(), self._llm_model())
        with self._lock:
            if self._db_path is not None:
                now = time.time()
                with self._connect() as conn:
                    self._sqlite_delete_expired(conn, now)
                    row = conn.execute(
                        "SELECT entry_json FROM criterion_cache WHERE key = ?",
                        (key,),
                    ).fetchone()
                    if row is None:
                        self._misses += 1
                        return None
                    conn.execute(
                        "UPDATE criterion_cache SET last_accessed = ? WHERE key = ?",
                        (now, key),
                    )
                self._hits += 1
                logger.info("[CACHE HIT] Criterion cache hit for key=%s...", key[:12])
                return CriterionCacheEntry.model_validate(json.loads(row[0]))

            if _HAS_CACHETOOLS:
                entry = self._cache.get(key)
                if entry is not None:
                    self._hits += 1
                    logger.info("[CACHE HIT] Criterion cache hit for key=%s...", key[:12])
                    return entry
                self._misses += 1
                return None

            pair = self._cache.get(key)
            if pair is None:
                self._misses += 1
                return None
            entry, expire_at = pair
            if time.time() > expire_at:
                del self._cache[key]
                self._misses += 1
                return None
            self._hits += 1
            logger.info("[CACHE HIT] Criterion cache hit for key=%s...", key[:12])
            return entry

    def put(self, text: str, domain: str | None, entry: CriterionCacheEntry) -> None:
        """Store entry. Auto-reads EMBEDDING_MODEL/LLM_MODEL."""
        if not _cache_enabled():
            return
        key = self._make_key(text, domain, self._embedding_model(), self._llm_model())
        with self._lock:
            if self._db_path is not None:
                now = time.time()
                expires_at = now + self.ttl_hours * 3600
                entry_json = entry.model_dump_json()
                with self._connect() as conn:
                    self._sqlite_delete_expired(conn, now)
                    exists = conn.execute(
                        "SELECT 1 FROM criterion_cache WHERE key = ?",
                        (key,),
                    ).fetchone()
                    if exists is None:
                        count = conn.execute(
                            "SELECT COUNT(*) FROM criterion_cache"
                        ).fetchone()[0]
                        if count >= self.max_entries:
                            conn.execute(
                                "DELETE FROM criterion_cache WHERE key IN ("
                                "SELECT key FROM criterion_cache "
                                "ORDER BY last_accessed ASC LIMIT 1)"
                            )
                    conn.execute(
                        """
                        INSERT INTO criterion_cache (key, entry_json, expires_at, last_accessed)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            entry_json = excluded.entry_json,
                            expires_at = excluded.expires_at,
                            last_accessed = excluded.last_accessed
                        """,
                        (key, entry_json, expires_at, now),
                    )
                return

            if _HAS_CACHETOOLS:
                self._cache[key] = entry
            else:
                if len(self._cache) >= self.max_entries and key not in self._cache:
                    oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                    del self._cache[oldest_key]
                expire_at = time.time() + self.ttl_hours * 3600
                self._cache[key] = (entry, expire_at)

    def clear(self) -> int:
        """Clear all entries. Returns count cleared."""
        with self._lock:
            if self._db_path is not None:
                with self._connect() as conn:
                    count = conn.execute("SELECT COUNT(*) FROM criterion_cache").fetchone()[0]
                    conn.execute("DELETE FROM criterion_cache")
            else:
                count = len(self._cache)
                self._cache.clear()
            self._hits = 0
            self._misses = 0
            return count

    def stats(self) -> dict[str, Any]:
        """Return hit/miss counts, current size, max size."""
        with self._lock:
            if self._db_path is not None:
                now = time.time()
                with self._connect() as conn:
                    self._sqlite_delete_expired(conn, now)
                    current_size = conn.execute(
                        "SELECT COUNT(*) FROM criterion_cache"
                    ).fetchone()[0]
            else:
                current_size = len(self._cache)
            return {
                "hits": self._hits,
                "misses": self._misses,
                "current_size": current_size,
                "max_entries": self.max_entries,
                "ttl_hours": self.ttl_hours,
                "enabled": _cache_enabled(),
            }


def _default_db_path() -> str:
    configured = os.environ.get("CRITERION_CACHE_DB_PATH")
    if configured:
        return configured

    tte_store_path = os.environ.get("TTE_STORE_PATH")
    if tte_store_path:
        return str(Path(tte_store_path).expanduser().resolve().parent / "criterion_cache.sqlite")

    repo_root = Path(__file__).resolve().parents[3]
    return str(repo_root / "tmp" / "tte" / "criterion_cache.sqlite")


_instance: CriterionResultCache | None = None
_instance_lock = threading.Lock()


def get_criterion_cache() -> CriterionResultCache:
    """Return singleton CriterionResultCache instance."""
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is None:
            max_entries = int(os.environ.get("CRITERION_CACHE_MAX_ENTRIES", "1000"))
            ttl_hours = float(os.environ.get("CRITERION_CACHE_TTL_HOURS", "24"))
            _instance = CriterionResultCache(
                max_entries=max_entries,
                ttl_hours=ttl_hours,
                db_path=_default_db_path(),
            )
            logger.info(
                "CriterionResultCache initialized: max=%d, ttl=%.1fh, db=%s",
                max_entries,
                ttl_hours,
                _instance._db_path,
            )
        return _instance
