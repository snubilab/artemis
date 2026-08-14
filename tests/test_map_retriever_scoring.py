"""
SPEC-MAP-001: Unit tests for retriever vocabulary preference and standard concept scoring.

Tests verify that the scoring pipeline in ConceptRetriever.search() correctly
applies vocabulary preferences and standard_concept bonuses/penalties.
"""
import pytest
from unittest.mock import MagicMock, patch

from src.agents.agent2.retriever import (
    CandidateConcept,
    ConceptRetriever,
    _VOCAB_PREFERENCE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_collection(candidates: list[dict]) -> MagicMock:
    """
    Build a mock ChromaDB collection that returns the given candidates.

    Each candidate dict should have:
        concept_id, concept_name, domain_id, vocabulary_id,
        concept_class_id, distance, and optionally standard_concept.
    """
    ids = [str(c["concept_id"]) for c in candidates]
    documents = [c["concept_name"] for c in candidates]
    metadatas = []
    for c in candidates:
        meta = {
            "concept_id": c["concept_id"],
            "vocabulary_id": c["vocabulary_id"],
            "concept_class_id": c["concept_class_id"],
            "domain_id": c["domain_id"],
        }
        if "standard_concept" in c:
            meta["standard_concept"] = c["standard_concept"]
        metadatas.append(meta)
    distances = [c["distance"] for c in candidates]

    collection = MagicMock()
    collection.query.return_value = {
        "ids": [ids],
        "metadatas": [metadatas],
        "distances": [distances],
        "documents": [documents],
    }
    return collection


def _build_retriever(candidates: list[dict]) -> ConceptRetriever:
    """Create a ConceptRetriever with a mocked collection and no weight files."""
    collection = _make_mock_collection(candidates)
    with patch("src.agents.agent2.retriever.get_collection", return_value=collection):
        retriever = ConceptRetriever.__new__(ConceptRetriever)
        retriever.collection = collection
        retriever.concept_weights = {}
    return retriever


# ---------------------------------------------------------------------------
# M1: Vocabulary Preference Tests
# ---------------------------------------------------------------------------

class TestVocabPreferenceMeasurement:
    """REQ-01/02: LOINC should win over SNOMED for Measurement domain."""

    def test_hba1c_loinc_beats_snomed(self):
        """HbA1c query: LOINC 3004410 should rank above SNOMED 37171451."""
        candidates = [
            {
                "concept_id": 37171451,
                "concept_name": "Hemoglobin A1c measurement",
                "domain_id": "Measurement",
                "vocabulary_id": "SNOMED",
                "concept_class_id": "Procedure",
                "distance": 0.30,
            },
            {
                "concept_id": 3004410,
                "concept_name": "Hemoglobin A1c/Hemoglobin.total in Blood",
                "domain_id": "Measurement",
                "vocabulary_id": "LOINC",
                "concept_class_id": "Lab Test",
                "distance": 0.32,
            },
        ]
        retriever = _build_retriever(candidates)
        results = retriever.search("HbA1c", n_results=5, domain_hint="Measurement")

        assert len(results) == 2
        assert results[0].concept_id == 3004410, (
            f"LOINC concept should rank first, got {results[0].vocabulary_id}"
        )

    def test_measurement_loinc_gap_is_at_least_0_40(self):
        """Verify the LOINC-SNOMED gap is large enough (>= 0.40)."""
        loinc_bonus = _VOCAB_PREFERENCE["Measurement"]["LOINC"]
        snomed_penalty = _VOCAB_PREFERENCE["Measurement"]["SNOMED"]
        gap = snomed_penalty - loinc_bonus
        assert gap >= 0.40, f"Measurement LOINC gap should be >= 0.40, got {gap}"


class TestVocabPreferenceDrug:
    """REQ-03: RxNorm should win over RxNorm Extension for Drug domain.

    This class used to pit RxNorm against ATC. The collection holds no ATC row in the
    Drug domain -- `omop_concepts_medcpt` returns only RxNorm and RxNorm Extension there
    -- so those tests asserted over a candidate the retriever can never produce and could
    not fail for the reason they claimed. The pair below is the one the Drug entry in
    `_VOCAB_PREFERENCE` actually decides, and it decides it for real seeds: 'Sitagliptin'
    resolves to RxNorm 'sitagliptin' with the preference on and to RxNorm Extension
    'sitagliptin 32.1 MG Oral Tablet' with it off.
    """

    def test_rxnorm_beats_rxnorm_extension(self):
        """Drug query: plain RxNorm should rank above RxNorm Extension at equal distance.

        Both candidates carry the SAME name on purpose. The name-match boost is worth
        -0.15 for an exact hit against -0.08 for a substring, which is larger than the
        0.10 the vocabulary entries are separated by -- so pairing a bare ingredient
        against a packaged form ('sitagliptin 32.1 MG Oral Tablet') produces a test that
        passes even with the Drug preferences deleted outright. RxNorm Extension does
        carry ingredient-named Drug rows (HEMOGLOBIN among them), so an equal-name pair
        is the realistic case as well as the sensitive one.
        """
        candidates = [
            {
                "concept_id": 1235495,
                "concept_name": "sitagliptin",
                "domain_id": "Drug",
                "vocabulary_id": "RxNorm Extension",
                "concept_class_id": "Ingredient",
                "distance": 0.25,
            },
            {
                "concept_id": 1580747,
                "concept_name": "sitagliptin",
                "domain_id": "Drug",
                "vocabulary_id": "RxNorm",
                "concept_class_id": "Ingredient",
                "distance": 0.25,
            },
        ]
        retriever = _build_retriever(candidates)
        results = retriever.search("Sitagliptin", n_results=5, domain_hint="Drug")

        assert results[0].vocabulary_id == "RxNorm", (
            f"RxNorm should rank first for Drug, got {results[0].vocabulary_id}"
        )

    def test_drug_prefers_rxnorm_over_the_extension_by_a_clear_margin(self):
        """The two Drug vocabularies must stay separated, not merely ordered.

        Both carry a bonus, so the gap is what decides an ingredient against a branded or
        packaged form at equal distance. 0.10 is the current separation; anything smaller
        lets the distance noise between two near-identical names flip the order.
        """
        rxnorm_bonus = _VOCAB_PREFERENCE["Drug"]["RxNorm"]
        extension_bonus = _VOCAB_PREFERENCE["Drug"]["RxNorm Extension"]
        # Rounded because the intended 0.10 is 0.09999999999999999 in binary floating
        # point, and a bare `>=` fails on the very values this is meant to accept.
        gap = round(extension_bonus - rxnorm_bonus, 6)
        assert gap >= 0.10, f"Drug RxNorm-Extension gap should be >= 0.10, got {gap}"


class TestVocabPreferenceCondition:
    """REQ-04: SNOMED should win over the other Condition vocabularies.

    Previously asserted against ICD10CM, which the collection holds no Condition row for.
    What SNOMED actually competes with in that domain is HCPCS and OMOP Extension, and
    neither is listed in `_VOCAB_PREFERENCE`, so both are scored with the default +0.05.
    """

    def test_snomed_beats_an_unlisted_condition_vocabulary(self):
        """Condition query: SNOMED should rank above OMOP Extension at equal distance."""
        candidates = [
            {
                "concept_id": 2000,
                "concept_name": "Type 2 diabetes mellitus",
                "domain_id": "Condition",
                "vocabulary_id": "OMOP Extension",
                "concept_class_id": "Disorder",
                "distance": 0.20,
            },
            {
                "concept_id": 2001,
                "concept_name": "Type 2 diabetes mellitus",
                "domain_id": "Condition",
                "vocabulary_id": "SNOMED",
                "concept_class_id": "Disorder",
                "distance": 0.20,
            },
        ]
        retriever = _build_retriever(candidates)
        results = retriever.search(
            "Type 2 diabetes mellitus", n_results=5, domain_hint="Condition",
        )

        assert results[0].vocabulary_id == "SNOMED", (
            f"SNOMED should rank first for Condition, got {results[0].vocabulary_id}"
        )


# ---------------------------------------------------------------------------
# M2: Standard Concept Scoring Tests
# ---------------------------------------------------------------------------

class TestStandardConceptScoring:
    """REQ-05: Standard concepts (S) should be preferred over non-standard."""

    def test_standard_s_beats_null(self):
        """Standard concept (S) should score better than non-standard (NULL)."""
        candidates = [
            {
                "concept_id": 3000,
                "concept_name": "Aspirin",
                "domain_id": "Drug",
                "vocabulary_id": "RxNorm",
                "concept_class_id": "Ingredient",
                "distance": 0.20,
                "standard_concept": None,
            },
            {
                "concept_id": 3001,
                "concept_name": "Aspirin",
                "domain_id": "Drug",
                "vocabulary_id": "RxNorm",
                "concept_class_id": "Ingredient",
                "distance": 0.20,
                "standard_concept": "S",
            },
        ]
        retriever = _build_retriever(candidates)
        results = retriever.search("Aspirin", n_results=5, domain_hint="Drug")

        assert results[0].concept_id == 3001, (
            f"Standard concept (S) should rank first, got concept_id={results[0].concept_id}"
        )

    def test_classification_c_no_penalty(self):
        """Classification concept (C) should get no adjustment (neutral)."""
        candidates = [
            {
                "concept_id": 4000,
                "concept_name": "Diabetes",
                "domain_id": "Condition",
                "vocabulary_id": "SNOMED",
                "concept_class_id": "Disorder",
                "distance": 0.20,
                "standard_concept": "C",
            },
            {
                "concept_id": 4001,
                "concept_name": "Diabetes",
                "domain_id": "Condition",
                "vocabulary_id": "SNOMED",
                "concept_class_id": "Disorder",
                "distance": 0.20,
                "standard_concept": "S",
            },
        ]
        retriever = _build_retriever(candidates)
        results = retriever.search("Diabetes", n_results=5, domain_hint="Condition")

        # S gets -0.10 boost, C gets 0.0 => S should still win
        assert results[0].concept_id == 4001, (
            "Standard (S) should rank above Classification (C)"
        )

    def test_graceful_fallback_no_standard_concept_in_metadata(self):
        """When standard_concept is missing from metadata, scoring should not crash."""
        candidates = [
            {
                "concept_id": 5000,
                "concept_name": "Test Concept",
                "domain_id": "Condition",
                "vocabulary_id": "SNOMED",
                "concept_class_id": "Disorder",
                "distance": 0.25,
                # no standard_concept key at all
            },
        ]
        retriever = _build_retriever(candidates)
        results = retriever.search("Test Concept", n_results=5, domain_hint="Condition")

        assert len(results) == 1
        assert results[0].concept_id == 5000

    def test_empty_string_treated_as_non_standard(self):
        """Empty string standard_concept should be penalized like NULL."""
        candidates = [
            {
                "concept_id": 6000,
                "concept_name": "Something",
                "domain_id": "Drug",
                "vocabulary_id": "RxNorm",
                "concept_class_id": "Ingredient",
                "distance": 0.20,
                "standard_concept": "",
            },
            {
                "concept_id": 6001,
                "concept_name": "Something",
                "domain_id": "Drug",
                "vocabulary_id": "RxNorm",
                "concept_class_id": "Ingredient",
                "distance": 0.20,
                "standard_concept": "S",
            },
        ]
        retriever = _build_retriever(candidates)
        results = retriever.search("Something", n_results=5, domain_hint="Drug")

        assert results[0].concept_id == 6001, (
            "Standard (S) should rank above empty-string standard_concept"
        )
