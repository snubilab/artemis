"""The one place a criterion's mapper seed is chosen.

A criterion asserts its temporal scope TWICE: once in ``window``, as days relative to
index, and once in the prose of ``description`` -- "... within 3 years", "(7 days)",
"for 8 weeks prior to randomization". Only the first assertion is read by Circe. The
second is inert everywhere except one place, where it does real damage: the text handed
to the concept mapper. :func:`src.agents.conceptset.nlu_router.detect_temporal_negation`
scans that text for ``within`` / ``prior`` / ``days`` / ``months`` / ``years`` and, on a
hit, refuses to route the seed at all -- the criterion is then recorded as
``intent-unparsed`` and never becomes a rule.

Measured on the 2026-09-09 six-study delivery: four CARMELINA criteria were lost that
way, every one of them with a CORRECT window already holding the number the prose
repeated. The extraction was right; the seed was the copy that should not have carried
it.

Two properties keep this narrow, and both are load-bearing:

* **Only what the window already holds.** A duration is dropped only when the criterion
  actually carries a ``window`` to hold it. Nothing else is touched -- "Age >= 18 years"
  and "Life expectancy < 5 years" are numbers about the patient, not lookbacks, and a
  stripper that ate them would silently change what the criterion asks for.
* **Nothing is deleted.** The criterion's own ``description`` and ``sourceText`` keep the
  full text; the rule name downstream is still built from them. This function narrows
  the SEED only.

Both call sites in ``tte_service`` -- the ChromaDB batch pre-fetch and
``_build_seeded_eligibility_rule`` -- must read the seed from here, or the candidates
pre-fetched under one string are handed to a mapper that asked for another.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: Duration units a protocol writes a lookback in. Deliberately excludes bare "time"
#: words with no numeric partner -- every pattern below requires a digit, because the
#: digit is what makes the phrase a duration rather than a relation ("prior stroke" is
#: not a duration and must survive).
_UNIT = r"(?:hour|hr|day|week|wk|month|mo|year|yr)s?"

#: What a protocol measures a lookback back FROM. Only these anchor a "prior to X"
#: phrase; "prior stroke" and "previous MI" carry no anchor and are relations, not
#: durations.
_MILESTONE = (
    r"(?:randomi[sz]ation|randomi[sz]ed|screening|enrol?lment|baseline|"
    r"index(?:\s+(?:date|event))?|informed\s+consent|consent|study\s+entry|"
    r"study\s+start|study\s+drug|first\s+dose|treatment\s+start|visit(?:\s+\S+)?)"
)

_COMPARATOR = r"(?:[<>]=?|=|≥|≤|at\s+least|at\s+most|up\s+to|within|about|approximately)"

#: Applied in order, repeatedly, until the text stops changing. Each one removes a span
#: that the criterion's ``window`` already expresses in days.
_TEMPORAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "(7 days)", "(>= 7 days)", "(within 3 months)" -- a parenthetical that is nothing
    # but a duration. A parenthetical carrying anything else ("(Insulin change <= 10%)",
    # "(PCI, CABG)") does not match and survives.
    re.compile(
        rf"\(\s*(?:{_COMPARATOR}\s*)?\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*{_UNIT}\s*\)",
        re.I,
    ),
    # "within 3 years", "in the past 12 months", "within the previous 24 hours"
    re.compile(
        rf"\b(?:with)?in\s+(?:the\s+)?(?:last|past|previous|preceding|prior)?\s*"
        rf"\d+(?:\.\d+)?\s*{_UNIT}\b",
        re.I,
    ),
    # "for 8 weeks", "for at least 3 months"
    re.compile(
        rf"\bfor\s+(?:at\s+least\s+|at\s+most\s+|a\s+minimum\s+of\s+|>=\s*|<=\s*)?"
        rf"\d+(?:\.\d+)?\s*{_UNIT}\b",
        re.I,
    ),
    # "30 days prior to randomisation" with no leading preposition. The milestone is
    # consumed here rather than left to the pattern below: cutting only the duration
    # strands the anchor ("Myocardial infarction randomisation"), which reads like an
    # entity and would be sent to the vocabulary as one.
    re.compile(
        rf"\b\d+(?:\.\d+)?\s*{_UNIT}\s+(?:prior|previous|preceding)\s+to"
        rf"(?:\s+{_MILESTONE})?",
        re.I,
    ),
    # "prior to randomization", "preceding screening" -- only ever with a milestone, so
    # "prior stroke" and "previous MI" are untouched.
    re.compile(rf"\b(?:prior|previous|preceding)\s+to\s+{_MILESTONE}", re.I),
)

#: Left behind when a span is cut out of the middle of a phrase.
_DANGLING_EDGE = re.compile(
    r"^\s*(?:and|or|of|for|in|at|to|the|a|an|,|;|:|-|–)\s+|"
    r"\s+(?:and|or|of|for|in|at|to|the|a|an)\s*[,;:.-]*\s*$",
    re.I,
)
_EMPTY_PARENS = re.compile(r"\(\s*\)")
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def strip_window_expressed_temporal(text: str) -> str:
    """Drop the duration qualifiers from ``text`` that a ``window`` already expresses.

    Byte-identical when nothing matched: the cleanup pass runs only after a real
    removal, so a seed this function has no opinion about is never reshaped by it.

    :param text: the seed text, e.g. ``"Cancer other than nonmelanoma skin cancer
        within 3 years"``.
    :returns: the seed with window-expressed durations removed, or ``text`` unchanged
        when nothing matched or when removing everything matched would leave no clinical
        entity behind.
    """
    if not text:
        return text

    stripped = text
    for _ in range(4):  # bounded: each pass can only shorten, four is far past fixpoint
        before = stripped
        for pattern in _TEMPORAL_PATTERNS:
            stripped = pattern.sub(" ", stripped)
        if stripped == before:
            break

    if stripped == text:
        return text

    stripped = _EMPTY_PARENS.sub(" ", stripped)
    stripped = " ".join(stripped.split())
    for _ in range(4):
        cleaned = _DANGLING_EDGE.sub("", stripped).strip(" ,;:-")
        if cleaned == stripped:
            break
        stripped = " ".join(cleaned.split())

    # Refusing to shrink a seed to nothing is the whole reason this returns the original
    # rather than "": an empty seed raises `REFUSAL_EMPTY_SEED` downstream, which would
    # trade one refusal code for another and lose the criterion just the same.
    if not stripped or not _HAS_LETTER.search(stripped):
        return text
    return stripped


def criterion_mapper_seed(criterion: Mapping[str, Any]) -> str:
    """The text the concept mapper should be asked to resolve for ``criterion``.

    Field precedence is unchanged -- ``sourceText`` first, then ``description`` -- so a
    criterion whose entity text survived extraction still maps on the entity text. What
    changes is the fallback: a description standing in for a missing ``sourceText``
    carries the whole protocol sentence, temporal qualifier included, and that qualifier
    is dropped when (and only when) the criterion has a ``window`` that already holds it.

    :param criterion: a store eligibility-criterion dict.
    :returns: the seed text, whitespace-collapsed; ``""`` when the criterion names
        nothing at all (the caller refuses that, and should).
    """
    seed = " ".join(
        ((criterion.get("sourceText") or criterion.get("description") or "").strip()).split()
    )
    if not seed or not criterion.get("window"):
        return seed
    return strip_window_expressed_temporal(seed)
