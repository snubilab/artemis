"""
Tests for _parse_criteria_items() hybrid Regex+LLM criteria parser.

Covers comma/semicolon separation (original), bullet points, numbered lists,
newline-separated items, mixed formats, short-item filtering, and LLM fallback.
"""
import pytest
from unittest.mock import patch, MagicMock

from src.agents.agent1.pubmed_fetcher import _parse_criteria_items, _regex_parse_criteria


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
    """Realistic LEADER supplement text with nested bullet structure.

    The regex parser returns 2 items for this text -- both OR-GROUP headers, with
    all thirteen bullets swallowed into them. The gate at pubmed_fetcher.py:336
    (`len(regex_items) < 5`) therefore always fires here, so any assertion of
    ">= 12 items" is an assertion about the LLM, not about the parser.

    That made the original test bill a live OpenAI call on every suite run and
    fail nondeterministically. It is split here: the deterministic part asserts
    what the parser does unaided and records the bullet-swallowing gap, and the
    end-to-end claim is marked integration so it runs deliberately.
    """

    LEADER_TEXT = (
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

    def test_regex_alone_swallows_the_bullets_into_their_headers(self):
        """The gap the LLM fallback is currently hiding."""
        with patch(
            "src.agents.agent1.pubmed_fetcher._llm_parse_criteria", return_value=[]
        ) as mock_llm:
            result = _parse_criteria_items(self.LEADER_TEXT)

        mock_llm.assert_called_once()  # the < 5 gate fires, which is the point
        assert len(result) == 2, f"regex-only should yield the two headers, got {result}"
        assert all(item.startswith("[OR-GROUP]") for item in result)

    def test_llm_items_are_merged_with_the_headers(self):
        """Deterministic: a canned fallback must reach the caller, not be dropped."""
        bullets = [
            "Prior MI", "Prior stroke or TIA", "Coronary revascularization",
            ">50% stenosis", "Symptomatic CHD", "Asymptomatic cardiac ischemia",
            "CHF NYHA class II-III", "eGFR <60", "Microalbuminuria or proteinuria",
            "Hypertension and LVH", "LV systolic or diastolic dysfunction",
            "ABI <0.9",
        ]
        with patch(
            "src.agents.agent1.pubmed_fetcher._llm_parse_criteria", return_value=bullets
        ):
            result = _parse_criteria_items(self.LEADER_TEXT)

        assert len(result) >= 12, f"Expected >= 12 after merge, got {len(result)}"

    @pytest.mark.billed
    def test_leader_supplement_produces_many_items(self):
        """End-to-end with a real LLM. Billed, and nondeterministic by nature.

        Not marked "integration": it needs a paid model, not the Docker stack.
        """
        result = _parse_criteria_items(self.LEADER_TEXT)
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
