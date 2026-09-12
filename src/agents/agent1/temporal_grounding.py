"""The time window a protocol LINE states, read from the line itself.

Agent 1 writes ``window`` as two integers and nothing converts or checks them:
``_build_criteria`` does ``TemporalWindow(**data["window"])`` straight from the model's
JSON. Three defects reach a delivery through that gap, and the 2026-09-14 conversion
audit found all three at once:

* **the unit is never converted** -- ``24 hours`` emitted as ``-24`` days (PLATO, twice)
  and ``3 years`` as ``-3`` days (CARMELINA), each off by the unit's own factor;
* **the magnitude slips** -- ``6 weeks`` emitted as ``-420`` on four CAROLINA rules,
  which is not a unit confusion at all: the same model on the same line writes the
  correct ``-42`` on 76 windows across the caches, so 420 is a digit the model appended;
* **the polarity inverts** -- ``> 6 weeks prior to informed consent`` means the event
  must be OLDER than six weeks, an open-ended LOWER bound on elapsed time. Emitted as
  ``-42..0`` it says the opposite, and selects exactly the patients that branch of the
  protocol excludes.

All three are answerable from the line, which is why this module reads the line. The
grounding is ``source_text`` -- the protocol text handed to the model, verbatim -- for
the reason :func:`~src.agents.agent1.parser.inclusive_upper_bounds` gives about its own
grounding: a criterion's ``name`` is written by the model and is not a stable signal,
so a number appearing only there is not evidence about the protocol.

Deliberately conservative. A line whose interval cannot be attached to THIS criterion
yields nothing, and the caller leaves the window alone. Measured over all 122 IR caches
(5,092 windows), the two acceptance paths below decide 557 of them and decline 4,535 --
declining is the common outcome by design, because a repair that rewrites a window it
guessed at is worse than one that never fires.
"""
from __future__ import annotations

import math
import re
from typing import NamedTuple, Optional

#: Days per unit, as this codebase already renders them elsewhere: a month is 30 days
#: (`-90` for three months, `-180` for six) and a year 365 (`-1825` for five, `-1460`
#: for four). Those renderings are read off the emitted corpus, not chosen here.
_UNIT_DAYS: dict[str, float] = {
    "hour": 1 / 24, "hours": 1 / 24, "hr": 1 / 24, "hrs": 1 / 24, "h": 1 / 24,
    "day": 1, "days": 1,
    "week": 7, "weeks": 7, "wk": 7, "wks": 7,
    "month": 30, "months": 30, "mo": 30, "mos": 30,
    "year": 365, "years": 365, "yr": 365, "yrs": 365,
}

#: The upper end of each unit's defensible rendering. A calendar month is 30 OR 31 days
#: and a year 365 OR 366, so `12 months` is defensibly 360 (12x30) and equally
#: defensibly 365 -- both appear in the corpus. Re-rendering one into the other would
#: be churn on a window that was never wrong, so the whole band counts as correct and
#: only a value OUTSIDE it is a defect.
_UNIT_DAYS_UPPER: dict[float, float] = {1 / 24: 1 / 24, 1: 1, 7: 7, 30: 31, 365: 366}

_UNITS_RE = "|".join(sorted(_UNIT_DAYS, key=len, reverse=True))

#: "older than N", the shape that makes a window a LOWER bound on elapsed time.
#: `at least` is deliberately absent: `stable anti-diabetic background for at least
#: 8 wks before study start` is a duration of a state through the window, not an event
#: older than it, and 46 corpus windows read it correctly as `-56..0`.
_OLDER_THAN = r"(?:>|&gt;|more\s+than|greater\s+than|longer\s+than)"

_INTERVAL = re.compile(
    r"(?P<older>" + _OLDER_THAN + r")?\s*"
    r"(?P<n>[0-9]+(?:\.[0-9]+)?)\s*[-‐-―]?\s*"
    r"(?P<unit>" + _UNITS_RE + r")\b",
    re.IGNORECASE,
)

#: Words that put a number+unit BEHIND the index date.
_BACKWARD = re.compile(
    r"\b(?:prior|previous|preceding|before|within|last|past|ago|since|"
    r"history|recent|earlier|screening|randomi[sz]ation|consent|"
    r"enrol\w*|baseline|index|documented|duration|for\s+at\s+least)\b",
    re.IGNORECASE,
)

#: ...and words that put it AHEAD of it. `planned within next 6 months after V1a` is a
#: prospective clause on the same CAROLINA line as a `<= 6 weeks prior` lookback, so
#: the two sets are resolved by proximity rather than by presence.
_FORWARD = re.compile(
    r"\b(?:next|following|planned|plan|expectancy|expected|survival|"
    r"after|post|during\s+the\s+study|follow[\s-]?up)\b",
    re.IGNORECASE,
)

#: `>= 18 years of age`, `Age >= 70 years`, `65 years old`. A demographic bound, not a
#: lookback. Without this the PLATO inclusion line's `>=18 years of age` reads as a
#: 6,570-day window and every criterion on that line inherits it.
_AGE = re.compile(r"\b(?:age[ds]?|old)\b", re.IGNORECASE)

