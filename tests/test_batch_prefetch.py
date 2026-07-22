"""Tests for ConceptRetriever.batch_search() method."""
import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.retriever import CandidateConcept, ConceptRetriever


@pytest.fixture
def mock_collection():
    return MagicMock()


@pytest.fixture
def retriever(mock_collection):
    with patch("src.agents.agent2.retriever.get_collection", return_value=mock_collection):
        r = ConceptRetriever.__new__(ConceptRetriever)
        r.collection = mock_collection
        r.concept_weights = {}
    return r


def _make_query_result(ids_per_query, metadatas_per_query, distances_per_query, documents_per_query):
    """Helper to build ChromaDB-style multi-query result dict."""
    return {
        "ids": ids_per_query,
        "metadatas": metadatas_per_query,
        "distances": distances_per_query,
        "documents": documents_per_query,
    }


class TestBatchSearchSingleQuery:
    def test_single_query_returns_correct_mapping(self, retriever, mock_collection):
        mock_collection.query.return_value = _make_query_result(
            ids_per_query=[["1234", "5678"]],
            metadatas_per_query=[[
                {"domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S"},
                {"domain_id": "Condition", "vocabulary_id": "ICD10CM", "concept_class_id": "Disorder", "standard_concept": "S"},
            ]],
            distances_per_query=[[0.10, 0.25]],
            documents_per_query=[["Heart failure", "Congestive heart failure"]],
        )

        result = retriever.batch_search(["heart failure"], n_results=10)

        assert "heart failure" in result
        assert len(result["heart failure"]) == 2
        assert result["heart failure"][0].concept_id == 1234
        assert result["heart failure"][0].concept_name == "Heart failure"
        mock_collection.query.assert_called_once()


class TestBatchSearchMultipleQueries:
    def test_multiple_queries_return_per_query_mapping(self, retriever, mock_collection):
        mock_collection.query.return_value = _make_query_result(
            ids_per_query=[["1234"], ["9999"]],
            metadatas_per_query=[[
                {"domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S"},
            ], [
                {"domain_id": "Drug", "vocabulary_id": "RxNorm", "concept_class_id": "Ingredient", "standard_concept": "S"},
            ]],
            distances_per_query=[[0.10], [0.20]],
            documents_per_query=[["Diabetes mellitus"], ["Metformin"]],
        )

        result = retriever.batch_search(["diabetes", "metformin"], n_results=5)

        assert len(result) == 2
        assert "diabetes" in result
        assert "metformin" in result
        assert result["diabetes"][0].concept_id == 1234
        assert result["metformin"][0].concept_id == 9999


class TestBatchSearchDomainHintGrouping:
    def test_same_domain_hint_batched_together(self, retriever, mock_collection):
        mock_collection.query.return_value = _make_query_result(
            ids_per_query=[["1234"], ["5678"]],
            metadatas_per_query=[[
                {"domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S"},
            ], [
                {"domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S"},
            ]],
            distances_per_query=[[0.10], [0.20]],
            documents_per_query=[["Heart failure"], ["Stroke"]],
        )

        result = retriever.batch_search(
            ["heart failure", "stroke"],
            n_results=5,
            domain_hints=["Condition", "Condition"],
        )

        # Single call because same domain_hint
        assert mock_collection.query.call_count == 1
        call_kwargs = mock_collection.query.call_args[1]
        assert call_kwargs["where"] == {"domain_id": "Condition"}
        assert len(result) == 2

    def test_different_domain_hints_produce_separate_calls(self, retriever, mock_collection):
        # First call for Condition, second for Drug
        mock_collection.query.side_effect = [
            _make_query_result(
                ids_per_query=[["1234"]],
                metadatas_per_query=[[{"domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S"}]],
                distances_per_query=[[0.10]],
                documents_per_query=[["Heart failure"]],
            ),
            _make_query_result(
                ids_per_query=[["9999"]],
                metadatas_per_query=[[{"domain_id": "Drug", "vocabulary_id": "RxNorm", "concept_class_id": "Ingredient", "standard_concept": "S"}]],
                distances_per_query=[[0.15]],
                documents_per_query=[["Metformin"]],
            ),
        ]

        result = retriever.batch_search(
            ["heart failure", "metformin"],
            n_results=5,
            domain_hints=["Condition", "Drug"],
        )

        assert mock_collection.query.call_count == 2
        assert len(result) == 2
        assert result["heart failure"][0].domain_id == "Condition"
        assert result["metformin"][0].domain_id == "Drug"

    def test_none_domain_hints_batched_without_filter(self, retriever, mock_collection):
        mock_collection.query.return_value = _make_query_result(
            ids_per_query=[["1234"], ["5678"]],
            metadatas_per_query=[[
                {"domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S"},
            ], [
                {"domain_id": "Drug", "vocabulary_id": "RxNorm", "concept_class_id": "Ingredient", "standard_concept": "S"},
            ]],
            distances_per_query=[[0.10], [0.20]],
            documents_per_query=[["Heart failure"], ["Metformin"]],
        )

        result = retriever.batch_search(
            ["heart failure", "metformin"],
            n_results=5,
            domain_hints=[None, None],
        )

        assert mock_collection.query.call_count == 1
        call_kwargs = mock_collection.query.call_args[1]
        assert "where" not in call_kwargs or call_kwargs.get("where") is None


