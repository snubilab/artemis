"""Tests for the offline PubChem drug-name normalizer.

Key-normalization tests run everywhere.  The lookup tests need the built
database (multi-GB, gitignored) and skip cleanly when it is absent, so the
suite stays green on a machine that has not run the build script.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.agents.agent2.drug_name_normalizer import (
    DEFAULT_DB_PATH,
    MATCH_CASE_FOLDED,
    MATCH_EXACT,
    MATCH_PUNCT_NORMALIZED,
    DrugNameNormalizer,
    normalize_key,
)

# The whole point of this module is that a development code resolves to its
# ingredient name; these are the codes that burned us in production.
DEVELOPMENT_CODES = [
    ("BI 10773", "Empagliflozin"),
    ("BI-10773", "Empagliflozin"),
    ("AZD6140", "Ticagrelor"),
    ("NN2211", "Liraglutide"),
    ("BMS-562247", "Apixaban"),
    ("BI 1356", "Linagliptin"),
    ("empagliflozin", "Empagliflozin"),
    ("Jardiance", "Empagliflozin"),
]


class TestNormalizeKey:
    """Key generation is the contract between the builder and the reader."""

    @pytest.mark.parametrize("spelling", ["BI 10773", "BI-10773", "BI10773", "bi 10773", "  BI 10773  "])
    def test_punctuation_and_case_variants_share_one_key(self, spelling: str) -> None:
        assert normalize_key(spelling) == "bi10773"

    def test_greek_letters_transliterate_rather_than_vanish(self) -> None:
        # Stripping greek outright would make alpha- and beta- prefixed
        # compounds collide, which is a wrong answer, not a miss.
        assert normalize_key("α-Tocopherol") == normalize_key("alpha-Tocopherol")
        assert normalize_key("β-Carotene") != normalize_key("α-Carotene")

    def test_cas_style_dotted_prefix_matches_ascii_spelling(self) -> None:
        assert normalize_key(".beta.-Carotene") == normalize_key("beta-carotene")

    @pytest.mark.parametrize("blank", ["", "   ", "---", "()"])
    def test_content_free_input_yields_empty_key(self, blank: str) -> None:
        assert normalize_key(blank) == ""


@pytest.fixture(scope="module")
def normalizer() -> DrugNameNormalizer:
    if not DEFAULT_DB_PATH.exists():
        pytest.skip(f"PubChem DB not built at {DEFAULT_DB_PATH}")
    return DrugNameNormalizer()


class TestLookup:
    @pytest.mark.parametrize(("query", "expected"), DEVELOPMENT_CODES)
    def test_resolves_to_expected_canonical_name(
        self, normalizer: DrugNameNormalizer, query: str, expected: str
    ) -> None:
        result = normalizer.normalize(query)
        assert result is not None, f"{query} not found"
        assert result.canonical_name == expected

    def test_match_type_is_reported_honestly(self, normalizer: DrugNameNormalizer) -> None:
        # PubChem stores this brand only as "JARDIANCE", so one drug exercises
        # all three tiers: the stored spelling, its case variant, and the
        # trademarked form that only survives punctuation collapsing.
        assert normalizer.normalize("JARDIANCE").match_type == MATCH_EXACT
        assert normalizer.normalize("Jardiance").match_type == MATCH_CASE_FOLDED
        assert normalizer.normalize("Jardiance®").match_type == MATCH_PUNCT_NORMALIZED

    def test_result_carries_a_cid(self, normalizer: DrugNameNormalizer) -> None:
        result = normalizer.normalize("Jardiance")
        assert result.cid > 0
        assert any(c.cid == result.cid for c in result.candidates)

    @pytest.mark.parametrize("junk", ["", "   ", "zzzz-not-a-drug-9999999", "()"])
    def test_unknown_input_is_a_clean_miss(self, normalizer: DrugNameNormalizer, junk: str) -> None:
        # A wrong answer is far more expensive than no answer: a bad map
        # produces a cohort that silently matches zero patients.
        assert normalizer.normalize(junk) is None

    def test_ly2189265_records_actual_behaviour(self, normalizer: DrugNameNormalizer) -> None:
        """LY2189265 (dulaglutide) fails against the live PubChem API.

        This test documents whatever the local snapshot does rather than
        forcing a pass: if it resolves it must resolve to dulaglutide, and if
        it does not it must be a clean miss.  It must never come back as some
        unrelated compound.
        """
        result = normalizer.normalize("LY2189265")
        if result is not None:
            assert "dulaglutide" in result.canonical_name.casefold()

    def test_placeholder_titles_are_never_returned_as_a_name(
        self, normalizer: DrugNameNormalizer
    ) -> None:
        """Every PubChem record for tirzepatide is titled "CID <n>".

        Returning that string would send the mapper off to embed a non-name and
        map it to an arbitrary concept -- the exact production failure this
        module exists to stop -- so a nameless hit must degrade to a miss.
        """
        assert normalizer.normalize("tirzepatide") is None
        for name in ("BI 10773", "AZD6140", "insulin glargine"):
            result = normalizer.normalize(name)
            assert result is not None
            assert not any(c.title.startswith("CID ") and c.title[4:].isdigit() for c in result.candidates)

    def test_ambiguity_is_exposed_not_silently_resolved(self, normalizer: DrugNameNormalizer) -> None:
        # "aspirin" is one compound under many CIDs; "MK-0431" style codes and
        # short generic strings are where several distinct titles collide.
        result = normalizer.normalize("aspirin")
        assert result is not None
        assert result.is_ambiguous == (len({c.title for c in result.candidates}) > 1)

    def test_lookup_uses_the_index(self, normalizer: DrugNameNormalizer) -> None:
        """A sequential scan over ~10^8 rows would make the mapper unusable."""
        plan = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True).execute(
            "EXPLAIN QUERY PLAN SELECT s.cid FROM synonym s JOIN title t ON t.cid = s.cid WHERE s.key = ?",
            ("empagliflozin",),
        ).fetchall()
        assert any("idx_synonym_key" in str(row) for row in plan), plan

    def test_read_only_connection_rejects_writes(self, normalizer: DrugNameNormalizer) -> None:
        with pytest.raises(sqlite3.OperationalError):
            normalizer._conn.execute("DELETE FROM synonym WHERE key = 'empagliflozin'")
