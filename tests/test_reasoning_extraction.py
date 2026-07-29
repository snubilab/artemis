"""Reasoning preambles arrive in more than one shape, and only one has a tag.

Measured on the live vLLM server:

    Qwen3-8B (hari)   <think>…</think> {"a":1}
    Qwen3.5-4B        Thinking Process:\\n\\n1.  **Analyze the Request:** … {"a":1}

The second has no tag, so a tag-only strip returns 1232 characters where the
caller expected 7. If that reaches a benchmark it reads as "this model cannot
hold an output schema", which is a claim about the model rather than about our
preprocessing — the distinction this suite exists to protect.
"""
from __future__ import annotations

import pytest

from src.utils.llm import extract_answer

ANSWER = '{"a":1}'

# Verbatim shape of a Qwen3.5-4B response, abridged. The reasoning quotes the
# prompt, so JSON runs appear *before* the answer — this is what makes
# "first brace wins" the wrong rule.
QWEN35 = (
    'Thinking Process:\n\n'
    '1.  **Analyze the Request:**\n'
    '    *   Input: "Return ONLY: {"a":1}\\n/no_think"\n'
    '    *   Constraint: "Return ONLY".\n'
    '2.  **Draft:** the object is {"a":1}\n\n'
    f'{ANSWER}'
)


def test_think_tag_is_removed() -> None:
    cleaned, strategy = extract_answer(f'<think>weighing it</think>\n{ANSWER}')
    assert cleaned == ANSWER
    assert strategy == "think_tag"


def test_untagged_preamble_yields_the_last_json_not_the_first() -> None:
    """The reasoning echoes the prompt, so earlier runs are the model's own quotes."""
    cleaned, strategy = extract_answer(QWEN35)
    assert cleaned == ANSWER
    assert strategy == "last_json"


def test_free_text_is_returned_untouched() -> None:
    """Not every caller wants JSON; stripping prose would corrupt those."""
    prose = "The patient is ineligible because ALT exceeds three times the upper limit."
    cleaned, strategy = extract_answer(prose)
    assert cleaned == prose
    assert strategy == "none"


def test_clean_json_without_a_preamble_is_untouched() -> None:
    cleaned, strategy = extract_answer(ANSWER)
    assert cleaned == ANSWER
    assert strategy == "none"


def test_preamble_without_any_json_is_left_alone() -> None:
    """Better to hand the caller the raw text than to invent an answer from it."""
    text = "Thinking Process:\n\nI am not sure what is being asked."
    cleaned, strategy = extract_answer(text)
    assert cleaned == text
    assert strategy == "none"


@pytest.mark.parametrize(
    "marker",
    ["Thinking Process:", "Reasoning:", "Let me think:", "Thought process:", "Analysis:"],
)
def test_known_preamble_markers_are_recognised(marker: str) -> None:
    cleaned, strategy = extract_answer(f"{marker}\nsome words\n{ANSWER}")
    assert cleaned == ANSWER
    assert strategy == "last_json"


def test_a_json_array_answer_is_extracted_too() -> None:
    cleaned, strategy = extract_answer('Thinking Process:\nweighing\n[1, 2, 3]')
    assert cleaned == "[1, 2, 3]"
    assert strategy == "last_json"


def test_the_tag_path_wins_when_both_shapes_are_present() -> None:
    """A tagged block is unambiguous; prefer it over prose heuristics."""
    cleaned, strategy = extract_answer(f'<think>Thinking Process: {{"b":2}}</think>{ANSWER}')
    assert cleaned == ANSWER
    assert strategy == "think_tag"
