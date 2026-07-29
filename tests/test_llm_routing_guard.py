"""What model, at what endpoint — asserted on the built object, not on a name.

Four separate leaks in one afternoon shared one shape: a model name that looks
right, building a client pointed somewhere else. `test_model_selection_is_uniform.py`
compares the names `resolve_model()` returns and would have caught none of them,
because a name says nothing about which host receives it:

  - `vllm/x` with VLLM_BASE_URL unset fell through to OpenRouter as the literal
    string "vllm/x", or was rewritten to gpt-4o-mini by the OpenAI branch
  - `AGENT2_CRITIC_MODEL_TIER=gpt-4o` — set by both benchmark drivers — routes
    the critic to OpenRouter while LLM_MODEL is local, and the old guard suite
    `delenv`'d that variable away, so it was green in exactly the configuration
    that fails

So these tests construct the object and read `base_url` off it. The autouse
netguard is the second half: any test in this file that reaches for the network
fails instead of billing, which is the property the old suite lacked.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from langchain_openai import ChatOpenAI

from src.agents.agent2.kg_expander import KGConcept
from src.settings import settings
from src.utils.exceptions import LLMConfigurationError
from src.utils.llm import _USAGE_CALLBACK, get_cost_tracker, get_llm, resolve_model

_SENTINEL_BASE_URL = "http://vllm-sentinel.invalid:8000/v1"
_LOCAL_MODEL = "vllm/sentinel/model-x"


@pytest.fixture(autouse=True)
def netguard(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test here may leave the process. A billed call is a failed test."""

    def blocked(self: Any, request: Any, **kwargs: Any) -> None:
        raise AssertionError(f"outbound HTTP attempted: {request.method} {request.url}")

    monkeypatch.setattr(httpx.Client, "send", blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", blocked)


@pytest.fixture
def local_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fully-local configuration, independent of whatever .env holds."""
    monkeypatch.setattr(settings, "LLM_MODEL", _LOCAL_MODEL)
    monkeypatch.setattr(settings, "VLLM_BASE_URL", _SENTINEL_BASE_URL)
    monkeypatch.setattr(settings, "VLLM_API_KEY", "EMPTY")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setattr(settings, "AZURE_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER", raising=False)


def _endpoint_of(llm: Any) -> str | None:
    """The base_url the object will actually POST to, through any wrapper."""
    return getattr(getattr(llm, "inner", llm), "openai_api_base", None)


def _call_site_llms() -> dict[str, Any]:
    """Every default a caller gets when it does not name a model itself."""
    from src.agents.agent1 import threshold_classifier as clf
    from src.agents.agent2 import critic as cri
    from src.agents.comparator import recommender as rec

    sites = {
        "bare": get_llm(resolve_model(None)),
        "comparator": get_llm(rec.DEFAULT_LLM_MODEL),
        "classifier": get_llm(clf.DEFAULT_MODEL),
    }
    for domain in ("Condition", "Drug", "Measurement", "Observation", "Procedure", None):
        sites[f"critic[{domain}]"] = get_llm(cri.select_critic_model(domain))
    return sites


# ── The class: one setting, one endpoint ───────────────────


def test_every_call_site_builds_a_client_pointed_at_the_local_server(
    local_pipeline: None,
) -> None:
    """Names are not enough — read the endpoint off the constructed object."""
    wrong = {
        site: _endpoint_of(llm)
        for site, llm in _call_site_llms().items()
        if _endpoint_of(llm) != _SENTINEL_BASE_URL
    }
    assert not wrong, f"these call sites do not talk to the configured server: {wrong}"


def test_local_call_sites_keep_the_reasoning_stripper(local_pipeline: None) -> None:
    """A bare ChatOpenAI here means the branch changed and <think> reaches the parser."""
    for site, llm in _call_site_llms().items():
        assert hasattr(llm, "inner"), f"{site} is not reasoning-stripped"


# ── The driver configuration N5 named ──────────────────────


def test_a_tier_override_is_honoured_but_says_so_out_loud(
    local_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both benchmark drivers set this variable; the suite used to delenv it.

    Remote routing is the documented opt-in, so the property under test is not
    that it does not happen — it is that it is visible when it does.
    """
    from src.agents.agent2 import critic as cri

    monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", "gpt-4o")
    with caplog.at_level(logging.WARNING, logger=cri.__name__):
        critic_llm = get_llm(cri.select_critic_model("Condition"))

    assert _endpoint_of(critic_llm) == settings.OPENROUTER_BASE_URL
    assert any(
        "will not run on the local server" in message for message in caplog.messages
    ), f"the critic left the local server with no warning; logged: {caplog.messages}"


# ── Tier sentinels ─────────────────────────────────────────


@pytest.mark.parametrize("tier", ["Follow", "FOLLOW", "  follow  ", "follow"])
def test_follow_is_recognised_whatever_the_case(
    monkeypatch: pytest.MonkeyPatch, tier: str
) -> None:
    from src.agents.agent2 import critic as cri

    monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", tier)
    assert cri.select_critic_model("Condition") is None


@pytest.mark.parametrize("tier", ["AUTO", "Auto", " auto "])
def test_auto_is_recognised_whatever_the_case(
    monkeypatch: pytest.MonkeyPatch, tier: str
) -> None:
    from src.agents.agent2 import critic as cri

    monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", tier)
    assert cri.select_critic_model("Condition") == "gpt-4o-mini"
    assert cri.select_critic_model("Observation") == "gpt-4o"


@pytest.mark.parametrize(
    "tier", ["none", "None", "null", "off", "false", "true", "0", "1", "no", "disabled"]
)
def test_a_boolean_ish_tier_is_rejected_not_treated_as_a_model(
    monkeypatch: pytest.MonkeyPatch, tier: str
) -> None:
    """These all used to become literal model names POSTed to OpenRouter."""
    from src.agents.agent2 import critic as cri

    monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", tier)
    with pytest.raises(LLMConfigurationError, match="AGENT2_CRITIC_MODEL_TIER"):
        cri.select_critic_model("Condition")


def test_a_typoed_model_is_still_representable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Literal model names stay literal, case intact — ids are case-sensitive.

    A typo like 'gpt-4o-mimi' therefore remains expressible, which is why the
    propagation test below is the load-bearing half of this pair.
    """
    from src.agents.agent2 import critic as cri

    monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", "Qwen/Qwen3-8B")
    assert cri.select_critic_model("Condition") == "Qwen/Qwen3-8B"


# ── get_llm never substitutes ──────────────────────────────


def test_a_vllm_model_without_a_base_url_raises_instead_of_falling_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "VLLM_BASE_URL", None)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-openrouter-key")
    with pytest.raises(LLMConfigurationError, match="VLLM_BASE_URL"):
        get_llm(_LOCAL_MODEL)


def test_the_openai_branch_does_not_rewrite_an_unknown_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`model if "gpt" in model else "gpt-4o-mini"` answered with the wrong model."""
    monkeypatch.setattr(settings, "VLLM_BASE_URL", None)
    monkeypatch.setattr(settings, "AZURE_API_KEY", None)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-openai-key")

    assert get_llm("Qwen/Qwen3-8B").model_name == "Qwen/Qwen3-8B"


# ── An unservable model must stop the run, not degrade it ──


def _status_error(status_code: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "http://provider.invalid/v1/chat/completions")
    response = httpx.Response(
        status_code, request=request, json={"error": {"message": "model does not exist"}}
    )
    return openai.APIStatusError("boom", response=response, body=None)


def _critic_with_chain(monkeypatch: pytest.MonkeyPatch, error: BaseException):
    from src.agents.agent2 import critic as cri

    critic = cri.ConceptCritic()

    class ExplodingChain:
        def invoke(self, _payload: dict) -> dict:
            raise error

    monkeypatch.setattr(critic, "_default_chain", ExplodingChain())
    return critic


_KG_CANDIDATE = KGConcept(
    concept_id=222, concept_name="Cerebral embolism",
    domain_id="Condition", vocabulary_id="SNOMED", relationship="2-hop",
)


@pytest.mark.parametrize("status_code", [401, 403, 404])
def test_an_unservable_critic_model_raises_instead_of_returning_seeds(
    local_pipeline: None, monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    """`vllm/snuh/hari-q3-8b` — the name in the docs — 404s on the live server.

    The blanket except turned that into seed concepts: KG expansion silently
    discarded, one ERROR line, and a complete benchmark row with a lower number.
    """
    critic = _critic_with_chain(monkeypatch, _status_error(status_code))
    with pytest.raises(LLMConfigurationError, match="not servable"):
        critic.evaluate("history of stroke", [111], [_KG_CANDIDATE], domain_hint="Condition")


def test_a_transient_critic_failure_still_degrades_to_seeds(
    local_pipeline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resilience is kept for the failures that are actually transient."""
    critic = _critic_with_chain(monkeypatch, TimeoutError("read timeout"))
    assert critic.evaluate(
        "history of stroke", [111], [_KG_CANDIDATE], domain_hint="Condition"
    ) == [111]


def test_the_workflow_frame_does_not_swallow_the_misconfiguration(
    local_pipeline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fixing critic.py alone is theatre — workflow.py blanket-excepts one frame up."""
    from src.agents.agent2 import workflow as wf

    class StubExpander:
        def expand(self, *_args: Any, **_kwargs: Any) -> list[KGConcept]:
            return [
                KGConcept(
                    concept_id=1000 + i, concept_name=f"c{i}",
                    domain_id="Condition", vocabulary_id="SNOMED", relationship="2-hop",
                )
                for i in range(12)  # > 10, or clinical_anchor mode skips the critic
            ]

    critic = _critic_with_chain(monkeypatch, _status_error(404))
    monkeypatch.setattr(wf, "get_kg_expander", lambda: StubExpander())
    monkeypatch.setattr(wf, "get_critic", lambda: critic)

    with pytest.raises(LLMConfigurationError):
        wf.Agent2Workflow()._kg_expand_and_critique([111], "history of stroke")


# ── Cost tracking records reality ──────────────────────────


@pytest.fixture
def tracker():
    tracker = get_cost_tracker()
    tracker.reset()
    yield tracker
    tracker.reset()


def test_an_unpriced_model_costs_nothing_but_still_counts(tracker) -> None:
    tracker.record("sentinel/model-x", 1_000_000, 1_000_000)
    summary = tracker.summary()
    assert summary["cost_usd"] == 0.0
    assert summary["llm_calls"] == 1
    assert summary["total_tokens"] == 2_000_000


def test_a_priced_model_still_costs(tracker) -> None:
    tracker.record("gpt-4o", 1_000_000, 1_000_000)
    assert tracker.summary()["cost_usd"] == pytest.approx(12.5)


def test_the_callback_records_the_model_the_provider_served(tracker) -> None:
    _USAGE_CALLBACK.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="x"))]],
            llm_output={
                "token_usage": {"prompt_tokens": 11, "completion_tokens": 7},
                "model_name": "gpt-4o",
            },
        )
    )
    summary = tracker.summary()
    assert summary == {
        "llm_calls": 1,
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "cost_usd": round(11 * 2.5e-6 + 7 * 1.0e-5, 6),
    }


def test_a_completion_through_a_built_llm_reaches_the_tracker(
    local_pipeline: None, tracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """llmCost was a structural zero: no ChatOpenAI path ever called record()."""

    def canned(self: Any, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="ok"))],
            llm_output={
                "token_usage": {"prompt_tokens": 3, "completion_tokens": 2},
                "model_name": "sentinel/model-x",
            },
        )

    monkeypatch.setattr(ChatOpenAI, "_generate", canned)
    get_llm(resolve_model(None)).invoke("anything")

    summary = tracker.summary()
    assert summary["llm_calls"] == 1
    assert summary["total_tokens"] == 5