class TestBatchSearchEdgeCases:
    def test_empty_input_returns_empty_dict(self, retriever, mock_collection):
        result = retriever.batch_search([], n_results=5)

        assert result == {}
        mock_collection.query.assert_not_called()

    def test_chromadb_error_returns_empty_results_with_warning(self, retriever, mock_collection, caplog):
        mock_collection.query.side_effect = RuntimeError("ChromaDB connection failed")

        with caplog.at_level(logging.WARNING):
            result = retriever.batch_search(["heart failure"], n_results=5)

        assert result == {"heart failure": []}
        assert any("batch_search" in record.message.lower() or "chroma" in record.message.lower() for record in caplog.records)


class TestBatchSearchScoring:
    def test_applies_vocab_preference_scoring(self, retriever, mock_collection):
        """SNOMED Condition gets -0.10 bonus, ICD10CM gets +0.05."""
        mock_collection.query.return_value = _make_query_result(
            ids_per_query=[["1234", "5678"]],
            metadatas_per_query=[[
                {"domain_id": "Condition", "vocabulary_id": "ICD10CM", "concept_class_id": "Disorder", "standard_concept": "S"},
                {"domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S"},
            ]],
            distances_per_query=[[0.10, 0.10]],  # same distance
            documents_per_query=[["Heart failure ICD", "Heart failure SNOMED"]],
        )

        result = retriever.batch_search(
            ["heart failure"],
            n_results=10,
            domain_hints=["Condition"],
        )

        candidates = result["heart failure"]
        # SNOMED should rank higher (lower adjusted_score) than ICD10CM at same distance
        snomed = next(c for c in candidates if c.vocabulary_id == "SNOMED")
        icd = next(c for c in candidates if c.vocabulary_id == "ICD10CM")
        assert snomed.adjusted_score < icd.adjusted_score

    def test_applies_exact_match_boost(self, retriever, mock_collection):
        mock_collection.query.return_value = _make_query_result(
            ids_per_query=[["1234", "5678"]],
            metadatas_per_query=[[
                {"domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S"},
                {"domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S"},
            ]],
            distances_per_query=[[0.10, 0.10]],
            documents_per_query=[["Heart failure", "Cardiac insufficiency"]],
        )

        result = retriever.batch_search(["heart failure"], n_results=10)

        candidates = result["heart failure"]
        exact = next(c for c in candidates if c.concept_name == "Heart failure")
        other = next(c for c in candidates if c.concept_name == "Cardiac insufficiency")
        assert exact.adjusted_score < other.adjusted_score


def _make_single_query_result(query_text: str) -> dict:
    """Helper to build a single-query ChromaDB result for chunking tests."""
    return _make_query_result(
        ids_per_query=[[str(hash(query_text) % 100000)]],
        metadatas_per_query=[[{
            "domain_id": "Condition",
            "vocabulary_id": "SNOMED",
            "concept_class_id": "Disorder",
            "standard_concept": "S",
        }]],
        distances_per_query=[[0.10]],
        documents_per_query=[[f"doc_{query_text}"]],
    )


def _make_multi_query_result(query_texts: list[str]) -> dict:
    """Helper to build a multi-query ChromaDB result for chunking tests."""
    return _make_query_result(
        ids_per_query=[[str(hash(qt) % 100000)] for qt in query_texts],
        metadatas_per_query=[[{
            "domain_id": "Condition",
            "vocabulary_id": "SNOMED",
            "concept_class_id": "Disorder",
            "standard_concept": "S",
        }] for _ in query_texts],
        distances_per_query=[[0.10] for _ in query_texts],
        documents_per_query=[[f"doc_{qt}"] for qt in query_texts],
    )


class TestBatchSearchChunking:
    def test_batch_search_chunks_large_input(self, retriever, mock_collection):
        """120 queries with max_batch_size=50 should produce 3 ChromaDB calls."""
        queries = [f"query_{i}" for i in range(120)]

        def side_effect_fn(**kwargs):
            return _make_multi_query_result(kwargs["query_texts"])

        mock_collection.query.side_effect = side_effect_fn

        result = retriever.batch_search(queries, n_results=5, max_batch_size=50)

        assert mock_collection.query.call_count == 3
        # Verify chunk sizes: 50, 50, 20
        call_sizes = [len(c.kwargs["query_texts"]) for c in mock_collection.query.call_args_list]
        assert call_sizes == [50, 50, 20]
        # All 120 queries should have results
        assert len(result) == 120
        for q in queries:
            assert q in result
            assert len(result[q]) == 1

    def test_batch_search_small_input_single_call(self, retriever, mock_collection):
        """Queries within max_batch_size should produce a single ChromaDB call."""
        queries = [f"query_{i}" for i in range(30)]

        def side_effect_fn(**kwargs):
            return _make_multi_query_result(kwargs["query_texts"])

        mock_collection.query.side_effect = side_effect_fn

        result = retriever.batch_search(queries, n_results=5, max_batch_size=50)

        assert mock_collection.query.call_count == 1
        assert len(result) == 30

    def test_batch_search_env_override(self, retriever, mock_collection, monkeypatch):
        """CHROMA_BATCH_SIZE=10 should override default max_batch_size."""
        monkeypatch.setenv("CHROMA_BATCH_SIZE", "10")

        queries = [f"query_{i}" for i in range(25)]

        def side_effect_fn(**kwargs):
            return _make_multi_query_result(kwargs["query_texts"])

        mock_collection.query.side_effect = side_effect_fn

        result = retriever.batch_search(queries, n_results=5)

        # 25 queries / batch size 10 = 3 calls (10+10+5)
        assert mock_collection.query.call_count == 3
        call_sizes = [len(c.kwargs["query_texts"]) for c in mock_collection.query.call_args_list]
        assert call_sizes == [10, 10, 5]
        assert len(result) == 25
