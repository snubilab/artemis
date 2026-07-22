import pytest
from unittest.mock import MagicMock, patch
from src.agents.agent2.kg_expander import KGExpander, KGConcept

@pytest.fixture
def mock_driver():
    with patch("src.agents.agent2.kg_expander.GraphDatabase.driver") as mock_driver_cls:
        driver_instance = MagicMock()
        mock_driver_cls.return_value = driver_instance
        yield driver_instance

@pytest.fixture
def expander(mock_driver):
    return KGExpander()

def test_kg_concept_has_descendant_count():
    """Subtask 02: KGConcept should have descendant_count field."""
    c = KGConcept(
        concept_id=1, 
        concept_name="Test", 
        domain_id="Condition", 
        vocabulary_id="SNOMED"
    )
    assert hasattr(c, "descendant_count"), "KGConcept missing descendant_count field"
    assert c.descendant_count == 0, "Default descendant_count should be 0"

def test_get_ancestors_counts_descendants(expander, mock_driver):
    """Subtask 02: get_ancestors should parse descendant_count from PostgreSQL."""
    # Mock session and result
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    # Mock Cypher result records (Neo4j returns ancestor info, NOT desc_count)
    mock_record1 = {
        "cid": 100, "name": "Parent", "domain": "Condition", 
        "vocab": "SNOMED", "cclass": "Clinical Finding", 
        "sep": 1,
    }
    mock_record2 = {
        "cid": 200, "name": "Grandparent", "domain": "Condition", 
        "vocab": "SNOMED", "cclass": "Clinical Finding", 
        "sep": 2,
    }
    
    mock_result = MagicMock()
    mock_result.__iter__.return_value = [mock_record1, mock_record2]
    mock_session.run.return_value = mock_result

    # Mock PostgreSQL descendant counts (the actual source of descendant_count)
    with patch.object(expander, '_get_pg_descendant_counts', return_value={100: 50, 200: 120}):
        ancestors = expander.get_ancestors(concept_id=10, max_sep=2)

    assert len(ancestors) == 2
    assert ancestors[0].concept_id == 100
    assert ancestors[0].descendant_count == 50
    assert ancestors[1].concept_id == 200
    assert ancestors[1].descendant_count == 120

def test_expand_includes_ancestors(expander):
    """Subtask 01: expand() should include ancestors in results."""
    # Mock helper methods to isolate logic
    with patch.object(expander, 'get_descendants', return_value=[]), \
         patch.object(expander, 'expand_from_ancestors', return_value=[]), \
         patch.object(expander, 'get_siblings', return_value=[]), \
         patch.object(expander, 'get_maps_to', return_value=[]), \
         patch.object(expander, 'get_ancestors') as mock_get_ancestors:
        
        # Setup ancestors return
        ancestor = KGConcept(
            concept_id=999, concept_name="Ancestor", 
            domain_id="Condition", vocabulary_id="SNOMED", 
            relationship="ancestor", descendant_count=100
        )
        mock_get_ancestors.return_value = [ancestor]

        # Call expand
        results = expander.expand(concept_id=1, strategy="clinical")

        # Verify ancestors were retrieved and added
        mock_get_ancestors.assert_called_once_with(1, max_sep=2)
        assert ancestor in results, "Ancestor should be in expansion results"

def test_expand_deduplicates_ancestors(expander):
    """Subtask 01: expand() should not duplicate if ancestor also appears elsewhere."""
    with patch.object(expander, 'get_descendants', return_value=[]), \
         patch.object(expander, 'expand_from_ancestors', return_value=[]), \
         patch.object(expander, 'get_siblings') as mock_siblings, \
         patch.object(expander, 'get_maps_to', return_value=[]), \
         patch.object(expander, 'get_ancestors') as mock_ancestors:
        
        # Same concept returned by siblings and ancestors
        concept_obj = KGConcept(concept_id=999, concept_name="Common", domain_id="C", vocabulary_id="V")
        
        mock_siblings.return_value = [concept_obj]
        mock_ancestors.return_value = [concept_obj]

        results = expander.expand(concept_id=1, strategy="clinical")

        # Should only appear once
        assert len(results) == 1
        assert results[0].concept_id == 999