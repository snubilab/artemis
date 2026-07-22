"""
Redis utility for ARTEMIS 3.1 Global Registry and State Management.
"""
import redis
from typing import Any, Optional
import json
from src.settings import settings


def get_redis_client() -> redis.Redis:
    """
    Returns a Redis client instance.
    """
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


class RegistryStore:
    """
    Global Registry for ConceptSets.
    Provides deduplication and fast lookup.
    """
    PREFIX = "artemis:registry"
    
    def __init__(self):
        self.client = get_redis_client()
    
    def register(self, concept_set_id: int, name: str, concept_ids: list[int]) -> str:
        """
        Register a ConceptSet in the global registry.
        Returns the key used for storage.
        """
        key = f"{self.PREFIX}:{concept_set_id}"
        data = {
            "id": concept_set_id,
            "name": name,
            "concept_ids": concept_ids
        }
        self.client.set(key, json.dumps(data))
        return key
    
    def get(self, concept_set_id: int) -> Optional[dict]:
        """
        Retrieve a ConceptSet by ID.
        """
        key = f"{self.PREFIX}:{concept_set_id}"
        data = self.client.get(key)
        if data:
            return json.loads(data)
        return None
    
    def exists(self, concept_set_id: int) -> bool:
        """
        Check if a ConceptSet exists.
        """
        key = f"{self.PREFIX}:{concept_set_id}"
        return self.client.exists(key) > 0
    
    def delete(self, concept_set_id: int) -> bool:
        """
        Delete a ConceptSet from registry.
        """
        key = f"{self.PREFIX}:{concept_set_id}"
        return self.client.delete(key) > 0
    
    def list_all(self) -> list[dict]:
        """
        List all registered ConceptSets.
        """
        keys = self.client.keys(f"{self.PREFIX}:*")
        results = []
        for key in keys:
            data = self.client.get(key)
            if data:
                results.append(json.loads(data))
        return results
    
    def clear(self) -> int:
        """
        Clear all registry entries. Returns count of deleted keys.
        """
        keys = self.client.keys(f"{self.PREFIX}:*")
        if keys:
            return self.client.delete(*keys)
        return 0


# Singleton instance
registry = RegistryStore()
