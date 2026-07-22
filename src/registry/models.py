"""
Registry data models for ARTEMIS 3.1.
Pydantic models for ConceptSet registration and deduplication.
"""
from typing import List, Optional
from pydantic import BaseModel, Field
import hashlib
import json


class RegisteredConcept(BaseModel):
    """A single concept within a registered ConceptSet."""
    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str = ""
    standard_concept: str = "S"
    include_descendants: bool = True
    is_excluded: bool = False


class RegisteredConceptSet(BaseModel):
    """
    A registered ConceptSet in the global registry.
    Includes hash for deduplication.
    """
    id: int
    name: str
    concepts: List[RegisteredConcept]
    source_entity_text: Optional[str] = None  # Original text before mapping
    created_at: Optional[str] = None
    hash: Optional[str] = None
    
    def compute_hash(self) -> str:
        """
        Compute a deterministic hash based on concept IDs.
        Used for deduplication.
        """
        concept_ids = sorted([c.concept_id for c in self.concepts])
        hash_input = json.dumps(concept_ids, sort_keys=True)
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    def model_post_init(self, __context) -> None:
        """Auto-compute hash after initialization."""
        if self.hash is None:
            self.hash = self.compute_hash()


class RegistryLookupResult(BaseModel):
    """Result of a registry lookup operation."""
    found: bool
    concept_set: Optional[RegisteredConceptSet] = None
    existing_id: Optional[int] = None  # If duplicate found by hash


class RegistryStats(BaseModel):
    """Statistics about the registry."""
    total_concept_sets: int
    total_concepts: int
    domains: dict  # domain_id -> count
