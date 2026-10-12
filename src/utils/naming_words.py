"""The words in a piece of clinical text that could name something (inventory A9).

What is left of the A9 rule. Its two pipeline callers are gone: the planner's gate 2 in
:func:`~src.agents.planner.decomposer._grounded_span` (RFC-016 §5) and delivery-gate check
(p), ``circe_lint.ungrounded_criteria``. Both decided whether a criterion was "named" by
its protocol line from shared words read through an English function-word list. Check (p)
was deleted rather than rewritten as a substring test: the only LLM-quoted fragment a store
row keeps for that question is ``protocolSpan``, which the planner's gate 1 already refuses
unless it is a substring of ``protocolLine``.

The only remaining users are two off-path A/B harnesses, ``scripts/example_value_ab.py``
and ``scripts/planner_example_ab.py``, which record :func:`_line_names_the_criterion` as
a ``lint_grounded`` column. Nothing on the extraction or delivery path imports this
module, which ``tests/test_no_text_rules.py`` keeps listed as a rule module until the
harnesses stop using it.
"""

from __future__ import annotations

import re

# Words that carry no naming power. A span overlapping a sub-term only on "or" or "of"
# has not named it. Single characters go too -- the "e" and "g" of "e.g.".
FUNCTION_WORDS = frozenset({
    "or", "of", "and", "the", "a", "an", "in", "with", "to", "for", "by", "on", "at",
    "as", "is", "are", "be", "not", "no", "any", "other", "due", "from",
})

_SPLIT = re.compile(r"[^0-9a-z]+")


def naming_words(text: str | None) -> set[str]:
    """The words in ``text`` that could name something."""
    folded = " ".join((text or "").split()).lower()
    return {w for w in _SPLIT.split(folded) if len(w) > 1 and w not in FUNCTION_WORDS}


#: A naming word shorter than this is not compared as a substring. Without the floor,
#: "ap" (alkaline phosphatase) matches "therapy" and every criterion looks grounded.
_SUBSTRING_FLOOR = 4


def _line_names_the_criterion(claimed: set[str], line: set[str]) -> bool:
    """Does ``line`` name any of the words the criterion claims?

    Whole-word overlap first, then substring in either direction above
    :data:`_SUBSTRING_FLOOR`. Moved here unchanged from ``circe_lint`` when check (p)
    was deleted, so the two A/B harnesses that record it keep measuring the same thing.

    :param claimed: naming words of what the criterion claims.
    :param line: naming words of its protocol line.
    :returns: True when the line shares a word with the claim, or a word of four or more
        characters of one contains a word of four or more characters of the other.
    """
    if claimed & line:
        return True
    for word in claimed:
        if len(word) < _SUBSTRING_FLOOR:
            continue
        for other in line:
            if len(other) < _SUBSTRING_FLOOR:
                continue
            if word in other or other in word:
                return True
    return False
