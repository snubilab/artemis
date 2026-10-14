"""The one text check: a fragment a model quoted occurs in the text it quoted it from.

Where meaning is needed, the model decides it and quotes the fragment of the text that
supports it; code checks only that the fragment is in the text (AGENTS.md § PROMPTS AND
TEXT RULES, rule 3). Every such check compares in the one form defined here, so a
fragment verifies in all of them or in none:

* Agent 1's segmentation (:mod:`src.agents.agent1.segmentation`) locates its fragments in
  the document with :func:`fold`, which also says where each compared character came from;
* the annotation fields (``base_span`` included) and their re-checks at build and export
  time, the planner's ``relation_span``, ``value_constraint_text`` and excepted-entity
  spans, and the delivery gate's re-checks (``scripts/verify_circe_delivery.py``) call
  :func:`span_in_line` through :mod:`src.services.criterion_annotation`;
* the planner's ``source_span`` (:mod:`src.agents.planner.decomposer`) calls it directly.

The comparison form undoes how the text was encoded, never what it says: runs of
whitespace and of private-use glyphs (a PDF symbol font's space or bullet, which a model
copying the text cannot see and does not reproduce) become one space; format characters
(soft hyphen, zero-width) and the backslash ClinicalTrials.gov's Markdown puts before a
comparison sign are dropped; letters are lower-cased. A fragment with a different word,
number or symbol is not in the text under this form.
"""

from __future__ import annotations

import unicodedata
from typing import Any

#: ClinicalTrials.gov's Markdown escape (``=\\>`` for ``=>``); dropped, like a format character.
_MARKDOWN_ESCAPE = "\\"


def is_space(char: str) -> bool:
    """Whitespace, or a private-use glyph: a PDF symbol font's space or bullet, which a
    model copying the text cannot see and does not reproduce.

    :param char: one character.
    :returns: True when the comparison form reads it as a space.
    """
    return char.isspace() or unicodedata.category(char) == "Co"


def _dropped(char: str) -> bool:
    """A format character (soft hyphen, zero-width) or the Markdown escape backslash."""
    return char == _MARKDOWN_ESCAPE or unicodedata.category(char) == "Cf"


def fold(text: str) -> tuple[str, list[int]]:
    """The comparison form of ``text`` and, for each of its characters, the offset it came
    from. Runs of :func:`is_space` characters become one space (none at either end),
    :func:`_dropped` characters are removed, letters are lower-cased.

    :param text: the text to fold.
    :returns: ``(form, index)`` with ``len(form) == len(index)``.
    """
    form: list[str] = []
    index: list[int] = []
    pending = False
    for position, char in enumerate(text):
        if _dropped(char):
            continue
        if is_space(char):
            pending = bool(form)
            continue
        if pending:
            form.append(" ")
            index.append(position)
            pending = False
        lower = char.lower()
        form.append(lower if len(lower) == 1 else char)
        index.append(position)
    return "".join(form), index


def comparison_form(text: str) -> str:
    """:func:`fold` without the offsets.

    :param text: the text to fold.
    :returns: its comparison form.
    """
    return fold(text)[0]


def span_in_line(span: Any, line: Any) -> bool:
    """Whether an LLM-quoted fragment occurs in the line it was quoted from.

    Tolerates re-wrapped whitespace, case and the PDF / Markdown encoding characters
    :func:`fold` undoes; never a missing or changed word.

    :param span: the fragment the model returned.
    :param line: the text it claims to quote, usually the row's ``protocolLine``.
    :returns: True when ``span`` is a non-empty substring of ``line`` in comparison form.
    """
    if not isinstance(span, str) or not isinstance(line, str):
        return False
    probe = comparison_form(span)
    return bool(probe) and probe in comparison_form(line)


def span_offsets(span: Any, line: Any) -> tuple[int, int] | None:
    """Where a quoted fragment sits in the line it was quoted from.

    The same check as :func:`span_in_line`, returning the place instead of a yes: the offsets,
    in ``line`` itself, of the first stretch whose comparison form is the fragment's. Two
    fragments quoted from one line are the same stretch of it exactly when their offsets are
    equal, however each was re-wrapped or re-cased, so offsets compare *where* two answers
    quoted without reading what either says.

    :param span: the fragment the model returned.
    :param line: the text it claims to quote, usually the row's ``protocolLine``.
    :returns: ``(start, end)``, with ``line[start:end]`` the stretch the fragment matched, or
        None when :func:`span_in_line` would say False.
    """
    if not span_in_line(span, line):
        return None
    probe = comparison_form(span)
    form, index = fold(line)
    start = form.index(probe)
    return index[start], index[start + len(probe) - 1] + 1
