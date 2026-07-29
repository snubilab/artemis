"""Reasoning-model output must be clean before it reaches a JSON parser.

Qwen3-class models emit <think>…</think> ahead of the answer. Every LLM call site
in this codebase parses JSON, four of them inside a `prompt | llm | parser` chain
where there is no seam to clean the text — so the stripping has to happen in the
model wrapper or one caller is always missed.
"""
from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.outputs import ChatGeneration, ChatResult

from src.utils.llm import ReasoningStrippedChatModel

ANSWER = '{"selected_ids": [42]}'
# The think block carries its own JSON so a naive "first brace wins" reader fails.
WITH_THINK = f'<think>Weighing options. {{"trap": 1}}</think>\n{ANSWER}'


class _Echo(BaseChatModel):
    """Records what it was sent and replies with a fixed body."""

    body: str = WITH_THINK
    seen: List[str] = []

    @property
    def _llm_type(self) -> str:
        return "echo"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        type(self).seen = [str(m.content) for m in messages]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.body))])


def _wrapped(body: str = WITH_THINK) -> ReasoningStrippedChatModel:
    return ReasoningStrippedChatModel(inner=_Echo(body=body))


def test_think_block_is_removed() -> None:
    assert _wrapped().invoke([HumanMessage(content="pick")]).content == ANSWER


def test_json_parser_chain_survives_a_think_block() -> None:
    """The failure this wrapper exists for: JsonOutputParser sees raw content."""
    chain = _wrapped() | JsonOutputParser()
    assert chain.invoke([HumanMessage(content="pick")]) == {"selected_ids": [42]}


def test_no_think_directive_is_appended_to_the_last_human_turn() -> None:
    model = _wrapped()
    model.invoke([SystemMessage(content="sys"), HumanMessage(content="pick")])
    assert _Echo.seen[-1].endswith("/no_think")
    assert _Echo.seen[0] == "sys", "the system turn must not be rewritten"


def test_no_think_is_not_duplicated() -> None:
    model = _wrapped()
    model.invoke([HumanMessage(content="pick\n/no_think")])
    assert _Echo.seen[-1].count("/no_think") == 1


def test_output_without_a_think_block_is_untouched() -> None:
    assert _wrapped(body=ANSWER).invoke([HumanMessage(content="pick")]).content == ANSWER
