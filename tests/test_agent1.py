"""
Unit tests for Agent 1 (Logic Decomposer).
"""
import pytest
from unittest.mock import Mock, patch
import json

from src.agents.agent1.parser import LogicDecomposer
from src.models.ir import ARTEMISRequest


class TestLogicDecomposer:
    """Test cases for LogicDecomposer."""
    
    @pytest.fixture
    def mock_llm_response(self):
        """Sample LLM response for testing."""
        return {
            "target": {
                "primary_criteria": {
                    "domain": "Drug",
                    "entity_text": "Empagliflozin",
                    "limit": "First"
                },
                "inclusion_rules": [
                    {
                        "name": "T2DM Diagnosis",
                        "domain": "Condition",
                        "entity_text": "Type 2 Diabetes Mellitus",
                        "logic_type": "PRESENCE",
                        "window": {"start": -365, "end": 0}
                    }
                ],
                "exclusion_rules": [
                    {
                        "name": "No Prior SGLT2i",
                        "domain": "Drug",
                        "entity_text": "SGLT2 Inhibitors",
                        "logic_type": "ABSENCE",
                        "window": {"start": -365, "end": 0}
                    }
                ]
            },
            "comparator": {
                "primary_criteria": {
                    "domain": "Drug",
                    "entity_text": "Placebo",
                    "limit": "First"
                },
                "inclusion_rules": [],
                "exclusion_rules": []
            },
            "outcome": {
                "name": "Cardiovascular Death",
                "domain": "Condition",
                "entity_text": "Cardiovascular Mortality",
                "time_at_risk": {"start": 0, "end": 365}
            }
        }
    
    @patch('src.agents.agent1.parser.get_llm')
    def test_parse_basic_query(self, mock_get_llm, mock_llm_response):
        """Test parsing a basic clinical question."""
        # Setup mock
        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(
            content=json.dumps(mock_llm_response)
        )
        mock_get_llm.return_value = mock_llm
        
        # Test
        decomposer = LogicDecomposer()
        query = "Compare Empagliflozin vs Placebo for cardiovascular death in T2DM patients"
        result = decomposer.parse(query)
        
        # Assertions
        assert isinstance(result, ARTEMISRequest)
        assert result.target.primary_criteria.entity_text == "Empagliflozin"
        assert result.comparator.primary_criteria.entity_text == "Placebo"
        assert result.outcome.name == "Cardiovascular Death"
        assert len(result.target.inclusion_rules) == 1
        assert len(result.target.exclusion_rules) == 1
    
    @patch('src.agents.agent1.parser.get_llm')
    def test_parse_with_markdown_response(self, mock_get_llm, mock_llm_response):
        """Test parsing when LLM returns JSON in markdown code block."""
        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(
            content=f"```json\n{json.dumps(mock_llm_response)}\n```"
        )
        mock_get_llm.return_value = mock_llm
        
        decomposer = LogicDecomposer()
        result = decomposer.parse("Test query")
        
        assert isinstance(result, ARTEMISRequest)
    
    @patch('src.agents.agent1.parser.get_llm')
    def test_parse_with_measurement_constraint(self, mock_get_llm):
        """Test parsing a query with measurement constraints."""
        response = {
            "target": {
                "primary_criteria": {"domain": "Drug", "entity_text": "Metformin"},
                "inclusion_rules": [
                    {
                        "name": "HbA1c > 7%",
                        "domain": "Measurement",
                        "entity_text": "HbA1c",
                        "logic_type": "PRESENCE",
                        "value_constraint": {
                            "op": "gt",
                            "value": 7.0,
                            "unit_text": "%"
                        }
                    }
                ],
                "exclusion_rules": []
            },
            "comparator": {"primary_criteria": {"domain": "Drug", "entity_text": "Placebo"}},
            "outcome": {
                "name": "HbA1c Reduction",
                "domain": "Measurement",
                "entity_text": "HbA1c",
                "time_at_risk": {"start": 0, "end": 180}
            }
        }
        
        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content=json.dumps(response))
        mock_get_llm.return_value = mock_llm
        
        decomposer = LogicDecomposer()
        result = decomposer.parse("Test with HbA1c constraint")
        
        assert result.target.inclusion_rules[0].value_constraint is not None
        assert result.target.inclusion_rules[0].value_constraint.op == "gt"
        assert result.target.inclusion_rules[0].value_constraint.value == 7.0