#: How far a stated interval may sit from the entity it qualifies before the attachment
#: stops being evidence. CAROLINA's OR-group line is 1,861 characters and states six
#: intervals; `Myocardial infarction (> 6 weeks ...)` puts its own two characters away,
#: while the `> 10 years` on a different clause 1,400 characters later belongs to a
#: different entity entirely.
_MAX_ANCHOR_GAP = 40

#: Separators that end a clause on these lines: the OR-group joiner and the semicolon.
#: An interval on the far side of one is qualifying something else.
_CLAUSE_BREAK = re.compile(r"[|;]")

#: The codebase's all-time convention (`prompts.py`, `circe_lint.py`), which is what a
#: lower-bound window opens at: "any time up to N days before index".
ALL_TIME_START = -9999


class Interval(NamedTuple):
    """One stated interval, with where it sits and which way it points."""

    #: Character offset of the match in the text it was read from.
    start: int
    #: Length in days, rounded UP. See :func:`_days` for why up.
    days: int
    #: Upper end of the same interval's defensible rendering (30- vs 31-day month).
    days_upper: int
    #: True for `> 6 weeks prior` -- the event must be OLDER than this.
    #: False for `within 6 weeks` -- the event must be NEWER than this.
    older_than: bool
    #: The matched text, for the repair's ledger reason.
    text: str


def _days(n: float, per_unit: float) -> int:
    """Days, rounded UP, never below 1.

    Circe's ``StartWindow`` counts whole days, so a sub-day interval has to land on
    one. ``24 hours`` becomes 1 day rather than 0 because 0 is not a shorter window,
    it is a DIFFERENT one: ``Days: 0`` means the index date alone, which drops a
    qualifying event that happened twenty hours earlier but on the previous calendar
    date. Rounding up keeps every patient the protocol admits; rounding down silently
    removes some.
    """
    return max(1, math.ceil(n * per_unit))


def _direction(text: str, pos: int, radius: int = 45) -> Optional[str]:
    """``"backward"``, ``"forward"`` or ``None`` -- by the NEAREST direction word.

    Presence is not enough, because both appear on one line: PLATO's
    ``Fibrinolytic therapy planned or within the previous 24 h`` carries `planned` and
    `previous`, and CAROLINA's ``within next 6 months after V1a or any previous PCI
    ... <= 6 weeks prior`` carries both twice. The word closest before the number is
    the one qualifying it.
    """
    segment = text[max(0, pos - radius):pos]
    back = max((m.start() for m in _BACKWARD.finditer(segment)), default=None)
    fwd = max((m.start() for m in _FORWARD.finditer(segment)), default=None)
    if back is None and fwd is None:
        trailing = text[pos:pos + radius]
        if _BACKWARD.search(trailing) and not _FORWARD.search(trailing):
            return "backward"
        return None
    if fwd is None:
        return "backward"
    if back is None:
        return "forward"
    return "backward" if back > fwd else "forward"


def temporal_intervals(text: Optional[str]) -> list[Interval]:
    """Every lookback interval the text states, in order of appearance.

    Silent about forward-looking intervals and about age bounds: neither is a window
    on prior history, and admitting either lets an unrelated number on the same line
    become a criterion's window.
    """
    found: list[Interval] = []
    if not text:
        return found
    for match in _INTERVAL.finditer(text):
        neighbourhood = text[max(0, match.start() - 12):match.end() + 14]
        if _AGE.search(neighbourhood):
            continue
        if _direction(text, match.start()) != "backward":
            continue
        n = float(match.group("n"))
        per_unit = _UNIT_DAYS[match.group("unit").lower()]
        found.append(
            Interval(
                start=match.start(),
                days=_days(n, per_unit),
                days_upper=_days(n, _UNIT_DAYS_UPPER[per_unit]),
                older_than=bool(match.group("older")),
                text=match.group(0).strip(),
            )
        )
    return found


def _squash(text: str) -> tuple[str, list[int]]:
    """Alphanumerics only, lowercased, plus a map back to original offsets.

    Dropping separators rather than normalising them is what lets an entity match its
    own mention across a spelling difference: the IR carries ``Cancer other than
    nonmelanoma skin cancer`` and CAROLINA's line writes ``cancer other than
    non-melanoma skin cancer``. Squashed, those are the same string.
    """
    chars: list[str] = []
    offsets: list[int] = []
    for i, ch in enumerate(text):
        if ch.isalnum():
            chars.append(ch.lower())
            offsets.append(i)
    return "".join(chars), offsets


