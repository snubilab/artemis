"""
Tests for the list splitter of the section rules (section_rules._regex_parse_criteria), restored 2026-10-22.

Restored from fe7839e^ (tests/test_parse_criteria_items.py) for the format rules only: bullets, list numbering,
line structure, wrapped lines, short-item filtering. The cases for the comma/semicolon plain-text split, the LLM
split pass and the A6 [OR-GROUP] collapse are not restored with those rules (see section_rules' module docstring).
"""
import pytest

from src.agents.agent1.section_rules import _regex_parse_criteria
from src.agents.agent1.section_rules import _regex_parse_criteria as _parse_criteria_items


class TestBulletPoints:
    """Bullet point list parsing (unicode and ASCII)."""

    def test_bullet_point_unicode_circle(self):
        # Arrange
        text = (
            "\u25cb Prior MI\n"
            "\u25cb Prior stroke or TIA\n"
            "\u25cb Revascularization\n"
            "\u25cb Microalbuminuria"
        )

        # Act
        result = _parse_criteria_items(text)

        # Assert
        assert len(result) == 4
        assert "Prior MI" in result
        assert "Prior stroke or TIA" in result
        assert "Revascularization" in result
        assert "Microalbuminuria" in result

    def test_bullet_point_dash(self):
        # Arrange
        text = "- Type 2 diabetes\n- HbA1c >= 7.0%\n- Age >= 50 years"

        # Act
        result = _parse_criteria_items(text)

        # Assert
        assert len(result) == 3

    def test_bullet_point_asterisk(self):
        # Arrange
        text = "* Prior MI\n* Prior stroke\n* CHF NYHA II-III"

        # Act
        result = _parse_criteria_items(text)

        # Assert
        assert len(result) == 3

    def test_bullet_point_filled_circle(self):
        # Arrange
        text = "\u2022 Prior MI\n\u2022 Prior stroke\n\u2022 CHF NYHA II-III"

        # Act
        result = _parse_criteria_items(text)

        # Assert
        assert len(result) == 3


class TestNumberedList:
    """Numbered list parsing."""

    def test_numbered_list_dot(self):
        # Arrange
        text = "1. Prior MI\n2. Prior stroke\n3. CHF NYHA II-III\n4. eGFR < 60"

        # Act
        result = _parse_criteria_items(text)

        # Assert
        assert len(result) == 4

    def test_numbered_list_parenthesis(self):
        # Arrange
        text = "a) Prior MI\nb) Prior stroke\nc) CHF NYHA II-III"

        # Act
        result = _parse_criteria_items(text)

        # Assert
        assert len(result) == 3


class TestNewlineSeparated:
    """Newline-separated item parsing."""

    def test_newline_separated_items(self):
        # Arrange
        text = (
            "Prior MI\n"
            "Prior stroke or TIA\n"
            "Revascularization\n"
            "Microalbuminuria"
        )

        # Act
        result = _parse_criteria_items(text)

        # Assert
        assert len(result) == 4


class TestMixedFormat:
    """Mixed format parsing -- bullets should take priority over commas."""

    def test_mixed_bullet_with_internal_commas_preserved(self):
        """Commas inside bullet items should NOT cause extra splits."""
        # Arrange
        text = (
            "Prior cardiovascular disease cohort:\n"
            "\u25cb Prior MI\n"
            "\u25cb Prior stroke or TIA\n"
            "\u25cb Coronary, carotid, or peripheral arterial revascularization"
        )

        # Act
        result = _parse_criteria_items(text)

        # Assert -- "Coronary, carotid, or peripheral" must stay as one item
        combined = " ".join(result)
        assert any("coronary" in item.lower() and "peripheral" in item.lower() for item in result), (
            f"Expected a single item containing both 'coronary' and 'peripheral', got: {result}"
        )


class TestShortItemFiltering:
    """Short items (< 5 chars) should be filtered out."""

    def test_short_items_removed(self):
        # Arrange
        text = "Type 2 diabetes, MI, HbA1c >= 7.0%, Age >= 50 years"

        # Act
        result = _parse_criteria_items(text)

        # Assert -- "MI" (2 chars) should be filtered
        assert all(len(item) > 5 for item in result)
        assert "MI" not in result