class TestIRModelValidation:
    """Test IR model constraints and validation."""
    
    def test_temporal_window_validation(self):
        """Test TemporalWindow accepts valid values."""
        from src.models.ir import TemporalWindow
        
        window = TemporalWindow(start=-365, end=0)
        assert window.start == -365
        assert window.end == 0
    
    def test_value_constraint_operators(self):
        """Test ValueConstraint accepts valid operators."""
        from src.models.ir import ValueConstraint
        
        for op in ["gt", "lt", "eq", "gte", "lte"]:
            vc = ValueConstraint(op=op, value=6.5)
            assert vc.op == op

    @patch('src.agents.agent1.parser.get_llm')
    def test_build_criteria_ignores_non_numeric_value_constraint_values(self, mock_get_llm):
        """Non-numeric qualitative values like 'negative' should not crash criteria parsing."""
        mock_get_llm.return_value = Mock()
        decomposer = LogicDecomposer()

        result = decomposer._build_criteria({
            "name": "Negative pregnancy test",
            "domain": "Measurement",
            "entity_text": "Pregnancy test",
            "value_constraint": {
                "op": "eq",
                "value": "negative",
                "unit_text": None,
            },
        })

        assert result.name == "Negative pregnancy test"
        assert result.value_constraint is None

    @patch('src.agents.agent1.parser.get_llm')
    def test_build_criteria_ignores_null_window_payloads(self, mock_get_llm):
        """Null windows from LLM output should not crash criteria parsing."""
        mock_get_llm.return_value = Mock()
        decomposer = LogicDecomposer()

        result = decomposer._build_criteria({
            "name": "Adults with ACS",
            "domain": "Condition",
            "entity_text": "Acute coronary syndrome",
            "window": None,
        })

        assert result.name == "Adults with ACS"
        assert result.window is None


class TestExclusionPolarityEnforcement:
    """Verify exclusion rules are always forced to ABSENCE logic_type."""
    
    @patch('src.agents.agent1.parser.get_llm')
    def test_exclusion_presence_is_forced_to_absence(self, mock_get_llm):
        """LLM outputs PRESENCE for exclusion → parser forces ABSENCE."""
        response = {
            "target": {
                "primary_criteria": {"domain": "Drug", "entity_text": "Liraglutide"},
                "inclusion_rules": [
                    {
                        "name": "T2DM Diagnosis",
                        "domain": "Condition",
                        "entity_text": "Type 2 Diabetes Mellitus",
                        "logic_type": "PRESENCE"
                    }
                ],
                "exclusion_rules": [
                    {
                        "name": "No T1DM",
                        "domain": "Condition",
                        "entity_text": "Type 1 Diabetes Mellitus",
                        "logic_type": "PRESENCE"  # ← Wrong LLM output
                    },
                    {
                        "name": "No transplant",
                        "domain": "Condition",
                        "entity_text": "Solid organ transplant",
                        "logic_type": "PRESENCE"  # ← Wrong LLM output
                    }
                ]
            },
            "comparator": {"primary_criteria": {"domain": "Drug", "entity_text": "Placebo"}},
            "outcome": {
                "name": "CV Death",
                "domain": "Condition",
                "entity_text": "Cardiovascular Mortality",
                "time_at_risk": {"start": 0, "end": 365}
            }
        }
        
        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content=json.dumps(response))
        mock_get_llm.return_value = mock_llm
        
        decomposer = LogicDecomposer()
        result = decomposer.parse("Test exclusion polarity")
        
        # Exclusion rules must be forced to ABSENCE
        assert len(result.target.exclusion_rules) == 2
        for exc_rule in result.target.exclusion_rules:
            assert exc_rule.logic_type == "ABSENCE", \
                f"Exclusion rule '{exc_rule.name}' should be ABSENCE, got {exc_rule.logic_type}"
        
        # Inclusion rules must remain PRESENCE
        assert result.target.inclusion_rules[0].logic_type == "PRESENCE"
    
    @patch('src.agents.agent1.parser.get_llm')
    def test_exclusion_already_absence_is_preserved(self, mock_get_llm):
        """LLM correctly outputs ABSENCE for exclusion → preserved as-is."""
        response = {
            "target": {
                "primary_criteria": {"domain": "Drug", "entity_text": "Liraglutide"},
                "inclusion_rules": [],
                "exclusion_rules": [
                    {
                        "name": "No T1DM",
                        "domain": "Condition",
                        "entity_text": "Type 1 Diabetes Mellitus",
                        "logic_type": "ABSENCE"  # ← Correct
                    }
                ]
            },
            "comparator": {"primary_criteria": {"domain": "Drug", "entity_text": "Placebo"}},
            "outcome": {
                "name": "CV Death",
                "domain": "Condition",
                "entity_text": "Cardiovascular Mortality",
                "time_at_risk": {"start": 0, "end": 365}
            }
        }
        
        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content=json.dumps(response))
        mock_get_llm.return_value = mock_llm
        
        decomposer = LogicDecomposer()
        result = decomposer.parse("Test exclusion polarity preserved")
        
        assert result.target.exclusion_rules[0].logic_type == "ABSENCE"


