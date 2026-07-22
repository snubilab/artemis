"""Tests for supplement PDF upload endpoint."""
import io
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestUploadSupplementPdf:
    def _get_client(self):
        from src.api.tte import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_upload_pdf_saves_to_papers_dir(self, tmp_path):
        client = self._get_client()
        pdf_content = b"%PDF-1.4 fake supplement"
        with patch("src.api.tte.PAPERS_DIR", tmp_path):
            response = client.post(
                "/tte/papers/NCT01179048/upload",
                files={"file": ("s1.pdf", io.BytesIO(pdf_content), "application/pdf")},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "supplement_s1.pdf"
        assert data["nctId"] == "NCT01179048"
        saved = tmp_path / "NCT01179048" / "supplement_s1.pdf"
        assert saved.exists()
        assert saved.read_bytes() == pdf_content

    def test_upload_rejects_non_pdf(self, tmp_path):
        client = self._get_client()
        with patch("src.api.tte.PAPERS_DIR", tmp_path):
            response = client.post(
                "/tte/papers/NCT01179048/upload",
                files={"file": ("data.csv", io.BytesIO(b"a,b,c"), "text/csv")},
            )
        assert response.status_code == 400

    def test_upload_normalizes_nct_id(self, tmp_path):
        client = self._get_client()
        with patch("src.api.tte.PAPERS_DIR", tmp_path):
            response = client.post(
                "/tte/papers/nct01179048/upload",
                files={"file": ("paper.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
            )
        assert response.status_code == 200
        assert (tmp_path / "NCT01179048" / "supplement_paper.pdf").exists()

    def test_list_papers_returns_uploaded_files(self, tmp_path):
        client = self._get_client()
        nct_dir = tmp_path / "NCT01179048"
        nct_dir.mkdir()
        (nct_dir / "supplement_s1.pdf").write_bytes(b"%PDF")
        (nct_dir / "main_paper.pdf").write_bytes(b"%PDF")
        with patch("src.api.tte.PAPERS_DIR", tmp_path):
            response = client.get("/tte/papers/NCT01179048")
        assert response.status_code == 200
        data = response.json()
        assert len(data["files"]) == 2

    def test_list_papers_empty_for_unknown_nct(self, tmp_path):
        client = self._get_client()
        with patch("src.api.tte.PAPERS_DIR", tmp_path):
            response = client.get("/tte/papers/NCT99999999")
        assert response.status_code == 200
        assert response.json()["files"] == []
