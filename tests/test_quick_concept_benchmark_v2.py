"""Unit tests for quick_concept_benchmark_v2 mapper wiring."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ARTEMIS_DIR / "scripts" / "quick_concept_benchmark_v2.py"


def _load_module():
    saved_env = os.environ.copy()
    saved_cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location(
        "quick_concept_benchmark_v2_test",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        os.chdir(saved_cwd)


MODULE = _load_module()


def test_parse_mapper_names_accepts_llm_rag():
    mapper_names = MODULE.parse_mapper_names("rag,llm_rag")

    assert mapper_names == ["RAG", "LLM RAG"]


def test_parse_mapper_names_accepts_gpt54_rag():
    mapper_names = MODULE.parse_mapper_names("gpt54_rag")

    assert mapper_names == ["GPT54 RAG"]


def test_run_llm_rag_pass_uses_rag_candidates_then_llm_selection():
    sample = [
        {
            "id": "row-1",
            "study": "DemoStudy",
            "cohort": "demo.json",
            "criterion_name": "No heart failure",
            "concept_set_name": "heart failure",
            "domain": "Condition",
            "gold_raw_ids": [11, 22],
        }
    ]
    rows: list[dict] = []

    fake_candidates = [
        SimpleNamespace(
            concept_id=101,
            concept_name="Heart failure",
            concept_class_id="Clinical Finding",
            vocabulary_id="SNOMED",
        ),
        SimpleNamespace(
            concept_id=202,
            concept_name="Congestive heart failure",
            concept_class_id="Clinical Finding",
            vocabulary_id="SNOMED",
        ),
        SimpleNamespace(
            concept_id=303,
            concept_name="Cardiac failure",
            concept_class_id="Clinical Finding",
            vocabulary_id="SNOMED",
        ),
    ]

    mock_rag = MagicMock()
    mock_rag.search.return_value = fake_candidates
    mock_reranker = MagicMock()
    mock_reranker.rerank_topn.return_value = [fake_candidates[1], fake_candidates[2]]

    fake_rag_module = SimpleNamespace(get_rag_search=lambda: mock_rag)
    fake_reranker_module = SimpleNamespace(ConceptReranker=lambda: mock_reranker)

    with patch.dict(
        sys.modules,
        {
            "src.agents.conceptset.rag_search": fake_rag_module,
            "src.agents.agent2.reranker": fake_reranker_module,
        },
    ):
        result_rows = MODULE.run_llm_rag_pass(sample, timeout_s=5.0, rows=rows)

    assert len(result_rows) == 1
    assert result_rows[0]["pred_raw_ids"] == [202, 303]
    assert result_rows[0]["error"] is None
    mock_rag.search.assert_called_once_with("heart failure", n_results=20, domain_filter="Condition")
    mock_reranker.rerank_topn.assert_called_once_with("heart failure", fake_candidates, top_n=3)


def test_run_llm_rag_pass_uses_explicit_model_override():
    sample = [
        {
            "id": "row-1",
            "study": "DemoStudy",
            "cohort": "demo.json",
            "criterion_name": "No heart failure",
            "concept_set_name": "heart failure",
            "domain": "Condition",
            "gold_raw_ids": [11, 22],
        }
    ]
    rows: list[dict] = []

    fake_candidates = [
        SimpleNamespace(
            concept_id=101,
            concept_name="Heart failure",
            concept_class_id="Clinical Finding",
            vocabulary_id="SNOMED",
        ),
        SimpleNamespace(
            concept_id=202,
            concept_name="Congestive heart failure",
            concept_class_id="Clinical Finding",
            vocabulary_id="SNOMED",
        ),
    ]

    mock_rag = MagicMock()
    mock_rag.search.return_value = fake_candidates

    with patch.dict(
        sys.modules,
        {"src.agents.conceptset.rag_search": SimpleNamespace(get_rag_search=lambda: mock_rag)},
    ), patch.object(
        MODULE,
        "_rerank_candidates_with_llm",
        return_value=[202],
    ) as mock_rerank:
        result_rows = MODULE.run_llm_rag_pass(
            sample,
            timeout_s=5.0,
            rows=rows,
            llm_model_name="gpt-5.4",
        )

    assert len(result_rows) == 1
    assert result_rows[0]["pred_raw_ids"] == [202]
    mock_rag.search.assert_called_once_with("heart failure", n_results=20, domain_filter="Condition")
    mock_rerank.assert_called_once_with("heart failure", fake_candidates, 2, "gpt-5.4")
