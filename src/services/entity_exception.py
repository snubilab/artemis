"""Entity exclusions stated in eligibility-criteria prose.

The entity axis of what :mod:`route_qualifier` does for routes. A criterion
names a set and then names part of it to leave out -- "insulin other than human
NPH insulin", "cancer other than non-melanoma skin cancer" -- and the pipeline
has never read that second half. Measured on the 2026-09-14 delivery: **0**
``isExcluded`` items across 514 concept sets in all 12 files, against gold's 718
across 59 of its 469 sets.

The consequence is an inversion rather than an omission. LEADER codeset 54
'insulin other than human NPH insulin' holds the same 26 ids as codeset 12
'human NPH insulin', so the phrase resolved to its own complement and the
exclusion removes exactly the patients the protocol requires to be on that
insulin. CAROLINA codeset 45 'cancer other than non-melanoma skin cancer' holds
20 members of which the vocabulary places 19 under `Malignant neoplasm of skin`
(4155297) or `Neoplasm of skin` (444209) and none under `Malignant melanoma of
skin` (141232) -- they ARE the excepted entity.

Pure regex, like ``route_qualifier``: no LLM, no embedding, no database. It says
only what the text asked for. Turning that into ``isExcluded`` items is
:mod:`entity_subtraction`'s job, and finding the concepts is the mapper's.

What is deliberately NOT a connective
-------------------------------------
A hyphenated ``non-X`` is part of a term, never a split point. Checked against
the delivery's own ten negation-named concept sets: splitting on it would fire
wrongly on four of them (`non-familial medullary thyroid carcinoma`,
`Non-ST-segment elevation myocardial infarction`, `Unreliable/Non-compliant`,
`life expectancy less than 5 years for non-CV causes`) and would mangle the
excepted phrase of the one case that matters most -- `cancer other than
**non-melanoma** skin cancer`.

An anaphoric excepted phrase ("specified types", "allowed short-term insulin",
"the above") points back at protocol text this module cannot see. It is
declined, not guessed at: leaving a criterion unsubtracted preserves the current
over-inclusion, while subtracting on a guess creates a new wrong exclusion,
which is the failure this exists to prevent. Same rule as
:mod:`route_subtraction`'s undecidable forms.

Detection of the shipped defect already exists in
``tests/test_concept_set_negation_lints.py``; this is the repair side.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Adjacent connectives. `other` and `than` must touch: a protocol's "has any
# other condition than mentioned" is not a set exception, and "less than" /
# "rather than" never contain the word `other` at a word boundary at all.
_CONNECTIVE = r"other\s+than|except\s+for|except|excluding|apart\s+from|but\s+not|exclusive\s+of"

_PARENTHESISED = re.compile(
    rf"^(?P<base>.*?)\s*\(\s*(?:{_CONNECTIVE})\s+(?P<excepted>[^()]+?)\s*\)\s*$",
    re.IGNORECASE,
)
_ADJACENT = re.compile(
    rf"^(?P<base>.*?)\s+(?:{_CONNECTIVE})\s+(?P<excepted>.+)$",
    re.IGNORECASE,
)

# A trailing time window belongs to the criterion, not to the entity. The store's
# sourceText for CAROLINA's criterion is "...skin cancer within last 3 years";
# leaving that on would send the whole clause to the mapper, which is the very
# failure mode being repaired.
_TRAILING_WINDOW = re.compile(
    r"\s+(?:with)?in\s+(?:the\s+)?"
    r"(?:last|past|previous|preceding|prior(?:\s+to)?)?\s*\d+\s*\w+.*$",
    re.IGNORECASE,
)

# The excepted phrase names nothing this module can resolve.
_ANAPHORIC_HEAD = re.compile(
    r"^(?:the\s+)?(?:above|foregoing|following|former|latter|rest|remainder|others?)\b",
    re.IGNORECASE,
)
_ANAPHORIC_WORD = re.compile(
    r"\b(?:specified|allowed|permitted|listed|mentioned|stated|described|noted"
    r"|these|those|such|aforementioned)\b",
    re.IGNORECASE,
)

# A concept name longer than this is a clause, not an entity. The delivered
# corpus's excepted phrases run 1-3 words.
_MAX_EXCEPTED_WORDS = 8

_SPLIT_STOPWORDS = frozenset({"and", "or", "the", "a", "an", ""})

# ` + ` joins several criteria into one group label ("Unreliable/Non-compliant +
# Life Expectancy < 5 years + Cancer other than nonmelanoma skin cancer"). Its
# base would be "A + B + Cancer", which names no entity a mapper can resolve.
_GROUP_LABEL_JOIN = " + "

# A comma list can end in a conjunction: "human NPH, long-acting analogue, or
# premixed insulin". Splitting on "," leaves the "or" attached to the last part.
_LEADING_CONJUNCTION = re.compile(r"^(?:and|or)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class EntityException:
    """What a criterion's text says about an entity to leave out.

    :param text: the criterion text that was scanned.
    :param base: the set the criterion names, to be mapped as usual.
    :param excepted: the entities to subtract from it, one mappable phrase each.
    """

    text: str
    base: str = ""
    excepted: list[str] = field(default_factory=list)


def _split_excepted(phrase: str) -> list[str]:
    """Split a list of excepted entities, conservatively.

    ``,`` and `` or `` always separate. ``/`` separates only when every part is a
    single token -- `GLP-1/DPP-4/SGLT-2` is a list, `skin of head/neck` is one
    anatomical name and splitting it would invent an entity called "neck".
    """
    parts = [_LEADING_CONJUNCTION.sub("", p.strip()).strip()
             for p in re.split(r"\s*,\s*|\s+or\s+", phrase) if p.strip()]
    out: list[str] = []
    for part in parts:
        slashed = [s.strip() for s in part.split("/")]
        if len(slashed) > 1 and all(s and " " not in s for s in slashed):
            out.extend(slashed)
        else:
            out.append(part)
    return [p for p in out if p.lower() not in _SPLIT_STOPWORDS]


def detect_entity_exception(text: str | None) -> EntityException | None:
    """Read the entity exclusion a criterion states, if it states one.

    :param text: criterion name, description or source text.
    :returns: the base and the excepted entities, or None when the text states
        no exception or states one this module cannot resolve. None means "leave
        it alone", never "there was nothing there".
    """
    if not text or not text.strip():
        return None

    normalized = " ".join(text.split())
    if _GROUP_LABEL_JOIN in normalized:
        return None

    match = _PARENTHESISED.match(normalized) or _ADJACENT.match(normalized)
    if match is None:
        return None

    base = match.group("base").strip().strip(",").strip()
    excepted_raw = match.group("excepted").strip()

    # The window belongs to the criterion; the entity is what is left.
    excepted_raw = _TRAILING_WINDOW.sub("", excepted_raw).strip().strip(",").strip()

    if not base or not excepted_raw:
        return None
    if base.lower() in _SPLIT_STOPWORDS:
        return None
    if len(excepted_raw.split()) > _MAX_EXCEPTED_WORDS:
        return None
    if _ANAPHORIC_HEAD.match(excepted_raw) or _ANAPHORIC_WORD.search(excepted_raw):
        return None

    excepted = _split_excepted(excepted_raw)
    if not excepted:
        return None

    return EntityException(text=normalized, base=base, excepted=excepted)
