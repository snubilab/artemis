"""The one table deciding where a Measurement ``Unit`` filter may be dropped.

WHY A UNIT FILTER IS DROPPED AT ALL. Circe compiles ``Unit`` to
``AND unit_concept_id IN (...)``. On the 2026-09-12 delivery every unit-bearing
inclusion rule returned exactly 0 people at Ajou (6 of 6) while Dong-A passed the
same rules (4 of 4, 5.94%-84.19%); Ajou's CAROLINA fell from 31/46 on the unitless
2026-08-31 export to 0/0, the BMI rule alone taking 20,058 -> 0. Ajou's
``unit_concept_id`` cannot be observed: the hospital cannot be queried, the ACHILLES
snapshot has no unit dimension, and ``ajou_cdm`` is synthetic with units hardcoded
by ``scripts/synthesize_site_cdm.py``. A NULL unit matches no ``IN`` list, so
widening the list cannot fix it. The user decided to drop the filter on PRESENCE
criteria for the analytes below; exclusions keep their units, because a unit miss
there only lets a rule pass silently and never zeroes a cohort.

WHAT DROPPING IT RISKS, AND HOW THAT IS DECIDED. Without the filter the bare bound is
compared against a value in whatever unit the site stores. A value in the stated unit
(including a NULL-unit one) is compared correctly -- that is the recovery. A value in
an ALTERNATIVE unit either

* falls outside the bound -> the patient is MISSED (as they already are today), or
* falls inside the bound while its true value does not -> the patient is WRONGLY
  INCLUDED, which the unit filter was preventing.

Only the first is acceptable. Whether the second can happen depends on the BOUND as
much as on the analyte -- measured, not assumed: CARMELINA's HbA1c rule is
``gte 6.5 OR lte 10.0``, and every IFCC value (>= 15 mmol/mol) passes a bare
``>= 6.5``, while CAROLINA's ``bt 6.5..8.5`` can be reached by no alternative unit at
all. So the table records, per analyte, each alternative unit's plausible raw range
and an envelope converting it to the stated unit, and :func:`residual_risk` computes
the direction for the bound actually delivered. A bound that can wrongly include is
declined; the analyte stays in the table for the bounds that cannot.

HOW AN ANALYTE IS IDENTIFIED. By the Measurement concepts a concept set holds, never
by its name: names here are model-written free text, and ``%`` is also the unit of
non-HbA1c criteria such as CARMELINA's "Insulin dose". A set classifies as an analyte
only when EVERY concept it selects is listed under that one analyte. A member listed
nowhere, or members from two analytes, means the scale table does not cover the whole
set, and the answer is to decline.

Deliberately NOT listed, each found in the delivered sets, each therefore declining
the set that holds it (a one-line addition here if the decision changes):

* ``3005446`` Hemoglobin A1/Hemoglobin.total -- HbA1, which includes A1a and A1b and
  reads higher than HbA1c. In both EMPA-REG HbA1c sets.
* ``40758413`` Blood pressure systolic and diastolic -- a panel over two quantities.
  In CAROLINA's systolic BP set.
* ``3007070`` Cholesterol in HDL [Mass/volume] -- a different lipoprotein. In
  CAROLINA's LDL set.
* ``3035009`` Cholesterol in LDL [Units/volume] by Electrophoresis -- a relative
  fraction whose scale was not analysed. In CAROLINA's LDL set.

Pure: no I/O and no imports outside the standard library, so both the vocabulary-
backed export repair (:mod:`src.services.presence_unit_repair`) and the DB-free lint
(:func:`src.utils.circe_lint.unitless_value_bound_criteria`) read this one table.
The repair classifies the resolved closure; the lint, having no vocabulary, classifies
the seed concepts -- the same limit :data:`~src.utils.circe_lint.
DIMENSIONLESS_VALUE_CONCEPTS` carries, stated there.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

CAN_ONLY_MISS = "can only miss patients"
CAN_WRONGLY_INCLUDE = "can wrongly include patients"


@dataclass(frozen=True)
class AlternativeUnit:
    """A unit in clinical use for the analyte other than the one the bound states.

    ``plausible`` is the raw value range a real record in this unit falls in.
    ``stated_low`` / ``stated_high`` are ``(slope, intercept)`` of two increasing
    linear functions bracketing the TRUE value in the stated unit, so an uncertain
    conversion (HbA1c g/dL needs total hemoglobin) is an envelope rather than a point.
    Envelopes are deliberately loose: a looser envelope only ever turns a verdict into
    "can wrongly include", which declines.
    """

    unit: str
    plausible: tuple[float, float]
    stated_low: tuple[float, float]
    stated_high: tuple[float, float]
    basis: str


@dataclass(frozen=True)
class PresenceUnitAnalyte:
    name: str
    stated_unit_ids: frozenset[int]
    concepts: Mapping[int, str]
    alternatives: tuple[AlternativeUnit, ...]


def _linear(slope: float, intercept: float = 0.0) -> tuple[float, float]:
    return (slope, intercept)


#: THE allowlist. Bounds delivered on 2026-09-12 are recorded in each ``name``'s
#: comment; the direction column is computed, not written -- see :func:`residual_risk`
#: and the report that accompanied this table.
PRESENCE_UNIT_ANALYTES: tuple[PresenceUnitAnalyte, ...] = (
    # delivered: bt 6.5..8.5, bt 7.0..10.0, bt 7.0..9.0 (only miss); gte 6.5 and
    # lte 10.0 as separate criteria (can wrongly include -> declined)
    PresenceUnitAnalyte(
        name="HbA1c",
        stated_unit_ids=frozenset({8554}),  # %
        concepts={
            3004410: "Hemoglobin A1c/Hemoglobin.total in Blood",
            3007263: "Hemoglobin A1c/Hemoglobin.total in Blood by calculation",
            3003309: "Hemoglobin A1c/Hemoglobin.total in Blood by Electrophoresis",
            3034639: "Hemoglobin A1c [Mass/volume] in Blood",
            4197971: "HbA1c measurement (DCCT aligned)",
            44793001: "Hb A1c measurement - IFCC standardised",
        },
        alternatives=(
            AlternativeUnit(
                "mmol/mol (IFCC)", (15.0, 200.0), _linear(0.09148, 2.152), _linear(0.09148, 2.152),
                "NGSP/IFCC master equation: % = 0.09148 * mmol/mol + 2.152",
            ),
            AlternativeUnit(
                "fraction (1)", (0.03, 0.25), _linear(100.0), _linear(100.0),
                "% = 100 * fraction",
            ),
            AlternativeUnit(
                "g/dL (LOINC 41995-2 [Mass/volume])", (0.1, 4.0),
                _linear(100.0 / 20.0), _linear(100.0 / 7.0),
                "% = 100 * HbA1c g/dL / total Hb g/dL, total Hb taken in [7, 20] g/dL",
            ),
        ),
    ),
    # delivered: lte 45 (only miss)
    PresenceUnitAnalyte(
        name="BMI",
        stated_unit_ids=frozenset({9531}),  # kg/m2
        concepts={
            3038553: "Body mass index (BMI) [Ratio]",
            36304833: "Body mass index (BMI) [Ratio] Estimated",
            40762636: "Body mass index (BMI) [Percentile]",
            4245997: "Body mass index",
        },
        alternatives=(
            AlternativeUnit(
                "percentile (%) on 40762636", (0.0, 99.9), _linear(0.0, 10.0), _linear(0.25, 25.0),
                "BMI-for-age percentile is monotone in BMI; CDC 2000 medians stay near or "
                "under 22 kg/m2 and the 95th percentile near or under 33 kg/m2 at every "
                "age, so kg/m2 <= 0.25 * percentile + 25 is a loose upper envelope",
            ),
        ),
        # kg/m2 is the only unit BMI is reported in; lb/in2 is not a reporting unit.
    ),
    # delivered: gte 30 (only miss)
    PresenceUnitAnalyte(
        name="eGFR",
        # mL/min/(173.10*-2.m2), mL/min/1.73.m2, mL/min/{1.73}m -- all per 1.73 m2
        stated_unit_ids=frozenset({720870, 9117, 9062}),
        concepts={
            3049187: "GFR (MDRD)/1.73 sq M among non black population",
            36303797: "GFR (CKD-EPI)/1.73 sq M among non black population",
            40764999: "GFR (CKD-EPI)/1.73 sq M",
            46236952: "GFR (MDRD)/1.73 sq M",
        },
        alternatives=(
            AlternativeUnit(
                "mL/s/1.73m2 (SI)", (0.0, 3.0), _linear(60.0), _linear(60.0),
                "mL/min = 60 * mL/s",
            ),
        ),
        # "mL/min" on these concepts is an abbreviation of the same indexed number:
        # MDRD and CKD-EPI output per 1.73 m2 by definition.
    ),
    # delivered: gte 30 (only miss)
    PresenceUnitAnalyte(
        name="urine albumin/creatinine",
        stated_unit_ids=frozenset({8838, 8723}),  # ug/mg, mg/g -- numerically equal
        concepts={
            3001802: "Microalbumin/Creatinine [Mass Ratio] in Urine",
            3020682: "Albumin/Creatinine [Ratio] in Urine",
            3034485: "Albumin/Creatinine [Mass Ratio] in Urine",
        },
        alternatives=(
            AlternativeUnit(
                "mg/mmol", (0.0, 3000.0), _linear(8.84), _linear(8.84),
                "mg/g = 8.84 * mg/mmol (creatinine 113.12 g/mol)",
            ),
            AlternativeUnit(
                "g/g or mg/mg", (0.0, 30.0), _linear(1000.0), _linear(1000.0),
                "mg/g = 1000 * g/g",
            ),
        ),
    ),
    # delivered: gt 140 (only miss)
    PresenceUnitAnalyte(
        name="systolic BP",
        stated_unit_ids=frozenset({8876}),  # mm[Hg]
        concepts={
            3004249: "Systolic blood pressure",
            3035856: "Systolic blood pressure--standing",
        },
        alternatives=(
            AlternativeUnit(
                "kPa", (4.0, 40.0), _linear(7.50062), _linear(7.50062),
                "mmHg = 7.50062 * kPa",
            ),
        ),
    ),
    # delivered: gte 135 (only miss)
    PresenceUnitAnalyte(
        name="LDL cholesterol",
        stated_unit_ids=frozenset({8840}),  # mg/dL
        concepts={
            3001308: "Cholesterol in LDL [Moles/volume] in Serum or Plasma",
            3009966: "Cholesterol in LDL [Mass/volume] by Direct assay",
            3028288: "Cholesterol in LDL [Mass/volume] by calculation",
            3028437: "Cholesterol in LDL [Mass/volume] in Serum or Plasma",
            3038988: "Cholesterol in LDL [Moles/volume] by calculation",
            4041556: "Serum LDL cholesterol measurement",
            4042061: "Serum fasting LDL cholesterol measurement",
            4042062: "Serum random LDL cholesterol measurement",
            1761709: "Cholesterol in LDL [Mass/volume] by calculation, corrected for Lp(a)",
        },
        alternatives=(
            AlternativeUnit(
                "mmol/L", (0.1, 20.0), _linear(38.67), _linear(38.67),
                "mg/dL = 38.67 * mmol/L",
            ),
            AlternativeUnit(
                "g/L", (0.01, 8.0), _linear(100.0), _linear(100.0),
                "mg/dL = 100 * g/L",
            ),
        ),
    ),
)


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Classification:
    analyte: PresenceUnitAnalyte | None
    #: "ok", "none" (no member listed anywhere), "mixed" (members of two analytes)
    #: or "unlisted" (some members listed, some not).
    status: str
    detail: str = ""


def classify_concepts(concept_ids: Iterable[int]) -> Classification:
    """Which allowlisted analyte a set of concepts measures, if exactly one."""
    ids = set(concept_ids)
    if not ids:
        return Classification(None, "none", "empty concept set")
    owners: dict[str, list[int]] = {}
    unlisted: list[int] = []
    for cid in sorted(ids):
        owner = next((a.name for a in PRESENCE_UNIT_ANALYTES if cid in a.concepts), None)
        if owner is None:
            unlisted.append(cid)
        else:
            owners.setdefault(owner, []).append(cid)
    if not owners:
        return Classification(None, "none", "no member is an allowlisted analyte")
    if len(owners) > 1:
        return Classification(
            None, "mixed",
            "members of " + " and ".join(f"{k} {v}" for k, v in sorted(owners.items())),
        )
    if unlisted:
        name = next(iter(owners))
        return Classification(
            None, "unlisted",
            f"{name} set also holds concept(s) not listed under {name}: {unlisted}",
        )
    name = next(iter(owners))
    return Classification(next(a for a in PRESENCE_UNIT_ANALYTES if a.name == name), "ok")


# --------------------------------------------------------------------------
# residual risk
# --------------------------------------------------------------------------

_INF = float("inf")


def accepted_interval(value: Mapping[str, Any]) -> tuple[float, float] | None:
    """The closed interval a Circe ``ValueAsNumber`` accepts; None if not an interval.

    Open ends are treated as closed. That widens every intersection and so can only
    turn "can only miss" into "can wrongly include", never the reverse.
    """
    op = value.get("Op")
    try:
        low = float(value.get("Value"))
    except (TypeError, ValueError):
        return None
    if op in {"gt", "gte"}:
        return (low, _INF)
    if op in {"lt", "lte"}:
        return (-_INF, low)
    if op == "eq":
        return (low, low)
    if op == "bt":
        try:
            high = float(value.get("Extent"))
        except (TypeError, ValueError):
            return None
        return (min(low, high), max(low, high))
    return None  # "!bt" and anything unknown is not a single interval


def residual_risk(analyte: PresenceUnitAnalyte, value: Mapping[str, Any]) -> tuple[str, str]:
    """``(direction, why)`` for dropping the unit filter on this bound.

    For each alternative unit: the raw values that pass the bare bound are the
    plausible range intersected with the accepted interval. None -> such records can
    only be missed. Some -> map them through the envelope; if every true value they
    could stand for is also accepted, they are included correctly, otherwise a patient
    can be wrongly included.
    """
    accepted = accepted_interval(value)
    if accepted is None:
        return CAN_WRONGLY_INCLUDE, f"bound {dict(value)} is not a single interval"
    lo, hi = accepted
    for alt in analyte.alternatives:
        raw_lo, raw_hi = max(lo, alt.plausible[0]), min(hi, alt.plausible[1])
        if raw_lo > raw_hi:
            continue
        true_lo = alt.stated_low[0] * raw_lo + alt.stated_low[1]
        true_hi = alt.stated_high[0] * raw_hi + alt.stated_high[1]
        if not (lo <= true_lo and true_hi <= hi):
            return (
                CAN_WRONGLY_INCLUDE,
                f"{alt.unit} values {raw_lo:g}..{raw_hi:g} pass the bare bound but stand "
                f"for {true_lo:.3g}..{true_hi:.3g} in the stated unit",
            )
    return CAN_ONLY_MISS, "no alternative-unit value passes the bound wrongly"


# --------------------------------------------------------------------------
# which criteria are presence criteria
# --------------------------------------------------------------------------

#: Group types under which adding matching events can only add patients. AT_MOST
#: inverts that, so a criterion under it is not treated as presence.
_MONOTONE_GROUP_TYPES = {"ALL", "ANY", "AT_LEAST"}


def is_presence_occurrence(occurrence: Mapping[str, Any] | None) -> bool:
    """``at least N`` with N >= 1 -- the only occurrence shape that is monotone.

    Narrower than "not Type 0 Count 0" on purpose: ``exactly N`` (Type 0, N >= 1) can
    gain a patient at N-1 when more events match, and ``at most N`` (Type 1) loses
    patients. Across all 24 delivered files only ``{2, 1}`` and ``{0, 0}`` occur.
    """
    occurrence = occurrence or {}
    try:
        return occurrence.get("Type") == 2 and int(occurrence.get("Count", 0)) >= 1
    except (TypeError, ValueError):
        return False


def iter_presence_criteria(expression: Mapping[str, Any]) -> Iterator[tuple[int, dict]]:
    """``(rule index, criterion entry)`` for every InclusionRules presence criterion
    reached only through monotone groups."""
    def walk(group: Any) -> Iterator[dict]:
        if not isinstance(group, Mapping):
            return
        if str(group.get("Type", "ALL")).upper() not in _MONOTONE_GROUP_TYPES:
            return
        for entry in group.get("CriteriaList") or []:
            if isinstance(entry, dict) and is_presence_occurrence(entry.get("Occurrence")):
                yield entry
        for sub in group.get("Groups") or []:
            yield from walk(sub)

    for index, rule in enumerate(expression.get("InclusionRules") or []):
        if isinstance(rule, Mapping):
            for entry in walk(rule.get("expression")):
                yield index, entry


@dataclass(frozen=True)
class UnitDropVerdict:
    allowed: bool
    analyte: PresenceUnitAnalyte | None
    classification: Classification
    risk: str
    why: str


def unit_drop_verdict(concept_ids: Iterable[int], value: Mapping[str, Any]) -> UnitDropVerdict:
    """May a presence Measurement bound over these concepts go without a ``Unit``?

    The single predicate both the repair and the lint apply. The caller has already
    established that the criterion is a presence criterion (:func:`iter_presence_
    criteria`) on ``Measurement``; the repair additionally checks the unit it removes
    is the analyte's stated one, which the lint cannot see once it is gone.
    """
    classification = classify_concepts(concept_ids)
    if classification.analyte is None:
        return UnitDropVerdict(False, None, classification, "", classification.detail)
    risk, why = residual_risk(classification.analyte, value)
    return UnitDropVerdict(risk == CAN_ONLY_MISS, classification.analyte, classification, risk, why)


def seed_concept_ids(concept_set: Mapping[str, Any]) -> set[int]:
    """Included seed concept ids -- the lint's vocabulary-free stand-in for a closure."""
    out: set[int] = set()
    for item in (concept_set.get("expression") or {}).get("items") or []:
        if not isinstance(item, Mapping) or item.get("isExcluded"):
            continue
        cid = (item.get("concept") or {}).get("CONCEPT_ID")
        if cid is not None:
            out.add(int(cid))
    return out
