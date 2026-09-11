"""The words in a piece of clinical text that could name something.

Extracted verbatim from ``src/agents/planner/decomposer._naming_words`` so that two
callers can share one implementation rather than two that drift:

* :func:`~src.agents.planner.decomposer._grounded_span` -- gate 2, deciding whether a
  span the model claims as its source really names the sub-term it is attached to.
* :func:`~src.utils.circe_lint.ungrounded_criteria` -- the same question asked one stage
  later, of a whole stored criterion against its own ``protocolLine``.

It lives here rather than in the decomposer because ``circe_lint`` is deliberately pure
-- no I/O, no model -- and the decomposer imports ``langchain`` and ``src.utils.llm`` at
module scope. Importing the helper from there would drag the model stack into every
lint.

Escapes are not stripped here, and do not need to be. ``deescape`` (the one home for
that decision, in ``src.agents.agent1.threshold_classifier``) matters for the *substring*
half of ``_grounded_span``, where a stray ``\\>`` breaks a comparison that must hold
character for character. Word splitting is escape-insensitive by construction: the split
pattern below treats a backslash as a separator like any other non-alphanumeric. Measured
over the 1,910 ``protocolLine`` / ``description`` / ``sourceText`` / ``conceptSetName`` /
``protocolSpan`` strings of the 2026-09-14 store, routing through ``deescape`` first
changes zero of them, and none of the 1,910 contains a backslash at all.
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
