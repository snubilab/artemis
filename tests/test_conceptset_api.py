"""
Tests for ConceptSet API endpoints - SPEC-UI-002

Tests for the /recommend-and-save endpoint that recommends a concept set
and persists it to Atlas WebAPI, returning the saved concept set ID.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers: create a minimal FastAPI test app for the conceptset router
# ---------------------------------------------------------------------------

def make_client():
    """Build a TestClient for the conceptset API router in isolation."""
    from fastapi import FastAPI
    from src.agents.conceptset.api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return make_client()


def make_mock_recommender(concept_set_id_in_atlas=None, name="Test Concept Set"):
    """Build a mock recommender that returns a deterministic result."""
    mock_rec = MagicMock()

    atlas_json = {
        "query": "test query",
        "conceptSets": [
            {
                "name": name,
                "expression": {"items": [{"concept": {"CONCEPT_ID": 312327}}]},
                "defaultLogic": "INCLUDE",
            }
        ],
        "cached": False,
    }
    mock_result = MagicMock()
    mock_result.to_atlas_json.return_value = atlas_json
    mock_rec.recommend.return_value = mock_result
    return mock_rec


# ---------------------------------------------------------------------------
# Tests: recommend-and-save endpoint
# ---------------------------------------------------------------------------

class TestRecommendAndSave:
    """Tests for POST /api/conceptset/recommend-and-save"""

    def test_returns_id_and_name_on_success(self, client):
        """AC: On success, endpoint returns concept set id and name from Atlas."""
        mock_rec = make_mock_recommender()

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.headers.get = MagicMock(return_value="application/json")
        mock_response.json.return_value = {"id": 42, "name": "Test Concept Set"}

        with patch("src.agents.conceptset.api.get_recommender", return_value=mock_rec), \
             patch("httpx.AsyncClient") as mock_http_class:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_http_class.return_value = mock_http

            response = client.post(
                "/api/conceptset/recommend-and-save",
                json={"query": "Type 2 Diabetes"}
            )

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "name" in data
        assert data["id"] == 42
        assert data["name"] == "Test Concept Set"

    def test_validates_query_min_length(self, client):
        """AC: Request with single-char query is rejected with 422."""
        response = client.post(
            "/api/conceptset/recommend-and-save",
            json={"query": "x"}
        )
        assert response.status_code == 422

    def test_validates_query_required(self, client):
        """AC: Request without query field is rejected with 422."""
        response = client.post(
            "/api/conceptset/recommend-and-save",
            json={}
        )
        assert response.status_code == 422

    def test_validates_top_k_range(self, client):
        """AC: top_k out of range is rejected with 422."""
        response = client.post(
            "/api/conceptset/recommend-and-save",
            json={"query": "Diabetes", "top_k": 0}
        )
        assert response.status_code == 422

        response = client.post(
            "/api/conceptset/recommend-and-save",
            json={"query": "Diabetes", "top_k": 11}
        )
        assert response.status_code == 422

    def test_webapi_error_returns_502(self, client):
        """AC: When Atlas WebAPI returns error status, endpoint returns 502."""
        mock_rec = make_mock_recommender()

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("src.agents.conceptset.api.get_recommender", return_value=mock_rec), \
             patch("httpx.AsyncClient") as mock_http_class:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_http_class.return_value = mock_http

            response = client.post(
                "/api/conceptset/recommend-and-save",
                json={"query": "Heart Failure"}
            )

        assert response.status_code == 502

    def test_no_concept_sets_returns_404(self, client):
        """AC: When recommender returns no concept sets, endpoint returns 404."""
        mock_rec = MagicMock()
        mock_result = MagicMock()
        mock_result.to_atlas_json.return_value = {
            "query": "test",
            "conceptSets": [],
            "cached": False,
        }
        mock_rec.recommend.return_value = mock_result

        with patch("src.agents.conceptset.api.get_recommender", return_value=mock_rec):
            response = client.post(
                "/api/conceptset/recommend-and-save",
                json={"query": "Unknown condition xyz"}
            )

        assert response.status_code == 404

    def test_webapi_missing_id_returns_502(self, client):
        """AC: When Atlas WebAPI returns 201 but no id, endpoint returns 502."""
        mock_rec = make_mock_recommender()

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.headers.get = MagicMock(return_value="application/json")
        mock_response.json.return_value = {"name": "Something", "id": None}

        with patch("src.agents.conceptset.api.get_recommender", return_value=mock_rec), \
             patch("httpx.AsyncClient") as mock_http_class:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_http_class.return_value = mock_http

            response = client.post(
                "/api/conceptset/recommend-and-save",
                json={"query": "Heart Failure"}
            )

        assert response.status_code == 502

    def test_uses_webapi_url_env_var(self, client, monkeypatch):
        """AC: Endpoint uses WEBAPI_URL env var for Atlas connection."""
        mock_rec = make_mock_recommender()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers.get = MagicMock(return_value="application/json")
        mock_response.json.return_value = {"id": 99, "name": "Test"}

        captured_url = []

        async def capture_post(url, **kwargs):
            captured_url.append(url)
            return mock_response

        monkeypatch.setenv("WEBAPI_URL", "http://custom-webapi:9090/WebAPI")

        with patch("src.agents.conceptset.api.get_recommender", return_value=mock_rec), \
             patch("httpx.AsyncClient") as mock_http_class:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(side_effect=capture_post)
            mock_http_class.return_value = mock_http

            response = client.post(
                "/api/conceptset/recommend-and-save",
                json={"query": "Metformin"}
            )

        assert len(captured_url) == 1
        assert "custom-webapi:9090" in captured_url[0]
