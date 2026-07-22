"""
TDD Tests for IR model: Criteria sub_criteria and group_type.
RED phase — tests should FAIL before implementation.
"""
import pytest
from src.models.ir import Criteria, TemporalWindow


class TestCriteriaSubCriteria:
    """Test Criteria model with sub_criteria and group_type fields."""

    def test_criteria_has_sub_criteria_field(self):
        """Criteria should accept sub_criteria as a list of Criteria."""
        parent = Criteria(
            name="Established CV Disease",
            domain="Condition",
            entity_text="cardiovascular disease",
            logic_type="PRESENCE",
            sub_criteria=[
                Criteria(name="MI", domain="Condition", entity_text="Myocardial Infarction"),
                Criteria(name="Stroke", domain="Condition", entity_text="Stroke"),
                Criteria(name="CAD", domain="Condition", entity_text="Coronary artery disease"),
            ],
            group_type="ANY"
        )
        assert len(parent.sub_criteria) == 3
        assert parent.group_type == "ANY"
        assert parent.sub_criteria[0].entity_text == "Myocardial Infarction"

    def test_criteria_default_no_sub_criteria(self):
        """Criteria without sub_criteria should default to empty list."""
        c = Criteria(name="T2DM", domain="Condition", entity_text="Type 2 diabetes")
        assert c.sub_criteria == []
        assert c.group_type == "ALL"

    def test_criteria_sub_criteria_preserves_parent_window(self):
        """Sub-criteria inherit structure but parent retains its own window."""
        parent = Criteria(
            name="CV Disease",
            domain="Condition",
            entity_text="cardiovascular disease",
            window=TemporalWindow(start=-365, end=0),
            sub_criteria=[
                Criteria(name="MI", domain="Condition", entity_text="MI"),
            ],
            group_type="ANY"
        )
        assert parent.window.start == -365
        # Sub-criteria don't automatically inherit window
        assert parent.sub_criteria[0].window is None

    def test_criteria_group_type_any(self):
        """group_type='ANY' means at least one sub-criterion must be present."""
        c = Criteria(
            name="CV Disease",
            domain="Condition",
            sub_criteria=[
                Criteria(name="MI", domain="Condition", entity_text="MI"),
                Criteria(name="Stroke", domain="Condition", entity_text="Stroke"),
            ],
            group_type="ANY"
        )
        assert c.group_type == "ANY"

    def test_is_composite_property(self):
        """Criteria with sub_criteria is composite."""
        atomic = Criteria(name="T2DM", domain="Condition", entity_text="T2DM")
        composite = Criteria(
            name="CV", domain="Condition",
            sub_criteria=[Criteria(name="MI", domain="Condition", entity_text="MI")]
        )
        # Composite has sub_criteria
        assert len(atomic.sub_criteria) == 0
        assert len(composite.sub_criteria) > 0
