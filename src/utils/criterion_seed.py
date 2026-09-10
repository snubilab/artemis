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


#: Where the record below is written in a study's ``structuredExpression``, and read from
#: the delivered payload by ``scripts/verify_circe_delivery.py``. Same present-and-empty
#: contract as ``_defaultedWindowCriteria``: an ABSENT key means the artifact predates
#: the record, while a key present and empty is the positive claim that every criterion
#: reaching the mapper carried its own ``entity_text``. Only one of those two can be made
#: by an absent key, and it is the wrong one.
MISSING_ENTITY_CRITERIA_KEY = "_missingEntityCriteria"


def criterion_entity_text_missing(criterion: Mapping[str, Any]) -> bool:
    """Did the extraction leave this criterion's MANDATORY ``entity_text`` empty?

    ``entity_text`` is the only text the concept mapper is ever given, which is why
    ``agent1/prompts.NCT_SYSTEM_PROMPT`` makes it mandatory on every criterion with no
    ``sub_criteria`` (``8bbd50d``). When it is empty, :func:`criterion_mapper_seed`
    falls back to ``description`` -- a phrase written for a human ("Drug naive",
    "Stable Background Medication (8 weeks prior to screening)") -- and nothing said so.
    This function is the one place that fact is decided, so the record, the re-coded
    refusal, and the seed itself cannot disagree about which rows it covers.

    Reads the store column ``sourceText``, which carries the IR's ``entity_text``:
    ``_criterion_dict_from_ir_item`` assigns ``source_text = entity_text``, while the
    IR's own ``source_text`` -- the verbatim protocol line -- reaches the store as
    ``protocolLine``. The two names look alike and are not the same field.

    A GROUP LABEL is excluded, and that exclusion is the mandate's own: null is correct
    "ONLY on a parent row that has [sub_criteria]". A label never reaches the mapper
    (:attr:`~src.api.models.tte.EligibilityCriterion.mappable` is False for one), so it
    has no seed to substitute and firing here would report correct extraction as a
    defect. Measured on ``output/site_gap/2026-09-10/store_grounded/studies.json``,
    six delivered trials: 30 of the 117 rows with an empty ``sourceText`` are group
    labels, and three of the five rows that opened this investigation are among them.

    Whitespace counts as empty, because :func:`criterion_mapper_seed` strips before it
    chooses -- a ``sourceText`` of ``"   "`` seeds the mapper on the description exactly
    as an empty one does, and a predicate that disagreed would write a record
    contradicting the seed it describes.

    :param criterion: a store eligibility-criterion dict.
    :returns: ``True`` when the mapper will be seeded on something other than this
        criterion's own entity text.
    """
    if criterion.get("isGroupLabel"):
        return False
    return not (criterion.get("sourceText") or "").strip()


def missing_entity_record(
    criterion: Mapping[str, Any], *, role: str, mapped: bool
) -> dict[str, Any]:
    """One row of :data:`MISSING_ENTITY_CRITERIA_KEY`.

    Written for every criterion that reached the mapper on a substituted seed, whether
    or not the substitution cost anything. The survivors are the reason the record
    exists at all: on the 2026-09-10 grounded store 62 of the 70 substituted seeds
    MAPPED, each of them on a human-facing label ("CV risk factor A", "Positive
    biomarker", "Life expectancy"), and the only trace anywhere was a ``queryUsed``
    buried in mapping metadata. The 8 that did not map are already visible in
    ``_unmappedCriteria``; these are not.

    ``seed`` is recorded rather than re-derived by a consumer, so what the mapper was
    actually asked is on file even after the seed rules change.

    :param criterion: a store eligibility-criterion dict.
    :param role: ``"inclusion"`` or ``"exclusion"``, matching the sibling records.
    :param mapped: whether the criterion became a rule.
    """
    return {
        "criterionId": str(criterion.get("id", "")),
        "role": role,
        "label": (criterion.get("description") or "").strip(),
        "domain": (criterion.get("domain") or "").strip() or None,
        "seed": criterion_mapper_seed(criterion),
        "outcome": "mapped" if mapped else "unmapped",
    }
