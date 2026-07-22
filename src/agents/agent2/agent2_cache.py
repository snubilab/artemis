"""
Agent 2 Mapping Cache — JSON-based persistent cache for Agent 2 results.
Avoids re-running the expensive LLM/Neo4j pipeline for identical inputs.

Usage:
    cache = Agent2Cache()
    result = cache.get("Type 2 Diabetes", "Condition")
    if result is None:
        result = agent2.process("Type 2 Diabetes")
        cache.put("Type 2 Diabetes", "Condition", result)
"""
import json
import hashlib
import os
import logging
import threading
from typing import List, Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache")
CACHE_FILE = CACHE_DIR / "agent2_cache.json"


class Agent2Cache:
    """Simple JSON-file-based cache for Agent 2 mapping results."""

    def __init__(self, cache_path: Optional[Path] = None):
        self.cache_path = cache_path or CACHE_FILE
        self._cache: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """Load cache from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    self._cache = json.load(f)
                logger.info(f"[Cache] Loaded {len(self._cache)} entries from {self.cache_path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[Cache] Failed to load cache: {e}")
                self._cache = {}
        else:
            self._cache = {}

    def _save(self):
        """Persist cache to disk."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _key(entity_text: str, domain_hint: Optional[str] = None) -> str:
        """Generate cache key from entity text and domain hint."""
        raw = f"{entity_text.strip().lower()}|{(domain_hint or '').lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, entity_text: str, domain_hint: Optional[str] = None) -> Optional[List[int]]:
        """Look up cached concept IDs. Returns None on miss."""
        key = self._key(entity_text, domain_hint)
        with self._lock:
            entry = self._cache.get(key)
        if entry is not None:
            logger.debug(f"[Cache] HIT: {entity_text[:40]}")
            return entry["concept_ids"]
        return None

    def put(self, entity_text: str, domain_hint: Optional[str], concept_ids: List[int]):
        """Store mapping result in cache."""
        key = self._key(entity_text, domain_hint)
        with self._lock:
            self._cache[key] = {
                "entity_text": entity_text,
                "domain_hint": domain_hint,
                "concept_ids": concept_ids,
            }
            self._save()
        logger.debug(f"[Cache] PUT: {entity_text[:40]} → {len(concept_ids)} ids")

    def put_batch(self, entries: List[Dict[str, Any]]):
        """Store multiple entries at once (single write)."""
        with self._lock:
            for entry in entries:
                key = self._key(entry["entity_text"], entry.get("domain_hint"))
                self._cache[key] = {
                    "entity_text": entry["entity_text"],
                    "domain_hint": entry.get("domain_hint"),
                    "concept_ids": entry["concept_ids"],
                }
            self._save()
        logger.info(f"[Cache] PUT_BATCH: {len(entries)} entries")

    def clear(self):
        """Clear all cached entries."""
        with self._lock:
            self._cache = {}
            if self.cache_path.exists():
                self.cache_path.unlink()
        logger.info("[Cache] Cleared")

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)
