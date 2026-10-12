"""TDD tests for Instance 4 fix: no placeholder concept set is ever injected.

RED phase: these tests define the new expected behavior —
ModuleNotFoundError must re-raise (not silently inject placeholder concepts).
"""
import pytest
from unittest.mock import MagicMock, patch


def _make_service():
    """Create a minimal TTEService with mocked dependencies."""
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc.store = MagicMock()
    return svc


class TestRecommendSeededConceptSetNoPlaceholderFallback:
    """Main mapping path must raise ModuleNotFoundError rather than return placeholder."""

    def test_module_not_found_propagates_from_rag_fallback_path(self):
        """If ChromaDB is missing, RAG fallback must raise, not return placeholder."""
        svc = _make_service()

        def _raise(*args, **kwargs):
            raise ModuleNotFoundError("No module named 'chromadb'")

        # The RAG fallback calls _get_seeded_concept_set_recommender — patch that
        with patch.object(svc, "_get_seeded_concept_set_recommender", side_effect=_raise):
            with pytest.raises(ModuleNotFoundError):
                svc._recommend_seeded_concept_set_rag_fallback(
                    "ticagrelor",
                    expected_domain="Drug",
                )

    def test_rag_fallback_propagates_module_not_found(self):
        """RAG fallback path must raise ModuleNotFoundError too."""
        svc = _make_service()

        def _raise(*args, **kwargs):
            raise ModuleNotFoundError("No module named 'chromadb'")

        with patch.object(svc, "_get_seeded_concept_set_recommender", side_effect=_raise):
            with pytest.raises(ModuleNotFoundError):
                svc._recommend_seeded_concept_set_rag_fallback(
                    "ticagrelor",
                    expected_domain="Drug",
                )

    def test_placeholder_concept_set_not_returned_on_chromadb_failure(self):
        """No dict with VOCABULARY_ID='ARTEMIS' must be returned on ChromaDB failure."""
        svc = _make_service()

        def _raise(*args, **kwargs):
            raise ModuleNotFoundError("chromadb missing")

        with patch.object(svc, "_get_seeded_concept_set_recommender", side_effect=_raise):
            with patch.object(svc, "_recommend_seeded_concept_set_rag_fallback", side_effect=_raise):
                try:
                    result = svc._recommend_seeded_concept_set("ticagrelor")
                except ModuleNotFoundError:
                    result = None

        # Must not have silently returned a placeholder
        assert result is None or (
            isinstance(result, dict)
            and result.get("expression", {}).get("items", [{}])[0].get("concept", {}).get("VOCABULARY_ID") != "ARTEMIS"
        )
