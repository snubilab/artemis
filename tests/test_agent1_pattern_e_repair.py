"""
Tests for Pattern E post-parse repair in LogicDecomposer.

Pattern E violation: LLM emits 3+ consecutive flat AND inclusion rules for
criteria that should be an OR group (e.g., CV disease history).
The repair merges them into a single Criteria with group_type="ANY".
"""
import pytest

from src.agents.agent1.parser import LogicDecomposer
from src.models.ir import Criteria


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flat(name: str, entity_text: str, domain: str = "Condition") -> Criteria:
    """Build a flat (no sub_criteria, group_type=ALL) Criteria."""
    return Criteria(
        name=name,
        domain=domain,
        entity_text=entity_text,
        logic_type="PRESENCE",
        sub_criteria=[],
        group_type="ALL",
    )


def _make_grouped(name: str, children: list[Criteria]) -> Criteria:
    """Build a Criteria that already has sub_criteria (i.e. already grouped)."""
    return Criteria(
        name=name,
        domain="Condition",
        entity_text=None,
        logic_type="PRESENCE",
        sub_criteria=children,
        group_type="ANY",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRepairPatternE:
    """Unit tests for LogicDecomposer._repair_pattern_e."""

    def test_repair_merges_cv_cluster_into_any_group(self):
        """4 consecutive flat CV-prior rules → merged into 1 ANY group."""
        rules = [
            _make_flat("MI history", "myocardial infarction"),
            _make_flat("Stroke history", "stroke"),
            _make_flat("TIA history", "transient ischemic attack"),
            _make_flat("CABG history", "cabg procedure"),
        ]

        result = LogicDecomposer._repair_pattern_e(rules)

        assert len(result) == 1, f"Expected 1 merged rule, got {len(result)}"
        merged = result[0]
        assert merged.group_type == "ANY"
        assert len(merged.sub_criteria) == 4
        assert merged.entity_text is None
        assert "cv prior" in merged.name.lower() or "or group" in merged.name.lower()

    def test_repair_does_not_merge_already_grouped_rules(self):
        """A rule that already has sub_criteria must not be touched."""
        child1 = _make_flat("MI", "myocardial infarction")
        child2 = _make_flat("Stroke", "stroke")
        child3 = _make_flat("CABG", "cabg")
        already_grouped = _make_grouped("CV group (already ANY)", [child1, child2, child3])

        # Add some unrelated flat rule so the list is non-trivial
        unrelated = _make_flat("T2DM", "diabetes mellitus type 2")
        rules = [already_grouped, unrelated]

        result = LogicDecomposer._repair_pattern_e(rules)

        assert len(result) == 2
        # The already-grouped rule must be unchanged
        assert result[0] is already_grouped
        assert result[0].group_type == "ANY"
        assert len(result[0].sub_criteria) == 3

    def test_repair_skips_short_runs(self):
        """Only 2 consecutive CV-prior rules → no merge (threshold is 3)."""
        rules = [
            _make_flat("MI history", "myocardial infarction"),
            _make_flat("Stroke history", "stroke"),
        ]

        result = LogicDecomposer._repair_pattern_e(rules)

        assert len(result) == 2
        for r in result:
            assert r.group_type == "ALL"
            assert not r.sub_criteria

    def test_repair_is_idempotent(self):
        """Running _repair_pattern_e twice produces the same result."""
        rules = [
            _make_flat("MI history", "myocardial infarction"),
            _make_flat("Stroke history", "stroke"),
            _make_flat("TIA history", "transient ischemic attack"),
        ]

        first_pass = LogicDecomposer._repair_pattern_e(rules)
        second_pass = LogicDecomposer._repair_pattern_e(first_pass)

        assert len(first_pass) == len(second_pass) == 1
        assert first_pass[0].group_type == second_pass[0].group_type == "ANY"
        # sub_criteria count must not grow
        assert len(first_pass[0].sub_criteria) == len(second_pass[0].sub_criteria) == 3

    def test_repair_empty_list_returns_empty(self):
        """Empty input → empty output (no crash)."""
        assert LogicDecomposer._repair_pattern_e([]) == []

    def test_repair_merges_all_when_all_same_cluster(self):
        """If every rule belongs to the same cluster, all get merged."""
        rules = [
            _make_flat("MI", "myocardial infarction"),
            _make_flat("Stroke", "stroke"),
            _make_flat("Heart failure", "heart failure"),
            _make_flat("CKD", "chronic kidney disease"),
            _make_flat("PAD", "peripheral artery disease"),
        ]

        result = LogicDecomposer._repair_pattern_e(rules)

        assert len(result) == 1
        assert result[0].group_type == "ANY"
        assert len(result[0].sub_criteria) == 5

    def test_repair_separate_clusters_not_merged_together(self):
        """Two distinct clusters that each have 3+ rules → two separate ANY groups."""
        cv_rules = [
            _make_flat("MI", "myocardial infarction"),
            _make_flat("Stroke", "stroke"),
            _make_flat("TIA", "transient ischemic attack"),
        ]
        metabolic_rules = [
            _make_flat("T2DM", "diabetes mellitus"),
            _make_flat("Obesity", "obesity"),
            _make_flat("Dyslipidemia", "dyslipidemia"),
        ]
        rules = cv_rules + metabolic_rules

        result = LogicDecomposer._repair_pattern_e(rules)

        assert len(result) == 2
        assert all(r.group_type == "ANY" for r in result)
        assert len(result[0].sub_criteria) == 3
        assert len(result[1].sub_criteria) == 3

    def test_repair_non_cluster_rules_preserved(self):
        """Rules that don't match any cluster pass through unchanged."""
        rules = [
            _make_flat("Age >= 40", "age"),
            _make_flat("Written consent", "informed consent"),
        ]

        result = LogicDecomposer._repair_pattern_e(rules)

        assert len(result) == 2
        for r in result:
            assert r.group_type == "ALL"
            assert not r.sub_criteria
