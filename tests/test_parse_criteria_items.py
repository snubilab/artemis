"""
Tests for _parse_criteria_items() hybrid Regex+LLM criteria parser.

Covers comma/semicolon separation (original), bullet points, numbered lists,
newline-separated items, mixed formats, short-item filtering, and LLM fallback.
"""
import pytest
from unittest.mock import patch, MagicMock

from src.agents.agent1.pubmed_fetcher import _parse_criteria_items


class TestCommaSeparated:
    """Original comma-separated parsing behavior."""

    def test_comma_separated_returns_individual_items(self):
        # Arrange
        text = "Type 2 diabetes, HbA1c >= 7.0%, Age >= 50 years"

        # Act
        result = _parse_criteria_items(text)

        # Assert
        assert len(result) == 3
        assert "Type 2 diabetes" in result
        assert "HbA1c >= 7.0%" in result
        assert "Age >= 50 years" in result


class TestSemicolonSeparated:
    """Original semicolon-separated parsing behavior."""

    def test_semicolon_separated_returns_individual_items(self):
        # Arrange
        text = "Type 2 diabetes; HbA1c >= 7.0%; Age >= 50 years"

        # Act
        result = _parse_criteria_items(text)

        # Assert
        assert len(result) == 3


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


class TestLeaderSupplementStyle:
    """Realistic LEADER supplement text with nested bullet structure."""

    def test_leader_supplement_produces_many_items(self):
        # Arrange
        text = (
            "Prior cardiovascular disease cohort: age \u226550 and \u22651 of:\n"
            "\u25cb Prior MI\n"
            "\u25cb Prior stroke or TIA\n"
            "\u25cb Coronary, carotid, or peripheral arterial revascularization\n"
            "\u25cb >50% stenosis\n"
            "\u25cb Symptomatic CHD\n"
            "\u25cb Asymptomatic cardiac ischemia\n"
            "\u25cb CHF NYHA class II-III\n"
            "\u25cb eGFR <60\n"
            "No prior cardiovascular disease group: age \u226560 and \u22651 of:\n"
            "\u25cb Microalbuminuria or proteinuria\n"
            "\u25cb Hypertension and LVH\n"
            "\u25cb LV systolic or diastolic dysfunction\n"
            "\u25cb ABI <0.9"
        )

        # Act
        result = _parse_criteria_items(text)

        # Assert -- should produce at least 12 distinct items from the bullets
        assert len(result) >= 12, f"Expected >= 12 items, got {len(result)}: {result}"


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


class TestLLMFallback:
    """LLM fallback behavior when regex produces too few items."""

    @patch("src.agents.agent1.pubmed_fetcher._llm_parse_criteria")
    def test_llm_fallback_not_triggered_when_regex_sufficient(self, mock_llm):
        """When regex produces >= 5 items, LLM should NOT be called."""
        # Arrange
        text = (
            "\u25cb Prior MI\n"
            "\u25cb Prior stroke or TIA\n"
            "\u25cb Revascularization\n"
            "\u25cb Microalbuminuria\n"
            "\u25cb CHF NYHA class II-III\n"
            "\u25cb eGFR < 60"
        )

        # Act
        result = _parse_criteria_items(text)

        # Assert
        mock_llm.assert_not_called()
        assert len(result) >= 5

    @patch("src.agents.agent1.pubmed_fetcher._llm_parse_criteria")
    def test_llm_fallback_triggered_when_regex_insufficient(self, mock_llm):
        """When regex produces < 5 items from > 200 chars text, LLM is called."""
        # Arrange -- long text that regex can't split well (no clear delimiters)
        long_text = (
            "Patients must have established cardiovascular disease including "
            "prior myocardial infarction or stroke or transient ischemic attack "
            "or coronary revascularization or carotid revascularization or "
            "peripheral arterial revascularization with documented stenosis "
            "greater than fifty percent or symptomatic coronary heart disease "
            "or asymptomatic cardiac ischemia or chronic heart failure "
            "with NYHA class II through III or estimated GFR less than sixty"
        )
        assert len(long_text) > 200

        mock_llm.return_value = [
            "Prior myocardial infarction",
            "Prior stroke or TIA",
            "Coronary revascularization",
            "Carotid revascularization",
            "Peripheral arterial revascularization",
            "Stenosis > 50%",
            "Symptomatic CHD",
            "Asymptomatic cardiac ischemia",
            "CHF NYHA class II-III",
            "eGFR < 60",
        ]

        # Act
        result = _parse_criteria_items(long_text)

        # Assert
        mock_llm.assert_called_once()
        assert len(result) >= 5

    @patch("src.agents.agent1.pubmed_fetcher._llm_parse_criteria")
    def test_llm_fallback_error_returns_regex_result(self, mock_llm):
        """When LLM raises an exception, regex result is returned as fallback."""
        # Arrange
        long_text = "a " * 150  # > 200 chars, regex will produce few items
        mock_llm.side_effect = Exception("LLM API unavailable")

        # Act
        result = _parse_criteria_items(long_text)

        # Assert -- should not raise, returns whatever regex found
        assert isinstance(result, list)
