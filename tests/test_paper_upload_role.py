"""Tests for paper upload role parameter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def _papers_dir(tmp_path: Path):
    """Patch PAPERS_DIR to use a temporary directory."""
    with patch("src.api.tte.PAPERS_DIR", tmp_path):
        yield tmp_path


@pytest.fixture()
def client(_papers_dir: Path):
    """Create a FastAPI test client with patched PAPERS_DIR."""
    from src.api.tte import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _make_pdf_bytes() -> bytes:
    return b"%PDF-1.4 fake content"


class TestUploadWithRole:
    def test_upload_with_role_main_prefixes_filename(
        self, client: TestClient, _papers_dir: Path
    ) -> None:
        resp = client.post(
            "/tte/papers/NCT00001234/upload?role=main",
            files={"file": ("study.pdf", _make_pdf_bytes(), "application/pdf")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "main_study.pdf"
        assert data["role"] == "main"
        assert data["nctId"] == "NCT00001234"

        saved = _papers_dir / "NCT00001234" / "main_study.pdf"
        assert saved.exists()

    def test_upload_with_role_supplement_prefixes_filename(
        self, client: TestClient, _papers_dir: Path
    ) -> None:
        resp = client.post(
            "/tte/papers/NCT00001234/upload?role=supplement",
            files={"file": ("appendix.pdf", _make_pdf_bytes(), "application/pdf")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "supplement_appendix.pdf"
        assert data["role"] == "supplement"

    def test_default_role_is_supplement(
        self, client: TestClient, _papers_dir: Path
    ) -> None:
        resp = client.post(
            "/tte/papers/NCT00001234/upload",
            files={"file": ("paper.pdf", _make_pdf_bytes(), "application/pdf")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "supplement"
        assert data["name"] == "supplement_paper.pdf"

    def test_invalid_role_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/tte/papers/NCT00001234/upload?role=unknown",
            files={"file": ("paper.pdf", _make_pdf_bytes(), "application/pdf")},
        )
        assert resp.status_code == 400
        assert "Invalid role" in resp.json()["detail"]

    def test_reupload_same_role_overwrites_previous(
        self, client: TestClient, _papers_dir: Path
    ) -> None:
        # First upload
        client.post(
            "/tte/papers/NCT00005678/upload?role=main",
            files={"file": ("first.pdf", _make_pdf_bytes(), "application/pdf")},
        )
        first_path = _papers_dir / "NCT00005678" / "main_first.pdf"
        assert first_path.exists()

        # Second upload with same role
        resp = client.post(
            "/tte/papers/NCT00005678/upload?role=main",
            files={"file": ("second.pdf", b"%PDF-1.4 new content", "application/pdf")},
        )
        assert resp.status_code == 200

        # Old file removed, new file exists
        assert not first_path.exists()
        new_path = _papers_dir / "NCT00005678" / "main_second.pdf"
        assert new_path.exists()
        assert new_path.read_bytes() == b"%PDF-1.4 new content"

    def test_response_includes_role_field(
        self, client: TestClient, _papers_dir: Path
    ) -> None:
        resp = client.post(
            "/tte/papers/NCT00001234/upload?role=main",
            files={"file": ("doc.pdf", _make_pdf_bytes(), "application/pdf")},
        )
        data = resp.json()
        assert "role" in data
        assert data["role"] == "main"

    def test_non_pdf_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/tte/papers/NCT00001234/upload?role=main",
            files={"file": ("doc.txt", b"not a pdf", "text/plain")},
        )
        assert resp.status_code == 400
        assert "PDF" in resp.json()["detail"]

    def test_different_roles_coexist(
        self, client: TestClient, _papers_dir: Path
    ) -> None:
        client.post(
            "/tte/papers/NCT00009999/upload?role=main",
            files={"file": ("main.pdf", _make_pdf_bytes(), "application/pdf")},
        )
        client.post(
            "/tte/papers/NCT00009999/upload?role=supplement",
            files={"file": ("supp.pdf", _make_pdf_bytes(), "application/pdf")},
        )

        nct_dir = _papers_dir / "NCT00009999"
        pdfs = sorted(p.name for p in nct_dir.glob("*.pdf"))
        assert pdfs == ["main_main.pdf", "supplement_supp.pdf"]
