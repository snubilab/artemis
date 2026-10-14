"""The critic's reply budget, and how each reply ended, measured at the server boundary.

About one critic call in ten ran into the 4096-token ceiling: a reply that judges 45-54
candidates at ~100 tokens each does not fit. The strict parser then rejected the cut body,
the criterion kept its seeds alone, and nothing recorded why — the server's
``finish_reason`` and token counts were on the response and no one read them.

These tests stub the HTTP exchange (``httpx.Client.send``), so the request goes through the
real ``get_llm`` → ``ChatOpenAI`` → ``ReasoningStrippedChatModel`` → critic path and the
response metadata reaches the critic the way a vLLM reply does. No LLM, no network.
"""

import json
import logging

import httpx
import pytest

from src.settings import settings
from tests.test_critic_failure_is_recorded import ANCHORS, SEED, _kg, _process, _selection

MODEL = "google/gemma-4-E4B-it"
COMPLETION_MARKER = "[Critic] Completion "


@pytest.fixture
def local_vllm(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", f"vllm/{MODEL}")
    monkeypatch.setattr(settings, "VLLM_BASE_URL", "http://vllm-stub.invalid:8000/v1")
    monkeypatch.setattr(settings, "VLLM_API_KEY", "EMPTY")
    monkeypatch.setenv("AGENT2_CRITIC_SELF_REFLECT", "true")
    monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER", raising=False)


def _serve(monkeypatch, content, finish_reason, *, completion_tokens, prompt_tokens=3000,
           status=200):
    """Answer every chat completion with ``content``; return the request bodies sent."""
    sent = []

    def send(self, request, **kwargs):
        sent.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "rejected"}}, request=request)
        return httpx.Response(200, request=request, json={
            "id": "stub", "object": "chat.completion", "created": 0, "model": MODEL,
            "choices": [{"index": 0, "finish_reason": finish_reason,
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens},
        })

    monkeypatch.setattr(httpx.Client, "send", send)
    return sent


def _critic(monkeypatch):
    from src.agents.agent2 import critic as critic_mod

    monkeypatch.setattr(critic_mod, "_concept_rows", lambda ids: {})
    return critic_mod.ConceptCritic()


def _completion_lines(caplog):
    return [json.loads(r.getMessage()[len(COMPLETION_MARKER):])
            for r in caplog.records if r.getMessage().startswith(COMPLETION_MARKER)]


CUT = _selection([SEED] + ANCHORS)[:-60]


# ── the budget ─────────────────────────────────────────────


@pytest.mark.parametrize("tier", ["follow", f"vllm/{MODEL}"])
def test_should_ask_the_server_for_8192_reply_tokens_when_the_critic_calls_the_model(
    monkeypatch, local_vllm, tier
):
    monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", tier)
    sent = _serve(monkeypatch, _selection([SEED, 20]), "stop", completion_tokens=200)
    critic = _critic(monkeypatch)

    critic.evaluate_with_outcome("q", [SEED], _kg(ANCHORS), domain_hint="Condition")

    assert [body["max_tokens"] for body in sent] == [8192]


# ── a reply cut at the budget ──────────────────────────────


def test_should_record_a_critic_failure_naming_finish_reason_length_when_the_reply_is_cut(
    monkeypatch, caplog, local_vllm
):
    _serve(monkeypatch, CUT, "length", completion_tokens=8192)
    critic = _critic(monkeypatch)
    caplog.set_level(logging.INFO)

    result = _process(monkeypatch, critic)

    assert result.concept_ids == [SEED], "a cut critic answer was used"
    assert "Invalid json output" in result.critic_failure, result.critic_failure
    assert "finish_reason=length" in result.critic_failure, result.critic_failure
    assert "completion_tokens=8192" in result.critic_failure, result.critic_failure
    assert result.mapping_failures() == [
        {"stage": "critic", "reason": result.critic_failure, "seedsOnly": True}
    ]
    [line] = _completion_lines(caplog)
    assert (line["finish_reason"], line["completion_tokens"], line["reply"]) == (
        "length", 8192, "unparseable"
    )


# ── every call says how it ended ───────────────────────────


def test_should_log_and_return_finish_reason_and_token_counts_when_the_reply_completes(
    monkeypatch, caplog, local_vllm
):
    _serve(monkeypatch, _selection([SEED, 20, 21]), "stop",
           completion_tokens=1234, prompt_tokens=3456)
    critic = _critic(monkeypatch)
    caplog.set_level(logging.INFO)

    outcome = critic.evaluate_with_outcome("q", [SEED], _kg(ANCHORS), domain_hint="Condition")

    assert outcome.failure is None
    assert sorted(outcome.concept_ids) == [SEED, 20, 21]
    assert (outcome.completion.finish_reason, outcome.completion.completion_tokens,
            outcome.completion.prompt_tokens) == ("stop", 1234, 3456)
    [line] = _completion_lines(caplog)
    assert line == {
        "query": "q", "domain": "Condition", "model": f"vllm/{MODEL}",
        "candidates": 1 + len(ANCHORS), "max_tokens": 8192, "finish_reason": "stop",
        "completion_tokens": 1234, "prompt_tokens": 3456, "reply": "parsed",
    }


def test_should_log_a_completion_line_with_no_reply_when_the_call_itself_fails(
    monkeypatch, caplog, local_vllm
):
    _serve(monkeypatch, "", None, completion_tokens=0, status=400)
    critic = _critic(monkeypatch)
    caplog.set_level(logging.INFO)

    outcome = critic.evaluate_with_outcome("q", [SEED], _kg(ANCHORS), domain_hint="Condition")

    assert outcome.failure and "BadRequestError" in outcome.failure, outcome.failure
    [line] = _completion_lines(caplog)
    assert (line["reply"], line["finish_reason"], line["completion_tokens"]) == ("none", None, None)


def test_should_log_no_completion_line_when_the_answer_comes_from_the_critic_cache(
    monkeypatch, caplog, local_vllm
):
    sent = _serve(monkeypatch, _selection([SEED, 20]), "stop", completion_tokens=200)
    critic = _critic(monkeypatch)
    caplog.set_level(logging.INFO)

    critic.evaluate_with_outcome("q", [SEED], _kg(ANCHORS), domain_hint="Condition")
    critic.evaluate_with_outcome("q", [SEED], _kg(ANCHORS), domain_hint="Condition")

    assert len(sent) == 1
    assert len(_completion_lines(caplog)) == 1
