"""Every capped LLM call asks the server for its own reply budget, and a reply that hits it
is no answer.

Measured 2026-10-23: annotation calls carried no ``max_tokens``, so a degenerate reply ran
to the served ``max_model_len`` (65,536). One ARISTOTLE annotation request in the P11 run
was in flight for 3+ hours at ~4 tok/s; the server's ``finished_reason="length"`` count
was 40. The caps and the measurements behind them are in ``src/utils/llm.py``.

The HTTP exchange is stubbed (``httpx.Client.send``), so the request goes through the real
``get_llm`` -> ``ChatOpenAI`` path and the server's ``finish_reason`` reaches the caller
the way a vLLM reply does. No LLM, no network.
"""

import json

import httpx
import pytest

from src.settings import settings
from src.utils import llm as llm_mod

MODEL = "google/gemma-4-E4B-it"
LINE = "Currently planned coronary, carotid, or peripheral artery revascularization"


@pytest.fixture
def local_vllm(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "LLM_MODEL", f"vllm/{MODEL}")
    monkeypatch.setattr(settings, "VLLM_BASE_URL", "http://vllm-stub.invalid:8000/v1")
    monkeypatch.setattr(settings, "VLLM_API_KEY", "EMPTY")
    monkeypatch.setenv("ARTEMIS_TRUNCATION_DIR", str(tmp_path / "truncated"))


def _serve(monkeypatch, content, finish_reason, *, completion_tokens):
    """Answer every chat completion with ``content``; return the request bodies sent."""
    sent = []

    def send(self, request, **kwargs):
        sent.append(json.loads(request.content))
        return httpx.Response(200, request=request, json={
            "id": "stub", "object": "chat.completion", "created": 0, "model": MODEL,
            "choices": [{"index": 0, "finish_reason": finish_reason,
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 3000, "completion_tokens": completion_tokens,
                      "total_tokens": 3000 + completion_tokens},
        })

    monkeypatch.setattr(httpx.Client, "send", send)
    return sent


@pytest.fixture
def annotation(tmp_path, monkeypatch):
    from src.services import criterion_annotation

    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    criterion_annotation.reset_for_tests()
    yield criterion_annotation
    criterion_annotation.reset_for_tests()


def test_should_ask_the_server_for_the_annotation_cap_when_annotation_calls_the_model(
    monkeypatch, local_vllm, annotation
):
    sent = _serve(monkeypatch, '{"record_requirement": "required"}', "stop",
                  completion_tokens=12)
    llm = annotation._build_llm(f"vllm/{MODEL}")

    annotation._complete(llm, "prompt")

    assert [body.get("max_tokens") for body in sent] == [llm_mod.ANNOTATION_MAX_TOKENS]


def test_should_record_no_answer_and_cache_nothing_when_an_annotation_reply_hits_the_cap(
    monkeypatch, local_vllm, annotation
):
    # The degenerate shape: an opened object, then whitespace until the cap stops it.
    degenerate = '{"record_requirement": "forbidden", "conditional_span": ' + " " * 4000
    sent = _serve(monkeypatch, degenerate, "length",
                  completion_tokens=llm_mod.ANNOTATION_MAX_TOKENS)
    llm = annotation._build_llm(f"vllm/{MODEL}")
    row = {"id": "21", "protocolLine": LINE}

    first = annotation.annotate_row(row, [], "exclusion", model=f"vllm/{MODEL}", llm=llm)
    calls_after_first = len(sent)
    again = annotation.annotate_row(dict(row), [], "exclusion", model=f"vllm/{MODEL}", llm=llm)

    assert first == again == "error"
    assert "LLMTruncationError" in row[annotation.ANNOTATION_KEY]["error"], row
    assert len(sent) == 2 * calls_after_first, "a capped reply was replayed from the cache"
    assert all(body.get("max_tokens") == llm_mod.ANNOTATION_MAX_TOKENS for body in sent)


@pytest.mark.parametrize("build, cap_name", [
    ("src.agents.agent2.specimen_critic", "SPECIMEN_CRITIC_MAX_TOKENS"),
    ("src.agents.agent1.segmentation", "SEGMENTATION_MAX_TOKENS"),
])
def test_should_ask_the_server_for_its_cap_when_a_module_builds_its_model(
    monkeypatch, local_vllm, build, cap_name
):
    import importlib

    sent = _serve(monkeypatch, "{}", "stop", completion_tokens=2)
    model = importlib.import_module(build)._build_llm(f"vllm/{MODEL}")

    model.invoke("prompt")

    assert [body.get("max_tokens") for body in sent] == [getattr(llm_mod, cap_name)]


def test_should_ask_the_server_for_the_extraction_cap_when_agent1_calls_the_model(
    monkeypatch, local_vllm
):
    from src.agents.agent1.parser import LogicDecomposer

    sent = _serve(monkeypatch, "{}", "stop", completion_tokens=2)

    LogicDecomposer(model_name=f"vllm/{MODEL}").llm.invoke("prompt")

    assert [body.get("max_tokens") for body in sent] == [llm_mod.EXTRACTION_MAX_TOKENS]