class TestEmptyInput:
    """Empty and whitespace-only input handling."""

    def test_empty_string_returns_empty_list(self):
        assert _parse_criteria_items("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert _parse_criteria_items("   \n\t  ") == []


class TestWrappedLineStartingWithPunctuation:
    """pdftotext wraps a criterion mid-sentence and the next line starts with a
    bracket, an operator or a digit rather than a lowercase letter.

    CARMELINA's supplement wraps immediately after "ALT", so the continuation
    begins "(SGPT), AST (SGOT), ...". The rejoin heuristic tested only
    `stripped[0].islower()`, so the fragment became a criterion of its own and
    the model, handed a fragment with no ALT in it, emitted one generic
    "Liver enzyme elevation" instead of three analyte criteria. Gold has three.

    These exercise _regex_parse_criteria rather than _parse_criteria_items:
    the latter hands text over ~200 characters to a live LLM, which both makes
    the test billable and hides what the regex pass did.
    """

    def test_the_carmelina_wrap_is_rejoined(self):
        # verbatim from jama_2019_carmelina_supplement.pdf, item 3
        text = (
            "3) Active liver disease or impaired hepatic function, defined by serum levels of either ALT\n"
            "(SGPT), AST (SGOT), or alkaline phosphatase (AP) >=3 x upper limit of normal (ULN) as\n"
            "determined at Visit 1.\n"
        )

        result = _regex_parse_criteria(text)

        assert len(result) == 1, f"expected one criterion, got {result}"
        assert "ALT" in result[0] and "AST" in result[0] and "alkaline phosphatase" in result[0]

    @pytest.mark.parametrize("continuation", [
        "(SGPT), AST (SGOT) above the limit",       # bracket
        ">=3 x upper limit of normal at Visit 1",   # comparison operator
        "18 years or older at informed consent",    # digit
    ])
    def test_continuations_that_do_not_start_with_a_letter_are_rejoined(self, continuation):
        # numbered so the splitter stays in bullet mode and does not sub-split commas
        text = f"1) Serum levels of either ALT\n{continuation}\n"

        result = _regex_parse_criteria(text)

        assert len(result) == 1, f"expected one criterion, got {result}"

    def test_a_new_item_starting_with_a_capital_still_splits(self):
        text = ("1) Documented type 2 diabetes mellitus\n"
                "2) Age 40 to 85 years at informed consent\n")

        assert len(_regex_parse_criteria(text)) == 2

    def test_an_abbreviation_starting_a_line_still_starts_a_new_item(self):
        """eGFR opens a criterion; it must not be glued to the previous one.
        This is what the abbreviation guard protects."""
        text = ("1) Active liver disease or impaired hepatic function\n"
                "eGFR <15 ml/min/1.73 m2 as determined during screening\n")

        assert len(_regex_parse_criteria(text)) == 2

    def test_a_sentence_that_already_ended_is_not_glued_to_the_next(self):
        text = "1) Type 1 diabetes mellitus.\n(SGPT) elevation above the reference range\n"

        assert len(_regex_parse_criteria(text)) == 2


class TestParenthesizedEnumeratedItems:
    """PLATO's design paper (plato_design_ahj2009.pdf, Table I) enumerates
    alternatives as '(a)', '(b)', '(c)' -- a leading paren before the letter --
    rather than the bare 'a)' / 'a.' forms the numbered-list regex already
    handled. Because Step 1 didn't strip the leading paren, Step 2's
    continuation heuristic (added for CARMELINA's '(SGPT)' wrap) treated each
    new enumerated item's '(' as a mid-sentence wrap and glued (b), (c), (d)
    onto (a). The merged string then fed the LLM's Age>=60 value-constraint
    extraction, producing the corrupted unitText 'y of age (b) Previous MI'
    (PLATO's known Age>=60 anomaly, out of scope of SPEC-INFRA-003 per
    spec.md Section 4).
    """

    PLATO_RISK_FACTORS = (
        "3. One of the following:\n"
        "(a) ≥60 y of age\n"
        "(b) Previous MI or CABG\n"
        "(c) CAD with ≥50% stenosis\n"
        "in ≥2 vessels\n"
        "(d) Previous ischemic stroke,\n"
        "TIA (hospital-based diagnosis),\n"
        "carotid stenosis (≥50%),\n"
        "or cerebral revascularization\n"
        "(e) Diabetes mellitus\n"
        "(f) Peripheral artery disease\n"
        "(g) Chronic renal dysfunction\n"
    )

    def test_leading_paren_letter_items_are_not_glued_together(self):
        result = _regex_parse_criteria(self.PLATO_RISK_FACTORS)
        age_item = next((i for i in result if "60" in i and "age" in i.lower()), None)
        assert age_item is not None, f"no age item found in {result}"
        assert "Previous MI" not in age_item, f"(b)'s text leaked into (a)'s item: {age_item!r}"

    def test_each_leading_paren_letter_item_is_its_own_entry(self):
        result = _regex_parse_criteria(self.PLATO_RISK_FACTORS)
        assert any(i.startswith("Previous MI or CABG") for i in result), result
        assert any("Diabetes mellitus" in i for i in result), result

    def test_the_carmelina_wrap_is_still_rejoined_after_this_fix(self):
        # Non-regression: '(SGPT)' is not a single letter/digit/roman marker,
        # so it must still be treated as a mid-sentence continuation.
        text = (
            "3) Active liver disease or impaired hepatic function, defined by serum levels of either ALT\n"
            "(SGPT), AST (SGOT), or alkaline phosphatase (AP) >=3 x upper limit of normal (ULN) as\n"
            "determined at Visit 1.\n"
        )
        result = _regex_parse_criteria(text)
        assert len(result) == 1, f"expected one criterion, got {result}"
        assert "ALT" in result[0] and "AST" in result[0]
