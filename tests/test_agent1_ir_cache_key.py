"""The IR cache key must cover the system prompt, not only the human message.

The key hashed ``f"{model_key}:{prompt}"`` where ``prompt`` is the human message
built from NCT_DECOMPOSITION_PROMPT. NCT_SYSTEM_PROMPT -- which carries Pattern E,
the rule that decides whether an "A or B or C" criterion becomes one ANY group or
several flat rules -- was not in the key.

Measured 2026-07-31: a Pattern E change intended to split lab OR-lists per analyte
produced ``Cache HIT`` and replayed the previous IR. The run reported the same
``ratio-emitting=2`` as before and looked like the fix had failed, when the fix had
never executed. Nothing in the output distinguished the two.
"""
from __future__ import annotations

from src.agents.agent1.parser import LogicDecomposer


def test_system_prompt_changes_the_key() -> None:
    """The guarantee the old key did not provide."""
    a = LogicDecomposer._ir_cache_key("m", "system A", "human")
    b = LogicDecomposer._ir_cache_key("m", "system B", "human")

    assert a != b


def test_human_prompt_still_changes_the_key() -> None:
    """The original guarantee has to survive the new one."""
    a = LogicDecomposer._ir_cache_key("m", "system", "human A")
    b = LogicDecomposer._ir_cache_key("m", "system", "human B")

    assert a != b


def test_model_still_changes_the_key() -> None:
    a = LogicDecomposer._ir_cache_key("model-a", "system", "human")
    b = LogicDecomposer._ir_cache_key("model-b", "system", "human")

    assert a != b


def test_the_boundary_between_fields_is_not_ambiguous() -> None:
    """Concatenating without a separator lets one field borrow from the next.

    "ab" + "c" and "a" + "bc" must not hash alike, or a system prompt ending in a
    character the human message begins with can collide.
    """
    a = LogicDecomposer._ir_cache_key("m", "ab", "c")
    b = LogicDecomposer._ir_cache_key("m", "a", "bc")

    assert a != b


def test_identical_inputs_still_hit() -> None:
    """A key that never repeats is a cache that never works."""
    assert LogicDecomposer._ir_cache_key("m", "s", "h") == LogicDecomposer._ir_cache_key("m", "s", "h")


def test_key_is_filename_safe() -> None:
    """It goes straight into a path."""
    key = LogicDecomposer._ir_cache_key("vllm_google_gemma-4-E4B-it", "s", "h")

    assert key.isalnum()
    assert len(key) == 16
