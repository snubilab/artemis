"""
Tests for PDF hierarchical structure preservation in eligibility extraction.

P2: When extract_eligibility_from_text() processes text with "parent header +
indented bullets" structure, it should collapse them into a single [OR-GROUP]
criterion string instead of flattening into separate items.
"""
import pytest


class TestOrGroupMarkerForBulletedParent:
    """Parent header + indented bullets → single [OR-GROUP] criterion."""

    def test_basic_ge1_of_pattern(self):
        """
        Given: text with '≥1 of:\n  • A\n  • B\n  • C'
        When:  _collapse_hierarchical_groups is called
        Then:  returns one [OR-GROUP] criterion containing all children joined by ' | '
        """
        from src.agents.agent1.pubmed_fetcher import _collapse_hierarchical_groups

        text = (
            "Age ≥50 and ≥1 of the following:\n"
            "  • Prior MI\n"
            "  • Stroke\n"
            "  • Renal failure\n"
        )
        result = _collapse_hierarchical_groups(text)

        assert "[OR-GROUP]" in result
        assert "Prior MI" in result
        assert "Stroke" in result
        assert "Renal failure" in result
        # Should be collapsed into a SINGLE line, not multiple
        or_group_lines = [ln for ln in result.splitlines() if "[OR-GROUP]" in ln]
        assert len(or_group_lines) == 1
        # All children on the same line separated by ' | '
        assert " | " in or_group_lines[0]

    def test_colon_terminated_header_with_tab_indented_bullets(self):
        """
        Given: header ending ONLY with ':' and tab-indented children (no OR-quantifier phrase)
        When:  _collapse_hierarchical_groups is called
        Then:  does NOT produce [OR-GROUP] — plain colon headers can be AND criteria.
               Post-parse Pattern E repair in parser.py handles the CV cluster merging.
        """
        from src.agents.agent1.pubmed_fetcher import _collapse_hierarchical_groups

        text = (
            "Established cardiovascular disease:\n"
            "\t• Prior CABG\n"
            "\t• Peripheral artery disease\n"
            "\t• Prior stroke\n"
        )
        result = _collapse_hierarchical_groups(text)

        # Colon-only headers do NOT trigger OR-GROUP (prevents false positives like
        # "Laboratory criteria:" collapsing AND children into OR alternatives).
        # Use "≥1 of:" or "at least one of:" for explicit OR-group collapse.
        or_group_lines = [ln for ln in result.splitlines() if "[OR-GROUP]" in ln]
        assert len(or_group_lines) == 0

    def test_at_least_one_of_phrase(self):
        """
        Given: header containing 'at least one of'
        When:  _collapse_hierarchical_groups is called
        Then:  produces [OR-GROUP]
        """
        from src.agents.agent1.pubmed_fetcher import _collapse_hierarchical_groups

        text = (
            "Subject must have at least one of the following risk factors:\n"
            "  - Hypertension\n"
            "  - Dyslipidemia\n"
            "  - Obesity\n"
        )
        result = _collapse_hierarchical_groups(text)

        or_group_lines = [ln for ln in result.splitlines() if "[OR-GROUP]" in ln]
        assert len(or_group_lines) == 1
        line = or_group_lines[0]
        assert "Hypertension" in line
        assert "Dyslipidemia" in line
        assert "Obesity" in line

    def test_full_pipeline_produces_one_item_for_hierarchical_group(self):
        """
        Given: text section containing 'Age ≥50 with ≥1 of:\n  • A\n  • B\n  • C'
        When:  _parse_criteria_items is called
        Then:  returns exactly one item that starts with [OR-GROUP] covering all children
        """
        from src.agents.agent1.pubmed_fetcher import _parse_criteria_items

        text = (
            "Age ≥50 and ≥1 of the following:\n"
            "  • Prior MI\n"
            "  • Stroke\n"
            "  • Renal failure\n"
        )
        items = _parse_criteria_items(text)

        or_items = [it for it in items if it.startswith("[OR-GROUP]")]
        assert len(or_items) == 1, f"Expected 1 OR-GROUP item, got {len(or_items)}: {items}"
        assert "Prior MI" in or_items[0]
        assert "Stroke" in or_items[0]
        assert "Renal failure" in or_items[0]