def _entity_anchored(source_text: str, entity: str,
                     candidates: list[Interval]) -> Optional[Interval]:
    """The interval that sits immediately after THIS criterion's own mention.

    The locality constraint is the whole point. CAROLINA's four
    ``> N prior to informed consent`` qualifiers share one 1,861-character OR-group
    line stating six intervals, and each qualifier's own interval is parenthesised
    right after its name. Without the gap and clause-break limits the same line also
    offers ``in previous 12 months`` and ``duration > 10 years`` to any criterion
    whose name happens to appear earlier in it.
    """
    squashed_source, offsets = _squash(source_text)
    squashed_entity, _ = _squash(entity)
    if not squashed_entity:
        return None
    pos = squashed_source.find(squashed_entity)
    if pos < 0:
        return None
    mention_end = offsets[pos + len(squashed_entity) - 1] + 1
    after = [c for c in candidates if c.start >= mention_end]
    if not after:
        return None
    nearest = min(after, key=lambda c: c.start)
    gap = source_text[mention_end:nearest.start]
    if len(gap) > _MAX_ANCHOR_GAP or _CLAUSE_BREAK.search(gap):
        return None
    return nearest


def stated_interval(source_text: Optional[str],
                    name: Optional[str]) -> tuple[Optional[Interval], Optional[str]]:
    """The interval the protocol line states FOR THIS CRITERION, or ``(None, None)``.

    Two acceptance paths, both requiring the interval to be tied to this criterion
    rather than merely present on its line:

    ``name-agreement``
        The criterion's own name restates one interval and the protocol line states
        the same one. The name alone would not be evidence -- it is model output --
        but a name and a line that agree pin down WHICH of the line's intervals this
        criterion is about. This is what resolves PLATO's inclusion 1, whose line runs
        272 characters and whose entity (``ACS``) never appears in it by the name the
        IR uses.

    ``entity-anchor``
        The criterion's entity is named in the line and an interval follows it
        immediately. This is what resolves CAROLINA's four OR-group qualifiers and the
        cancer clause that CAROLINA and CARMELINA share.

    Anything else declines. In particular a line stating several intervals and a
    criterion whose name states none is NOT resolved by picking the first: measured,
    admitting that path rewrote 268 further windows, among them ``Age >= 18 years``
    taking PLATO's 24-hour window and ``LVEF <= 40%`` taking ARISTOTLE's 90-day one.

    :returns: ``(interval, how)`` where ``how`` is the accepting path's name, for the
        repair's ledger record.
    """
    candidates = temporal_intervals(source_text)
    if not candidates:
        return None, None

    from_name = temporal_intervals(name)
    if from_name and len({(i.days, i.older_than) for i in from_name}) == 1:
        wanted = from_name[0]
        for candidate in candidates:
            if (candidate.days, candidate.older_than) == (wanted.days, wanted.older_than):
                return candidate, "name-agreement"

    if name and source_text:
        anchored = _entity_anchored(source_text, name, candidates)
        if anchored is not None:
            return anchored, "entity-anchor"
    return None, None


def window_for(interval: Interval, current_end: Optional[int]) -> tuple[int, int]:
    """The ``(start, end)`` a stated interval means, in the IR's day convention.

    ``older_than`` is a different SHAPE, not a different magnitude. "Myocardial
    infarction more than six weeks before consent" admits an infarction from twenty
    years ago and refuses one from last week, so it opens at the all-time sentinel and
    CLOSES 42 days before index -- ``(-9999, -42)``. The recency reading ``(-42, 0)``
    selects precisely the patients that clause excludes.

    A negative ``End`` is emittable: ``tte_service.py`` builds
    ``{"Days": abs(end), "Coeff": 1 if end >= 0 else -1}``, so ``end=-42`` renders as
    ``{"Days": 42, "Coeff": -1}``. This was checked before the shape was chosen.

    A recency window keeps whatever post-index end the extraction gave it -- two
    corpus windows run to ``+365`` -- and only moves the start.
    """
    if interval.older_than:
        return ALL_TIME_START, -interval.days
    end = current_end if current_end is not None and current_end > 0 else 0
    return -interval.days, end


def window_agrees(interval: Interval, start: Optional[int], end: Optional[int]) -> bool:
    """Whether an emitted window is already a defensible reading of this interval.

    Both the shape and the magnitude have to match, and the magnitude matches against
    the whole 30-or-31-day band rather than a single number, so ``12 months`` accepts
    both the ``-360`` and the ``-365`` rendering and neither is rewritten into the
    other.
    """
    if interval.older_than:
        return (start == ALL_TIME_START and end is not None
                and interval.days <= -end <= interval.days_upper)
    return (start is not None and end is not None and end >= 0
            and interval.days <= -start <= interval.days_upper)


def temporal_numerals(text: Optional[str]) -> set[float]:
    """The bare numerals of every lookback interval the text states.

    Used to recognise a window whose number the model did not read off this
    criterion's line but copied from another one in the same trial. PLATO's
    ``Index event is an acute complication of PCI`` carries no digit anywhere and was
    emitted with a 24-day window -- the numeral of the ``24 hours`` phrases on two
    unrelated criteria of the same trial.
    """
    return {
        float(m.group("n"))
        for m in _INTERVAL.finditer(text or "")
        if not _AGE.search((text or "")[max(0, m.start() - 12):m.end() + 14])
        and _direction(text or "", m.start()) == "backward"
    }