class TestSubCriteriaParsing:
    """Verify sub_criteria + group_type parsing (Pattern E: composite OR)."""

    @patch('src.agents.agent1.parser.get_llm')
    def test_parse_with_sub_criteria_any(self, mock_get_llm):
        """LLM outputs composite OR rule with sub_criteria → parsed correctly."""
        response = {
            "target": {
                "primary_criteria": {"domain": "Drug", "entity_text": "Liraglutide"},
                "inclusion_rules": [
                    {
                        "name": "T2DM Diagnosis",
                        "domain": "Condition",
                        "entity_text": "Type 2 Diabetes Mellitus",
                        "logic_type": "PRESENCE"
                    },
                    {
                        "name": "Prior CV disease (≥1 of)",
                        "domain": "Condition",
                        "entity_text": None,
                        "logic_type": "PRESENCE",
                        "group_type": "ANY",
                        "sub_criteria": [
                            {
                                "name": "Prior MI",
                                "domain": "Condition",
                                "entity_text": "Myocardial infarction",
                                "logic_type": "PRESENCE"
                            },
                            {
                                "name": "Prior Stroke",
                                "domain": "Condition",
                                "entity_text": "Stroke",
                                "logic_type": "PRESENCE"
                            },
                            {
                                "name": "CHF NYHA II-III",
                                "domain": "Condition",
                                "entity_text": "Chronic heart failure",
                                "logic_type": "PRESENCE"
                            }
                        ]
                    }
                ],
                "exclusion_rules": []
            },
            "comparator": {"primary_criteria": {"domain": "Drug", "entity_text": "Placebo"}},
            "outcome": {
                "name": "MACE",
                "domain": "Condition",
                "entity_text": "Cardiovascular death",
                "time_at_risk": {"start": 0, "end": 365}
            }
        }

        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content=json.dumps(response))
        mock_get_llm.return_value = mock_llm

        decomposer = LogicDecomposer()
        result = decomposer.parse("Test composite OR rule")

        # Two inclusion rules: T2DM (atomic) + CV disease (composite)
        assert len(result.target.inclusion_rules) == 2
        cv_rule = result.target.inclusion_rules[1]
        assert cv_rule.name == "Prior CV disease (≥1 of)"
        assert cv_rule.group_type == "ANY"
        assert len(cv_rule.sub_criteria) == 3
        assert cv_rule.sub_criteria[0].entity_text == "Myocardial infarction"
        assert cv_rule.sub_criteria[1].entity_text == "Stroke"
        assert cv_rule.sub_criteria[2].entity_text == "Chronic heart failure"
        # entity_text of parent is None
        assert cv_rule.entity_text is None

    @patch('src.agents.agent1.parser.get_llm')
    def test_parse_without_sub_criteria_unchanged(self, mock_get_llm):
        """Existing format without sub_criteria still works (backward compat)."""
        response = {
            "target": {
                "primary_criteria": {"domain": "Drug", "entity_text": "Ticagrelor"},
                "inclusion_rules": [
                    {
                        "name": "ACS Diagnosis",
                        "domain": "Condition",
                        "entity_text": "Acute coronary syndrome",
                        "logic_type": "PRESENCE"
                    }
                ],
                "exclusion_rules": []
            },
            "comparator": {"primary_criteria": {"domain": "Drug", "entity_text": "Clopidogrel"}},
            "outcome": {
                "name": "MACE",
                "domain": "Condition",
                "entity_text": "CV death",
                "time_at_risk": {"start": 0, "end": 365}
            }
        }

        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content=json.dumps(response))
        mock_get_llm.return_value = mock_llm

        decomposer = LogicDecomposer()
        result = decomposer.parse("Test no sub_criteria")

        rule = result.target.inclusion_rules[0]
        assert rule.sub_criteria == []
        assert rule.group_type == "ALL"  # default
        assert rule.entity_text == "Acute coronary syndrome"

    @patch('src.agents.agent1.parser.get_llm')
    def test_exclusion_sub_criteria_forced_to_absence(self, mock_get_llm):
        """Exclusion sub_criteria inherit ABSENCE logic_type."""
        response = {
            "target": {
                "primary_criteria": {"domain": "Drug", "entity_text": "Liraglutide"},
                "inclusion_rules": [],
                "exclusion_rules": [
                    {
                        "name": "No CV events (≥1 of)",
                        "domain": "Condition",
                        "entity_text": None,
                        "logic_type": "ABSENCE",
                        "group_type": "ANY",
                        "sub_criteria": [
                            {
                                "name": "No MI",
                                "domain": "Condition",
                                "entity_text": "Myocardial infarction",
                                "logic_type": "PRESENCE"
                            },
                            {
                                "name": "No Stroke",
                                "domain": "Condition",
                                "entity_text": "Stroke",
                                "logic_type": "PRESENCE"
                            }
                        ]
                    }
                ]
            },
            "comparator": {"primary_criteria": {"domain": "Drug", "entity_text": "Placebo"}},
            "outcome": {
                "name": "MACE",
                "domain": "Condition",
                "entity_text": "CV death",
                "time_at_risk": {"start": 0, "end": 365}
            }
        }

        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content=json.dumps(response))
        mock_get_llm.return_value = mock_llm

        decomposer = LogicDecomposer()
        result = decomposer.parse("Test exclusion sub_criteria")

        exc_rule = result.target.exclusion_rules[0]
        assert exc_rule.logic_type == "ABSENCE"
        assert len(exc_rule.sub_criteria) == 2
        # Sub-criteria should also be forced to ABSENCE
        for sc in exc_rule.sub_criteria:
            assert sc.logic_type == "ABSENCE", \
                f"Sub-criterion '{sc.name}' should be ABSENCE, got {sc.logic_type}"

    @patch('src.agents.agent1.parser.get_llm')
    def test_parse_lowercase_group_type_normalized(self, mock_get_llm):
        """Lowercase group_type 'any' should be normalized to 'ANY'."""
        response = {
            "target": {
                "primary_criteria": {"domain": "Drug", "entity_text": "Liraglutide"},
                "inclusion_rules": [
                    {
                        "name": "CV disease (≥1 of)",
                        "domain": "Condition",
                        "entity_text": None,
                        "logic_type": "PRESENCE",
                        "group_type": "any",
                        "sub_criteria": [
                            {"name": "MI", "domain": "Condition",
                             "entity_text": "Myocardial infarction", "logic_type": "PRESENCE"},
                            {"name": "Stroke", "domain": "Condition",
                             "entity_text": "Stroke", "logic_type": "PRESENCE"}
                        ]
                    }
                ],
                "exclusion_rules": []
            },
            "comparator": {"primary_criteria": {"domain": "Drug", "entity_text": "Placebo"}},
            "outcome": {
                "name": "MACE", "domain": "Condition",
                "entity_text": "CV death", "time_at_risk": {"start": 0, "end": 365}
            }
        }

        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content=json.dumps(response))
        mock_get_llm.return_value = mock_llm

        decomposer = LogicDecomposer()
        result = decomposer.parse("Test lowercase group_type")

        cv_rule = result.target.inclusion_rules[0]
        assert cv_rule.group_type == "ANY", \
            f"Lowercase 'any' should be normalized to 'ANY', got '{cv_rule.group_type}'"
        assert len(cv_rule.sub_criteria) == 2