class TestFlatCriteriaUnchanged:
    """Plain numbered or bullet lists without parent headers → no [OR-GROUP]."""

    def test_numbered_list_no_or_group(self):
        """
        Given: plain numbered list
        When:  _parse_criteria_items is called
        Then:  no [OR-GROUP] markers appear; all items returned individually
        """
        from src.agents.agent1.pubmed_fetcher import _parse_criteria_items

        text = (
            "1. Age ≥18 years\n"
            "2. Type 2 diabetes mellitus\n"
            "3. HbA1c ≥7.0%\n"
            "4. Written informed consent\n"
        )
        items = _parse_criteria_items(text)

        assert all("[OR-GROUP]" not in it for it in items)
        assert len(items) >= 4

    def test_flat_bullet_list_no_or_group(self):
        """
        Given: flat bullet list (no parent header)
        When:  _parse_criteria_items is called
        Then:  no [OR-GROUP] markers; items returned individually
        """
        from src.agents.agent1.pubmed_fetcher import _parse_criteria_items

        text = (
            "• Age ≥18 years\n"
            "• Body weight ≥50 kg\n"
            "• Signed informed consent\n"
        )
        items = _parse_criteria_items(text)

        assert all("[OR-GROUP]" not in it for it in items)
        assert len(items) >= 3

    def test_single_child_under_header_not_grouped(self):
        """
        Given: header with only ONE indented child (< 2 required)
        When:  _collapse_hierarchical_groups is called
        Then:  no [OR-GROUP] produced (requirement: ≥2 children)
        """
        from src.agents.agent1.pubmed_fetcher import _collapse_hierarchical_groups

        text = (
            "Prior cardiovascular event:\n"
            "  • Myocardial infarction\n"
            "No renal impairment\n"
        )
        result = _collapse_hierarchical_groups(text)
        assert "[OR-GROUP]" not in result


class TestMixedFlatAndHierarchical:
    """Some flat criteria + some hierarchical → only hierarchical gets [OR-GROUP]."""

    def test_mixed_content(self):
        """
        Given: mix of flat criteria and one hierarchical group
        When:  _parse_criteria_items is called
        Then:  flat items have no [OR-GROUP]; hierarchical group has one [OR-GROUP]
        """
        from src.agents.agent1.pubmed_fetcher import _parse_criteria_items

        text = (
            "1. Age ≥18 years\n"
            "2. Type 2 diabetes\n"
            "3. Any of the following:\n"
            "   • Prior MI\n"
            "   • Prior stroke\n"
            "   • Peripheral artery disease\n"
            "4. Written informed consent\n"
        )
        items = _parse_criteria_items(text)

        or_items = [it for it in items if "[OR-GROUP]" in it]
        non_or_items = [it for it in items if "[OR-GROUP]" not in it]

        # Exactly one OR-GROUP item for the hierarchical block
        assert len(or_items) == 1
        assert "Prior MI" in or_items[0]
        assert "Prior stroke" in or_items[0]
        assert "Peripheral artery disease" in or_items[0]

        # Flat items should be present without OR-GROUP
        flat_texts = " ".join(non_or_items).lower()
        assert "age" in flat_texts
        assert "type 2 diabetes" in flat_texts
        assert "informed consent" in flat_texts

    def test_two_hierarchical_groups_in_same_section(self):
        """
        Given: two separate hierarchical groups in inclusion criteria
        When:  _parse_criteria_items is called
        Then:  each group produces its own [OR-GROUP] item
        """
        from src.agents.agent1.pubmed_fetcher import _parse_criteria_items

        text = (
            "Age ≥50 with ≥1 of:\n"
            "  • Prior MI\n"
            "  • Stroke\n"
            "eGFR ≥30 mL/min\n"
            "Any of the following comorbidities:\n"
            "  • Heart failure\n"
            "  • Atrial fibrillation\n"
        )
        items = _parse_criteria_items(text)

        or_items = [it for it in items if "[OR-GROUP]" in it]
        assert len(or_items) == 2

        combined = " ".join(or_items)
        assert "Prior MI" in combined
        assert "Stroke" in combined
        assert "Heart failure" in combined
        assert "Atrial fibrillation" in combined
