"""
Unit tests for Agent 4 (Validator) - Phase 2.3.
"""
import pytest
from unittest.mock import patch

from src.agents.agent4.validator import CirCeValidator, ValidationResult, ValidationError


class TestCirCeValidator:
    """Tests for Circe JSON validator."""
    
    @pytest.fixture
    def valid_circe_json(self):
        """Sample valid Circe JSON."""
        return {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "Metformin",
                    "expression": {
                        "items": [
                            {
                                "concept": {
                                    "CONCEPT_ID": 21600381,
                                    "CONCEPT_NAME": "Metformin",
                                    "DOMAIN_ID": "Drug",
                                    "VOCABULARY_ID": "RxNorm"
                                }
                            }
                        ]
                    }
                }
            ],
            "PrimaryCriteria": {
                "CriteriaList": [
                    {
                        "DrugExposure": {"CodesetId": 1}
                    }
                ],
                "ObservationWindow": {"PriorDays": 365, "PostDays": 0}
            },
            "InclusionRules": []
        }
    
    @pytest.fixture
    def invalid_circe_json(self):
        """Sample invalid Circe JSON - missing required fields."""
        return {
            "ConceptSets": []
            # Missing PrimaryCriteria
        }
    
    @patch('src.agents.agent4.validator.registry')
    def test_validate_valid_json(self, mock_registry, valid_circe_json):
        """Test validation passes for valid JSON."""
        mock_registry.exists.return_value = True
        validator = CirCeValidator()
        result = validator.validate(valid_circe_json)
        
        assert result.valid == True
        assert len(result.errors) == 0
    
    def test_validate_missing_required_fields(self, invalid_circe_json):
        """Test validation fails for missing required fields."""
        validator = CirCeValidator()
        result = validator.validate(invalid_circe_json)
        
        assert result.valid == False
        assert len(result.errors) > 0
        
        # Check specific error
        error_fields = [e.field for e in result.errors]
        assert "PrimaryCriteria" in error_fields
    
    def test_validate_empty_criteria_list(self):
        """Test validation fails for empty CriteriaList."""
        validator = CirCeValidator()
        json_data = {
            "ConceptSets": [],
            "PrimaryCriteria": {
                "CriteriaList": []  # Empty
            }
        }
        
        result = validator.validate(json_data)
        
        assert result.valid == False
        assert any("CriteriaList" in e.field for e in result.errors)
    
    @patch('src.agents.agent4.validator.registry')
    def test_validate_duplicate_concept_set_ids(self, mock_registry):
        """Test validation catches duplicate ConceptSet IDs."""
        mock_registry.exists.return_value = True
        validator = CirCeValidator()
        json_data = {
            "ConceptSets": [
                {"id": 1, "name": "A", "expression": {"items": []}},
                {"id": 1, "name": "B", "expression": {"items": []}}  # Duplicate
            ],
            "PrimaryCriteria": {
                "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}]
            }
        }
        
        result = validator.validate(json_data)
        
        assert result.valid == False
        assert any("Duplicate" in e.message for e in result.errors)
    
    @patch('src.agents.agent4.validator.registry')
    def test_validate_invalid_codeset_reference(self, mock_registry):
        """Test validation catches invalid CodesetId references."""
        mock_registry.exists.return_value = True
        validator = CirCeValidator()
        json_data = {
            "ConceptSets": [
                {"id": 1, "name": "A", "expression": {"items": []}}
            ],
            "PrimaryCriteria": {
                "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 999}}]  # Invalid
            }
        }
        
        result = validator.validate(json_data)
        
        assert result.valid == False
        assert any("999" in e.message for e in result.errors)
    
    @patch('src.agents.agent4.validator.registry')
    def test_format_report(self, mock_registry, valid_circe_json):
        """Test report formatting."""
        mock_registry.exists.return_value = True
        validator = CirCeValidator()
        result = validator.validate(valid_circe_json)
        report = validator.format_report(result)
        
        assert "VALID" in report
        assert "ConceptSets:" in report
    
    @patch('src.agents.agent4.validator.registry')
    def test_registry_integrity_warning(self, mock_registry, valid_circe_json):
        """Test warning when ConceptSet not in registry."""
        mock_registry.exists.return_value = False
        
        validator = CirCeValidator()
        result = validator.validate(valid_circe_json)
        
        # Should have warnings but still valid
        assert len(result.warnings) > 0
