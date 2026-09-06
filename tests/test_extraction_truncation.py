"""A completion cut off at the token ceiling must not present as malformed JSON.

Turning the Agent 1 IR cache off for a cold six-study re-extraction exposed a path
that had only ever been replayed from cache. On the live path the vLLM server
(``google/gemma-4-E4B-it``, ``max_model_len`` 16384) stops generating once prompt +
completion reaches the ceiling and reports ``finish_reason="length"``. Nothing read
that field, so the truncated body went straight into ``json.loads`` and surfaced as
``Expecting value: line 754 column 16`` (PLATO, 46 criteria) or ``Unterminated
string starting at: line 523 column 24`` (CAROLINA, 114 criteria).

Both messages describe a model that cannot hold an output schema. What actually
happened is that it ran out of budget mid-answer, and the two need opposite fixes --
a prompt or schema change versus more room -- so they must not read alike.

``finish_reason`` rides on the ChatGeneration's ``generation_info``, exactly where
``langchain_openai`` puts it; ``langchain_core`` is what merges it into
``response_metadata``. Going through ``invoke()`` therefore exercises the real
mechanism rather than a hand-placed field.
"""
from __future__ import annotations

from typing import Any, List, Optional
from unittest.mock import Mock

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.agents.agent1.nct_fetcher import TrialData
from src.agents.agent1.parser import LogicDecomposer
from src.utils.exceptions import LLMTruncationError
from src.utils.llm import finish_reason, raise_if_truncated, token_usage

# A prefix of a real answer, ending inside a string -- the shape CAROLINA produced.
TRUNCATED_BODY = '{"target": {"inclusion_rules": [{"entity_text": "Type 2 diabetes'
WHOLE_BODY = '{"target": {"inclusion_rules": []}}'

# PLATO's measured split: a 9,450-token prompt left 6,934 tokens of headroom in a
# 16,384-token window, and the completion stopped at exactly that number.
PROMPT_TOKENS = 9450
COMPLETION_TOKENS = 6934


class _Server(BaseChatModel):
    """Answers with a fixed body, finish_reason, and token usage."""

    body: str = TRUNCATED_BODY
    reason: str = "length"
    prompt_tokens: int = PROMPT_TOKENS
    completion_tokens: int = COMPLETION_TOKENS

    @property
    def _llm_type(self) -> str:
        return "stub-vllm"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content=self.body),
                    generation_info={"finish_reason": self.reason},
                )
            ],
            llm_output={
                "token_usage": {
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                    "total_tokens": self.prompt_tokens + self.completion_tokens,
                },
                "model_name": "google/gemma-4-E4B-it",
            },
        )


def _decomposer(monkeypatch: pytest.MonkeyPatch, **server: Any) -> LogicDecomposer:
    monkeypatch.setattr("src.agents.agent1.parser.get_llm", lambda **_: _Server(**server))
    return LogicDecomposer()


def test_should_raise_a_truncation_error_when_finish_reason_is_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(LLMTruncationError):
        _decomposer(monkeypatch).parse("apixaban vs warfarin")


def test_should_not_report_a_truncated_completion_as_a_json_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect: a budget exhaustion arriving under a syntax error's name."""
    with pytest.raises(LLMTruncationError) as excinfo:
        _decomposer(monkeypatch).parse("apixaban vs warfarin")
    assert "Failed to parse LLM response as JSON" not in str(excinfo.value)


def test_should_name_the_token_budget_when_the_completion_is_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The arithmetic is the actionable part: it says how much room was missing."""
    with pytest.raises(LLMTruncationError) as excinfo:
        _decomposer(monkeypatch).parse("apixaban vs warfarin")
    message = str(excinfo.value)
    assert str(PROMPT_TOKENS) in message
    assert str(COMPLETION_TOKENS) in message
    assert excinfo.value.prompt_tokens == PROMPT_TOKENS
    assert excinfo.value.completion_tokens == COMPLETION_TOKENS


def test_should_still_raise_a_parse_error_when_a_finished_model_emits_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed generation is a different failure and keeps its own message."""
    decomposer = _decomposer(monkeypatch, body="not json at all", reason="stop")
    with pytest.raises(ValueError) as excinfo:
        decomposer.parse("apixaban vs warfarin")
    assert "Failed to parse LLM response as JSON" in str(excinfo.value)


def test_should_not_raise_when_the_model_finished_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _decomposer(monkeypatch, body=WHOLE_BODY, reason="stop").parse(
        "apixaban vs warfarin"
    )
    assert request.target.inclusion_rules == []


def test_should_raise_a_truncation_error_on_the_nct_extraction_path_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parse_nct is the path that actually failed; parse() alone would not cover it.

    The raise lands before the IR cache and meta files are written, so this test
    leaves nothing behind in data/cache/agent1_ir.
    """
    monkeypatch.setattr(
        "src.agents.agent1.parser.fetch_or_load_trial_data",
        lambda nct_id: TrialData(
            nct_id=nct_id,
            title="A trial",
            conditions=["Type 2 diabetes"],
            interventions=["linagliptin", "glimepiride"],
            inclusion_criteria=["Adults aged 40 to 85 years"],
            exclusion_criteria=["ALT > 3X ULN"],
            primary_outcomes=["MACE"],
        ),
    )
    decomposer = _decomposer(monkeypatch)
    with pytest.raises(LLMTruncationError):
        decomposer.parse_nct("NCT09999999", enrich_from_pubmed=False, verify_thresholds=False)


def test_should_treat_a_missing_finish_reason_as_not_truncated() -> None:
    """A provider that reports nothing must not be read as a failure."""
    raise_if_truncated(AIMessage(content="{}"), what="unit test")


def test_should_treat_unreadable_response_metadata_as_no_information() -> None:
    """A Mock's auto-created attributes are truthy but not mappings.

    Several agent1 tests drive parse() with `unittest.mock.Mock`, so the metadata
    reader sits in front of objects that answer every attribute with another Mock.
    An unguarded read raised `TypeError: 'Mock' object is not iterable` and broke
    nine passing tests -- an observability helper must never become a failure mode.
    """
    assert finish_reason(Mock()) is None
    assert token_usage(Mock()) == {}
    raise_if_truncated(Mock(), what="unit test")
