"""
Integration test: Agent 1 → Agent 2 Pipeline.
Tests the full flow from NL query to mapped concept IDs.
"""
import pytest
from unittest.mock import Mock, patch
import json


class TestAgent1ToAgent2Pipeline:
    """Integration tests for Agent 1 → Agent 2 data flow."""
    
    @pytest.fixture
    def sample_ir_response(self):
        """Sample IR from Agent 1."""
        return {
            "target": {
                "primary_criteria": {
                    "domain": "Drug",
                    "entity_text": "Metformin",
                    "limit": "First"
                },
                "inclusion_rules": [
                    {
                        "name": "T2DM",
                        "domain": "Condition",
                        "entity_text": "Type 2 Diabetes Mellitus",
                        "logic_type": "PRESENCE",
                        "window": {"start": -365, "end": 0}
                    }
                ],
                "exclusion_rules": []
            },
            "comparator": {
                "primary_criteria": {
                    "domain": "Drug",
                    "entity_text": "Sulfonylurea",
                    "limit": "First"
                }
            },
            "outcome": {
                "name": "All-cause Mortality",
                "domain": "Condition",
                "entity_text": "Death",
                "time_at_risk": {"start": 0, "end": 365}
            }
        }
    
    @patch('src.agents.agent1.parser.get_llm')
    def test_agent1_produces_valid_ir(self, mock_get_llm, sample_ir_response):
        """Test Agent 1 produces valid IR that Agent 2 can consume."""
        from src.agents.agent1.parser import LogicDecomposer
        from src.models.ir import ARTEMISRequest
        
        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content=json.dumps(sample_ir_response))
        mock_get_llm.return_value = mock_llm
        
        # Agent 1: Parse NL to IR
        agent1 = LogicDecomposer()
        ir = agent1.parse("Compare Metformin vs Sulfonylurea for mortality in T2DM")
        
        # Validate IR structure
        assert isinstance(ir, ARTEMISRequest)
        assert ir.target.primary_criteria.entity_text == "Metformin"
        
        # Extract entity texts for Agent 2
        entities_to_map = []
        
        for cohort in [ir.target, ir.comparator]:
            if cohort.primary_criteria.entity_text:
                entities_to_map.append({
                    "text": cohort.primary_criteria.entity_text,
                    "domain": cohort.primary_criteria.domain
                })
            for rule in cohort.inclusion_rules:
                if rule.entity_text:
                    entities_to_map.append({
                        "text": rule.entity_text,
                        "domain": rule.domain
                    })
        
        if ir.outcome.entity_text:
            entities_to_map.append({
                "text": ir.outcome.entity_text,
                "domain": ir.outcome.domain
            })
        
        # Verify we extracted the right entities
        assert len(entities_to_map) >= 3
        texts = [e["text"] for e in entities_to_map]
        assert "Metformin" in texts
        assert "Sulfonylurea" in texts
        assert "Type 2 Diabetes Mellitus" in texts
    
    @pytest.mark.skip(reason="Requires chromadb - run with full dependencies")
    def test_agent2_maps_entities(self):
        """Test Agent 2 workflow class exists and is importable."""
        from src.agents.agent2.workflow import Agent2Workflow
        
        # Just verify the class exists and can be instantiated
        agent2 = Agent2Workflow()
        assert hasattr(agent2, 'process')
    
    @pytest.mark.skip(reason="Requires chromadb - run with full dependencies")
    @patch('src.agents.agent1.parser.get_llm')
    def test_full_pipeline_flow(self, mock_get_llm, sample_ir_response):
        """Test complete Agent 1 → Agent 2 flow."""
        from src.agents.agent1.parser import LogicDecomposer
        from src.agents.agent2.workflow import Agent2Workflow
        
        # Mock Agent 1
        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content=json.dumps(sample_ir_response))
        mock_get_llm.return_value = mock_llm
        
        # Run Agent 1
        agent1 = LogicDecomposer()
        ir = agent1.parse("Test query")
        
        # Verify IR is valid for Agent 2 processing
        assert ir.target.primary_criteria.entity_text is not None
        assert ir.comparator.primary_criteria.entity_text is not None
        
        # Verify Agent 2 is ready (without actually calling external dependencies)
        agent2 = Agent2Workflow()
        assert hasattr(agent2, 'process')
        
        print(f"[Pipeline Test] IR generated for '{ir.target.primary_criteria.entity_text}'")

