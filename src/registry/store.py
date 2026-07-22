"""
Enhanced Registry Store for ARTEMIS 3.1.
Redis-backed storage with Pydantic model integration and hash-based deduplication.
Falls back to in-memory storage if Redis is not available.
"""
from typing import Optional, List
import json
import logging
from datetime import datetime

from src.settings import settings
from src.registry.models import RegisteredConceptSet, RegisteredConcept, RegistryLookupResult, RegistryStats

logger = logging.getLogger(__name__)

# Optional Redis import
try:
    import redis
    HAS_REDIS = True
except ImportError as e:
    redis = None  # type: ignore
    HAS_REDIS = False
    logger.warning(
        "[RegistryStore] Redis package unavailable; using in-memory fallback. "
        f"error_type={type(e).__name__}"
    )


def get_redis_client() -> Optional["redis.Redis"]:
    """Returns a Redis client instance, or None if Redis is unavailable."""
    if not HAS_REDIS:
        return None
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()  # Test connection
        return client
    except Exception as e:
        logger.warning(
            "[RegistryStore] Redis connection failed; using in-memory fallback. "
            f"error_type={type(e).__name__} error={e}"
        )
        return None


class RegistryStore:
    """
    Global Registry for ConceptSets.
    Features:
    - Pydantic model integration
    - Hash-based deduplication
    - ID and hash indexing
    - In-memory fallback if Redis unavailable
    """
    PREFIX = "artemis:registry"
    HASH_INDEX = "artemis:registry:hash_index"
    ID_COUNTER = "artemis:registry:id_counter"
    
    def __init__(self):
        self.client = get_redis_client()
        self.use_redis = self.client is not None
        # In-memory fallback storage
        self._memory_store: dict = {}
        self._hash_index: dict = {}
        self._id_counter = 0
    
    def _next_id(self) -> int:
        """Generate next available ConceptSet ID."""
        if self.use_redis:
            return self.client.incr(self.ID_COUNTER)
        else:
            self._id_counter += 1
            return self._id_counter
    
    def register(
        self, 
        name: str, 
        concepts: List[RegisteredConcept],
        source_entity_text: Optional[str] = None,
        concept_set_id: Optional[int] = None
    ) -> RegistryLookupResult:
        """
        Register a ConceptSet. Returns existing if duplicate (by hash).
        """
        # Build ConceptSet to compute hash
        temp_cs = RegisteredConceptSet(
            id=concept_set_id or 0,
            name=name,
            concepts=concepts,
            source_entity_text=source_entity_text
        )
        cs_hash = temp_cs.compute_hash()
        
        # Check for duplicate by hash
        if self.use_redis:
            existing_id = self.client.hget(self.HASH_INDEX, cs_hash)
        else:
            existing_id = self._hash_index.get(cs_hash)
        
        if existing_id:
            existing_cs = self.get(int(existing_id))
            return RegistryLookupResult(
                found=True,
                concept_set=existing_cs,
                existing_id=int(existing_id)
            )
        
        # Create new entry
        new_id = concept_set_id or self._next_id()
        concept_set = RegisteredConceptSet(
            id=new_id,
            name=name,
            concepts=concepts,
            source_entity_text=source_entity_text,
            created_at=datetime.now().isoformat(),
            hash=cs_hash
        )
        
        # Store
        key = f"{self.PREFIX}:{new_id}"
        if self.use_redis:
            self.client.set(key, concept_set.model_dump_json())
            self.client.hset(self.HASH_INDEX, cs_hash, new_id)
        else:
            self._memory_store[key] = concept_set.model_dump_json()
            self._hash_index[cs_hash] = new_id
        
        return RegistryLookupResult(
            found=False,
            concept_set=concept_set
        )
    
    def get(self, concept_set_id: int) -> Optional[RegisteredConceptSet]:
        """Retrieve a ConceptSet by ID."""
        key = f"{self.PREFIX}:{concept_set_id}"
        if self.use_redis:
            data = self.client.get(key)
        else:
            data = self._memory_store.get(key)
        if data:
            return RegisteredConceptSet.model_validate_json(data)
        return None
    
    def get_by_hash(self, cs_hash: str) -> Optional[RegisteredConceptSet]:
        """Retrieve a ConceptSet by its content hash."""
        if self.use_redis:
            existing_id = self.client.hget(self.HASH_INDEX, cs_hash)
        else:
            existing_id = self._hash_index.get(cs_hash)
        if existing_id:
            return self.get(int(existing_id))
        return None
    
    def exists(self, concept_set_id: int) -> bool:
        """Check if a ConceptSet exists."""
        key = f"{self.PREFIX}:{concept_set_id}"
        if self.use_redis:
            return self.client.exists(key) > 0
        else:
            return key in self._memory_store
    
    def delete(self, concept_set_id: int) -> bool:
        """Delete a ConceptSet from registry."""
        cs = self.get(concept_set_id)
        if cs:
            key = f"{self.PREFIX}:{concept_set_id}"
            if self.use_redis:
                self.client.delete(key)
                if cs.hash:
                    self.client.hdel(self.HASH_INDEX, cs.hash)
            else:
                self._memory_store.pop(key, None)
                if cs.hash:
                    self._hash_index.pop(cs.hash, None)
            return True
        return False
    
    def list_all(self) -> List[RegisteredConceptSet]:
        """List all registered ConceptSets."""
        if self.use_redis:
            keys = self.client.keys(f"{self.PREFIX}:*")
            cs_keys = [k for k in keys if k.count(':') == 2 and 'index' not in k and 'counter' not in k]
            results = []
            for key in cs_keys:
                data = self.client.get(key)
                if data:
                    results.append(RegisteredConceptSet.model_validate_json(data))
            return results
        else:
            results = []
            for key, data in self._memory_store.items():
                if 'index' not in key and 'counter' not in key:
                    results.append(RegisteredConceptSet.model_validate_json(data))
            return results
    
    def get_stats(self) -> RegistryStats:
        """Get registry statistics."""
        all_cs = self.list_all()
        domains: dict = {}
        total_concepts = 0
        
        for cs in all_cs:
            total_concepts += len(cs.concepts)
            for concept in cs.concepts:
                domain = concept.domain_id
                domains[domain] = domains.get(domain, 0) + 1
        
        return RegistryStats(
            total_concept_sets=len(all_cs),
            total_concepts=total_concepts,
            domains=domains
        )
    
    def clear(self) -> int:
        """Clear all registry entries. Returns count of deleted keys."""
        if self.use_redis:
            keys = self.client.keys(f"{self.PREFIX}*")
            if keys:
                return self.client.delete(*keys)
            return 0
        else:
            count = len(self._memory_store)
            self._memory_store.clear()
            self._hash_index.clear()
            self._id_counter = 0
            return count


def get_registry() -> RegistryStore:
    """Get or create the global registry singleton (lazy initialization)."""
    global _registry
    if _registry is None:
        _registry = RegistryStore()
    return _registry


# Lazy singleton
_registry: Optional[RegistryStore] = None

# For backwards compatibility
registry = RegistryStore()
