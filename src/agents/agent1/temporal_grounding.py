"""Number x unit -> days, for a duration the annotation step quoted.

RFC-016 §3 replaced this module's former job -- regrounding a criterion's window from the
direction words around a number in its protocol line (inventory A4, E3) -- with the
annotation's ``timing`` field and its verified ``window_span``. What is left is the
conversion RFC-016 keeps as a machine format: a quantity and its time unit, read off a
fragment the model already quoted and the code already checked against ``protocolLine``.
Nothing here decides a window, a direction or a timing.

Its one consumer is :func:`src.services.criterion_annotation.window_disagreement`, which
compares the converted duration with the extracted window and records a disagreement on
the row. It never rewrites the window.
"""
from __future__ import annotations

import math

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
#: defensibly 365 -- both appear in the corpus.
_UNIT_DAYS_UPPER: dict[float, float] = {1 / 24: 1 / 24, 1: 1, 7: 7, 30: 31, 365: 366}

#: Characters a quantity or a unit token may carry at its edges in a quoted fragment:
#: brackets, separators and comparison signs. Never letters.
_EDGE = "()[],;:.<>=≤≥~"


def _days(n: float, per_unit: float) -> int:
    """Days, rounded UP, never below 1 (Circe counts whole days; 0 is a different window)."""
    return max(1, math.ceil(n * per_unit))


def _number(token: str) -> float | None:
    try:
        value = float(token.strip(_EDGE))
    except ValueError:
        return None
    return value if value > 0 else None


def stated_durations(span: str | None) -> list[tuple[int, int]]:
    """Each ``<number> <unit>`` pair in a quoted fragment, as a ``(days, days_upper)`` band.

    Tokenised on whitespace: a number immediately followed by a time unit. Anything else --
    a number followed by a word that is not a unit, a unit glued to its number -- yields
    nothing, and the caller then records nothing. Declining is the safe outcome here because
    the only use of the result is a report.

    :param span: a fragment of ``protocolLine`` the annotation step already verified.
    :returns: one ``(days, days_upper)`` per stated duration, in order of appearance.
    """
    tokens = (span or "").split()
    found: list[tuple[int, int]] = []
    for value_token, unit_token in zip(tokens, tokens[1:]):
        n = _number(value_token)
        per_unit = _UNIT_DAYS.get(unit_token.strip(_EDGE).lower())
        if n is None or per_unit is None:
            continue
        found.append((_days(n, per_unit), _days(n, _UNIT_DAYS_UPPER[per_unit])))
    return found
