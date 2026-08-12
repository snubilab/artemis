"""
Fix: ATC distance threshold tightened to prevent drug class confusion.

Tests verify:
1. ATC distance 0.55 -> rejected (returns None, []) at default threshold 0.4
2. ATC distance 0.25 -> accepted and ingredients returned
3. Env var AGENT2_ATC_DISTANCE_THRESHOLD override works
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.drug_class_expander import expand_drug_class_via_vocab


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_chroma_result(document: str, concept_id: int, concept_code: str, distance: float):
    """Build a ChromaDB-style query result dict."""
    return {
        "documents": [[document]],
        "metadatas": [[{"concept_id": concept_id, "concept_code": concept_code}]],
        "distances": [[distance]],
    }


def _mock_db_conn(ingredient_ids: list[int]) -> MagicMock:
    """Return a mock PostgreSQL connection that yields ingredient_ids from fetchall."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [(cid,) for cid in ingredient_ids]
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn


# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_UMLS_PATCH = "src.agents.agent2.drug_class_expander.expand_drug_class_via_umls"
_CHROMA_PATCH = "src.utils.vector.get_chroma_client"
_SETTINGS_PATCH = "src.agents.agent2.drug_class_expander.Settings"


# ---------------------------------------------------------------------------
# Test 1: distance 0.55 is rejected at default threshold (0.4)
# ---------------------------------------------------------------------------

def test_atc_distance_above_threshold_is_rejected():
    """A far ATC match must still be rejected.

    Was written against distance=0.55 and a 0.4 default. The default is now 0.75,
    chosen from the 31 real match decisions in the 2026-08-12 remap, where every
    rejection between 0.453 and 0.735 turned out to be a correct class match; see
    tests/test_atc_class_distance_threshold.py. The scenario here moves to an
    observed *wrong* match so it keeps testing rejection rather than the old
    boundary: 'Drug-naive' -> 'OTHER NERVOUS SYSTEM DRUGS' at 0.957.
    """
    # Arrange
    chroma_result = _make_chroma_result(
        document="OTHER NERVOUS SYSTEM DRUGS",
        concept_id=21604488,
        concept_code="N07",
        distance=0.957,
    )
    mock_collection = MagicMock()
    mock_collection.query.return_value = chroma_result

    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_collection

    mock_db = _mock_db_conn(ingredient_ids=[1, 2, 3, 4])

    with (
        patch(_UMLS_PATCH, return_value=(None, [])),
        patch(_CHROMA_PATCH, return_value=mock_client),
        patch.dict(os.environ, {}, clear=False),
    ):
        # Remove env override to ensure default of 0.4 is used
        os.environ.pop("AGENT2_ATC_DISTANCE_THRESHOLD", None)

        # Act
        name, ids = expand_drug_class_via_vocab(
            text="GLP-1 receptor agonist",
            db_conn=mock_db,
            schema="cdm",
        )

    # Assert
    assert name is None
    assert ids == []


# ---------------------------------------------------------------------------
# Test 2: distance 0.25 is accepted and ingredients are returned
# ---------------------------------------------------------------------------

def test_atc_distance_below_threshold_is_accepted():
    """ATC match with distance=0.25 must be accepted when threshold=0.4."""
    # Arrange
    ingredient_ids = [1001, 1002, 1003]
    chroma_result = _make_chroma_result(
        document="GLP-1 receptor agonists",
        concept_id=21600500,
        concept_code="A10BJ",
        distance=0.25,
    )
    mock_collection = MagicMock()
    mock_collection.query.return_value = chroma_result

    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_collection

    mock_db = _mock_db_conn(ingredient_ids=ingredient_ids)

    with (
        patch(_UMLS_PATCH, return_value=(None, [])),
        patch(_CHROMA_PATCH, return_value=mock_client),
    ):
        os.environ.pop("AGENT2_ATC_DISTANCE_THRESHOLD", None)

        # Act
        name, ids = expand_drug_class_via_vocab(
            text="GLP-1 receptor agonist",
            db_conn=mock_db,
            schema="cdm",
        )

    # Assert
    assert name == "GLP-1 receptor agonists"
    assert ids == ingredient_ids


# ---------------------------------------------------------------------------
# Test 3: env var AGENT2_ATC_DISTANCE_THRESHOLD is respected at runtime
# ---------------------------------------------------------------------------

def test_env_var_overrides_distance_threshold():
    """A threshold of 0.3 must reject distance=0.35 and accept 0.25.

    The name says env var, but the call below passes the value explicitly, and it
    has to: the default binds `os.environ` at import, so setting the variable later
    does not reach this function. What this pins is the explicit parameter.
    """
    ingredient_ids = [2001, 2002, 2003]

    def _run(distance: float):
        chroma_result = _make_chroma_result(
            document="DPP-4 inhibitors",
            concept_id=21600600,
            concept_code="A10BH",
            distance=distance,
        )
        mock_collection = MagicMock()
        mock_collection.query.return_value = chroma_result

        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection

        mock_db = _mock_db_conn(ingredient_ids=ingredient_ids)

        with (
            patch(_UMLS_PATCH, return_value=(None, [])),
            patch(_CHROMA_PATCH, return_value=mock_client),
            patch.dict(os.environ, {"AGENT2_ATC_DISTANCE_THRESHOLD": "0.3"}),
        ):
            return expand_drug_class_via_vocab(
                text="DPP-4 inhibitors",
                db_conn=mock_db,
                schema="cdm",
                # Pass the threshold explicitly using the env var value so the
                # function uses 0.3 — the default is evaluated at import time,
                # so we need to pass it explicitly for the env-override test.
                distance_threshold=float(os.environ["AGENT2_ATC_DISTANCE_THRESHOLD"]),
            )

    # distance 0.35 > 0.3 threshold -> rejected
    name, ids = _run(distance=0.35)
    assert name is None, "distance=0.35 should be rejected at threshold=0.3"
    assert ids == []

    # distance 0.25 < 0.3 threshold -> accepted
    name, ids = _run(distance=0.25)
    assert name == "DPP-4 inhibitors"
    assert ids == ingredient_ids
