"""
Unit tests for Registry (Phase 2.1).
Tests RegistryStore and RegisteredConceptSet models.
"""
import pytest
from unittest.mock import Mock, patch
import json

from src.registry.models import RegisteredConceptSet, RegisteredConcept, RegistryLookupResult


class TestRegisteredConceptSet:
    """Tests for RegisteredConceptSet model."""
    
    def test_compute_hash_deterministic(self):
        """Hash should be deterministic for same concepts."""
        concepts = [
            RegisteredConcept(
                concept_id=12345,
                concept_name="Test",
                domain_id="Drug",
                vocabulary_id="RxNorm"
            )
        ]
        
        cs1 = RegisteredConceptSet(id=1, name="Test", concepts=concepts)
        cs2 = RegisteredConceptSet(id=2, name="Different Name", concepts=concepts)
        
        # Same concepts = same hash
        assert cs1.hash == cs2.hash
    
    def test_compute_hash_different_for_different_concepts(self):
        """Hash should differ for different concepts."""
        cs1 = RegisteredConceptSet(
            id=1, name="Test",
            concepts=[RegisteredConcept(
                concept_id=111,
                concept_name="A",
                domain_id="Drug",
                vocabulary_id="RxNorm"
            )]
        )
        cs2 = RegisteredConceptSet(
            id=2, name="Test",
            concepts=[RegisteredConcept(
                concept_id=222,
                concept_name="B",
                domain_id="Drug",
                vocabulary_id="RxNorm"
            )]
        )
        
        assert cs1.hash != cs2.hash


class TestRegistryStore:
    """Tests for RegistryStore - requires Redis mock."""
    
    @patch('src.registry.store.get_redis_client')
    def test_register_new_concept_set(self, mock_get_redis):
        """Test registering a new ConceptSet."""
        from src.registry.store import RegistryStore
        
        # Mock Redis client
        mock_client = Mock()
        mock_client.hget.return_value = None  # No existing hash
        mock_client.incr.return_value = 1
        mock_get_redis.return_value = mock_client
        
        store = RegistryStore()
        concepts = [
            RegisteredConcept(
                concept_id=21600381,
                concept_name="Metformin",
                domain_id="Drug",
                vocabulary_id="RxNorm"
            )
        ]
        
        result = store.register(
            name="Metformin Concept Set",
            concepts=concepts,
            source_entity_text="Metformin"
        )
        
        assert result.found == False
        assert result.concept_set is not None
        assert result.concept_set.name == "Metformin Concept Set"
        mock_client.set.assert_called_once()
    
    @patch('src.registry.store.get_redis_client')
    def test_register_returns_existing_on_duplicate(self, mock_get_redis):
        """Test that duplicate ConceptSets return existing entry."""
        from src.registry.store import RegistryStore
        
        mock_client = Mock()
        # Simulate existing hash found
        mock_client.hget.return_value = "5"  # Existing ID
        
        existing_data = RegisteredConceptSet(
            id=5,
            name="Existing",
            concepts=[RegisteredConcept(
                concept_id=21600381,
                concept_name="Metformin",
                domain_id="Drug",
                vocabulary_id="RxNorm"
            )]
        )
        mock_client.get.return_value = existing_data.model_dump_json()
        mock_get_redis.return_value = mock_client
        
        store = RegistryStore()
        result = store.register(
            name="New Name",
            concepts=existing_data.concepts
        )
        
        assert result.found == True
        assert result.existing_id == 5
    
    @patch('src.registry.store.get_redis_client')
    def test_get_returns_none_for_missing(self, mock_get_redis):
        """Test get returns None for non-existent ID."""
        from src.registry.store import RegistryStore
        
        mock_client = Mock()
        mock_client.get.return_value = None
        mock_get_redis.return_value = mock_client
        
        store = RegistryStore()
        result = store.get(99999)
        
        assert result is None
