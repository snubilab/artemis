"""Specimen, property and challenge of the LOINC lab tests in a Measurement concept set.

The one home for three decisions that the concept-set builder and the delivery gate both make:
which LOINC lab tests a criterion's concept set may hold, which it is missing, and which make the
criterion's own unit filter unmatchable. ``TTEService._build_seeded_eligibility_rule`` applies
:func:`refine_measurement_concept_set`; ``circe_lint.specimen_mismatched_measurement_criteria``
reports :func:`specimen_violations`. Neither re-derives anything here.

The defect, measured on ``deliveries/2026-09-23``. The mapper is handed the bare analyte
("glucose"), retrieval ranks the routine serum code beyond the fetched pool (3004501 at #217),
the reranker keeps vitreous-fluid and CSF/plasma-ratio codes, and the expression builder drops
the SNOMED parents that would have covered the rest. EMPA-REG codeset 10 and CAROLINA codesets
41/42 shipped as {3000483, 3004378, 3004676, 44816672}, all zero in ACHILLES 1800 at Ajou, Dong-A
and Keimyung, so "glucose > 240 mg/dL" excluded nobody. Codeset 42 (> 13.3 mmol/L) held only Mass
Concentration codes, so its ``Unit`` could never match. The same shape sits in the ALT, AST,
bilirubin and CK-MB sets: the right serum code plus red-cell, dried-blood-spot, amniotic, urine,
synovial and CSF siblings.

Everything is read off the LOINC axes in the vocabulary (``Has component``, ``Has system``,
``Has property``, ``Has scale type``) and off the criterion's own words. No concept id, analyte
name or trial appears in the logic. Three small tables are written down, each because the
vocabulary does not carry the fact:

* :data:`CIRCULATING_BLOOD_SYSTEM_WORDS`. The 1,045 ``Is a`` edges among ``LOINC System``
  concepts are radiology anatomy only ("Finger fifth - left" -> "Finger fifth"); no edge says
  that "Serum or Plasma" is a blood specimen or that "Red Blood Cells" is a fraction of one. The
  allowlist is six words, matched per token of the system name, so "Serum, Plasma or Blood" and
  "Blood arterial" qualify while "Red Blood Cells", "DBS", "Platelet poor plasma", "Blood^Fetus"
  and "Urine and Serum or Plasma" do not.
* :data:`_UNIT_DIMENSION` / :data:`_PROPERTY_BY_DIMENSIONS`. OMOP holds no edge from a UCUM unit
  to a LOINC property, so the property is derived from the UCUM code's grammar: the dimension of
  each '/'-separated atom (mass, substance, catalytic, count, volume, time, area). Unit ids are
  never consulted. Only concentrations and volume rates are named; see the table for why ratios
  are not.
* :data:`_STATED_CHALLENGES`. LOINC writes a challenge as the component's second part
  ("Glucose^post CFst") in its own abbreviations; the one mapping from a criterion's words onto
  that axis is "fast..." -> ``CFst`` (calorie fast).

``LabTest`` and the functions over it are pure. :class:`PostgresLabTestVocabulary` is the only
I/O, and imports its driver lazily so importing this module needs no database.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

LOINC_VOCABULARY = "LOINC"
LAB_TEST_CLASS = "Lab Test"
MEASUREMENT_DOMAIN = "Measurement"
QUANTITATIVE_SCALE = "Qn"
#: The LOINC Time part LP6960-1 ("Pt"): one specimen at one moment. Its siblings are timed
#: collections ("24 hours", "12 hours") and study summaries ("Stdy^mean", "Stdy^max").
POINT_IN_TIME = "Point in time (spot)"

#: Tokens of a LOINC System name that denote a serum, plasma or whole-blood specimen.
#: See the module docstring for why this cannot be derived from the vocabulary.
CIRCULATING_BLOOD_SYSTEM_WORDS = frozenset(
    {"serum", "plasma", "blood", "arterial", "venous", "capillary"}
)
_SYSTEM_CONNECTIVES = frozenset({"and", "or"})
#: A criterion names a system token when one of its words shares this many leading letters
#: with it ("urinary" names "Urine"). Shorter tokens must match whole.
_NAMING_PREFIX = 4
_WORD = re.compile(r"[a-z0-9]+")

# UCUM atom -> physical dimension. Prefixes are UCUM's; the atoms are the base units LOINC
# properties are defined over.
_MASS = re.compile(r"^(k|m|u|n|p|d|c|μ)?g$")
_SUBSTANCE = re.compile(r"^(m|u|n|p)?mol$")
_VOLUME = re.compile(r"^(d|c|m|u)?L$|^mm3$")
_COUNT = re.compile(r"^(10\*\d+)?$")
_UNIT_DIMENSION: tuple[tuple[re.Pattern[str], str], ...] = (
    (_COUNT, "count"),
    (_MASS, "mass"),
    (_SUBSTANCE, "substance"),
    (re.compile(r"^\[U\]$|^U$"), "catalytic"),
    (re.compile(r"^\[[iI]U\]$"), "arbitrary"),
    (_VOLUME, "volume"),
    (re.compile(r"^(min|h|s|d)$"), "time"),
    (re.compile(r"^\(.*m2\)$|^(c|d|m)?m2$"), "area"),
)
_PROPERTY_BY_DIMENSIONS = {
    ("mass", "volume"): "Mass Concentration",
    ("substance", "volume"): "Substance Concentration",
    ("catalytic", "volume"): "Catalytic Concentration",
    ("count", "volume"): "Number Concentration",
    ("arbitrary", "volume"): "Arbitrary Concentration",
    ("volume", "time"): "Volume Rate",
    ("volume", "time", "area"): "Volume Rate/Area",
}
# The readings below name a FAMILY of LOINC properties, each name read from the vocabulary's
# 'Has property' targets (synthea23m, 2026-10-08), not assumed:
# * mass/area: the vocabulary has no areic-mass property; both BMI ratio codes (39156-5,
#   89270-3) carry 'Ratio' (LP6852-0), and their percentile siblings 'Percentile' (LP6846-2).
# * substance/substance: 'Substance Fraction' (LP6866-0, e.g. HbA1c by IFCC 59261-8) and
#   'Substance Ratio' (LP6868-6) -- a quotient of two amounts of substance is one or the other.
_PROPERTY_FAMILIES_BY_DIMENSIONS: dict[tuple[str, ...], frozenset[str]] = {
    ("mass", "area"): frozenset({"Ratio"}),
    ("substance", "substance"): frozenset({"Substance Fraction", "Substance Ratio"}),
}
#: '%' is the dimensionless unit 1 scaled by 1/100. LOINC reports its non-decimal fraction
#: properties in it -- 'Mass fraction' (LP6831-4, HbA1c 4548-4), 'Number Fraction' (LP6838-9),
#: 'Volume Fraction' (LP6891-8) ... -- and gives the unit-1 forms their own 'Decimal ...'
#: properties ('Decimal mass fraction' LP150070-3, HbA1c 71875-9), which '%' does not name.
PERCENT_FRACTION_PROPERTIES = frozenset({
    "Mass fraction", "Substance Fraction", "Volume Fraction", "Number Fraction",
    "Arbitrary fraction", "Catalytic Fraction", "Length fraction", "Saturation Fraction",
    "Area Fraction", "Time Fraction", "Circumference Fraction",
})
#: Single-atom units: '%' above; mm[Hg] is a pressure, which LOINC files as 'Pressure'
#: (LP6847-0, systolic blood pressure 8480-6) or 'Partial pressure' (LP6845-4, pO2/pCO2).
_PROPERTY_FAMILIES_BY_ATOM: dict[str, frozenset[str]] = {
    "%": PERCENT_FRACTION_PROPERTIES,
    "mm[Hg]": frozenset({"Pressure", "Partial pressure"}),
}
# Deliberately absent: mass/mass and substance/substance. LOINC files the same urine
# albumin/creatinine quotient under both 'Mass Ratio' (14959-1) and 'Ratio' (32294-1), both
# reported in mg/g, and TROY's CAROLINA UACR set holds both; measured on the 2026-10-07 run,
# reading ug/mg as 'Mass Ratio' dropped CAROLINA codeset 25's gold recall from 1.0 to 0.667.

#: Criterion word prefix -> the LOINC challenge token it states.
_STATED_CHALLENGES = {"fast": "cfst"}
#: Challenge tokens that time a state rather than name one ("post", "12H", "45M").
_CHALLENGE_TIMING = re.compile(r"^(post|\d+(\.\d+)?[hmd])$")


@dataclass(frozen=True)
class LabTest:
    """One LOINC lab test, as its four axes describe it."""

    concept_id: int
    concept_name: str
    component: str
    system: str | None
    property: str | None
    scale: str | None
    concept_code: str = ""
    domain_id: str = MEASUREMENT_DOMAIN
    #: The ``Has component`` concept. Names are not unique: 72 LOINC Component names are held
    #: by two concepts, e.g. 'Glucose' by LP14635-4 and by LP435977-6, whose only lab test is a
    #: glucagon-challenge glucose that lost its '^' part.
    component_id: int | None = None
    #: The ``Has time aspect`` concept name.
    time_aspect: str | None = None

    @property
    def analyte(self) -> str:
        return analyte_of(self.component)

    @property
    def challenge(self) -> str | None:
        return challenge_of(self.component)


class LabTestVocabulary(Protocol):
    def lab_tests(self, concept_ids: Iterable[int]) -> dict[int, LabTest]:
        """The LOINC lab tests among ``concept_ids``; any other concept is absent."""

    def analyte_lab_tests(self, analyte: str) -> list[LabTest]:
        """Standard, valid LOINC lab tests whose component is ``analyte`` or a challenge of it."""


@dataclass(frozen=True)
class SpecimenPlan:
    """What :func:`plan_specimen_refinement` decided, and why when it decided nothing."""

    analyte: str | None = None
    removed: tuple[tuple[int, tuple[str, ...]], ...] = ()
    added: tuple[LabTest, ...] = ()
    declined: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.removed or self.added)


# --------------------------------------------------------------------------------------
# The axes
# --------------------------------------------------------------------------------------


def analyte_of(component: str) -> str:
    """The LOINC component without its challenge part: ``"Glucose^post CFst"`` -> ``"Glucose"``."""
    return component.split("^", 1)[0]


def challenge_of(component: str) -> str | None:
    """The challenge part of a LOINC component, or None for a non-challenge test."""
    _, sep, challenge = component.partition("^")
    return challenge if sep else None


def criterion_words(*texts: str | None) -> frozenset[str]:
    """Lower-case alphanumeric words of the criterion's own text."""
    return frozenset(w for text in texts if text for w in _WORD.findall(text.lower()))


def _names(token: str, words: frozenset[str]) -> bool:
    k = min(_NAMING_PREFIX, len(token))
    return any(len(word) >= k and word[:k] == token[:k] for word in words)


def system_allowed(system: str | None, words: frozenset[str]) -> bool:
    """Whether a lab test in ``system`` measures the specimen the criterion means.

    A serum, plasma or whole-blood system always qualifies; any other token of the system name
    must be named by the criterion's words, so "Urine" stands under "Urinary albumin creatinine
    ratio" and a combined "Urine and Serum or Plasma" needs the urine named too.
    """
    tokens = [t for t in _WORD.findall((system or "").lower()) if t not in _SYSTEM_CONNECTIVES]
    return bool(tokens) and all(
        t in CIRCULATING_BLOOD_SYSTEM_WORDS or _names(t, words) for t in tokens
    )


def unit_properties(ucum_code: str | None) -> frozenset[str]:
    """Every LOINC property a UCUM unit can be a measure of; empty when the grammar does not say.

    ``"mg/dL"`` -> {Mass Concentration}, ``"kg/m2"`` -> {Ratio}, ``"%"`` -> the non-decimal
    fraction properties, ``"mmol/mol"`` -> {Substance Fraction, Substance Ratio}. A quotient of
    two masses (``"mg/g"``) stays empty: LOINC files urine albumin/creatinine under both 'Mass
    Ratio' and 'Ratio' (see above), so the unit cannot choose.
    """
    if not ucum_code:
        return frozenset()
    if ucum_code in _PROPERTY_FAMILIES_BY_ATOM:
        return _PROPERTY_FAMILIES_BY_ATOM[ucum_code]
    atoms = ucum_code.split("/")
    if len(atoms) < 2:
        return frozenset()
    dimensions = []
    for atom in atoms:
        dimension = next((d for pattern, d in _UNIT_DIMENSION if pattern.match(atom)), None)
        if dimension is None:
            return frozenset()
        dimensions.append(dimension)
    single = _PROPERTY_BY_DIMENSIONS.get(tuple(dimensions))
    if single:
        return frozenset({single})
    return _PROPERTY_FAMILIES_BY_DIMENSIONS.get(tuple(dimensions), frozenset())


def unit_property(ucum_code: str | None) -> str | None:
    """The ONE LOINC property a UCUM unit is a measure of, or None when it names none or several.

    The specimen step and check (u) read this: they compare each lab test to a single property,
    so a unit naming a family (``"%"``) constrains nothing there, as before. Only
    :func:`verify_members_against_unit` resolves a family, against the set's own members.
    """
    family = unit_properties(ucum_code)
    return next(iter(family)) if len(family) == 1 else None


@dataclass(frozen=True)
class UnitVerification:
    """Which members of a concept set are verified to be measured in a stated unit."""

    property: str | None = None
    kept: tuple[int, ...] = ()
    removed: tuple[tuple[int, str], ...] = ()
    declined: str | None = None


def verify_members_against_unit(
    member_ids: Sequence[int],
    member_properties: Mapping[int, str | None],
    ucum_code: str | None,
) -> UnitVerification:
    """Keep only the members whose LOINC property is the one the stated unit measures.

    The property is the member of :func:`unit_properties` held by a strict majority of the
    members whose property is in that family -- '%' over HbA1c resolves to 'Mass fraction', so
    an IFCC 'Substance Fraction' code is dropped with the 'Mass Concentration' one. A member with
    no LOINC property (a SNOMED procedure) cannot be verified and is dropped. Declines, keeping
    nothing, when the criterion states no unit, the unit names no property, or no property
    holds a majority.

    :param member_ids: the set's non-excluded concept ids, in order.
    :param member_properties: concept id -> LOINC property name; a non-LOINC id is absent.
    :param ucum_code: the CONCEPT_CODE of the unit the criterion stated.
    """
    if not ucum_code:
        return UnitVerification(
            declined="the criterion states no unit, so no member's property can be verified"
        )
    family = unit_properties(ucum_code)
    if not family:
        return UnitVerification(declined=f"the stated unit {ucum_code!r} names no LOINC property")
    ids = list(dict.fromkeys(int(i) for i in member_ids))
    in_family = [member_properties.get(i) for i in ids if member_properties.get(i) in family]
    if not in_family:
        return UnitVerification(
            declined=f"no member carries a LOINC property the unit {ucum_code!r} names"
        )
    resolved, count = Counter(in_family).most_common(1)[0]
    if count * 2 <= len(in_family):
        return UnitVerification(
            declined=f"no property majority for {ucum_code!r}: {dict(Counter(in_family))}"
        )
    removed = []
    for cid in ids:
        prop = member_properties.get(cid)
        if prop is None:
            removed.append((cid, "not a LOINC concept with a property, so it cannot be verified"))
        elif prop != resolved:
            removed.append((cid, f"property {prop!r} is not the unit's {resolved!r}"))
    kept = tuple(cid for cid in ids if member_properties.get(cid) == resolved)
    return UnitVerification(property=resolved, kept=kept, removed=tuple(removed))


def value_filter_unit_property(criteria_attributes: Mapping[str, Any]) -> str | None:
    """The property implied by a Circe Measurement's ``Unit`` -- its first, standard, entry."""
    units = criteria_attributes.get("Unit") or []
    first = units[0] if units and isinstance(units[0], Mapping) else {}
    return unit_property(first.get("CONCEPT_CODE"))


def challenge_stated(challenge: str, description_words: frozenset[str]) -> bool:
    """Whether the criterion's description states the condition a challenge test is taken under.

    Every token of the challenge must be either timing ("post", "12H") or a condition the
    description names. "post CFst" stands under "after overnight fast"; "2H post 75 g glucose
    PO" does not, because nothing stated the glucose load.
    """
    stated = {
        token
        for prefix, token in _STATED_CHALLENGES.items()
        if any(word.startswith(prefix) for word in description_words)
    }
    residual = [t for t in challenge.lower().split() if not _CHALLENGE_TIMING.match(t)]
    return bool(residual) and all(t in stated for t in residual)


# --------------------------------------------------------------------------------------
# The decisions
# --------------------------------------------------------------------------------------


def _member_violations(
    test: LabTest, words: frozenset[str], unit_prop: str | None
) -> tuple[str, ...]:
    reasons = []
    if not system_allowed(test.system, words):
        reasons.append(f"system {test.system!r} is not one the criterion names")
    if unit_prop and test.property != unit_prop:
        reasons.append(f"property {test.property!r} contradicts the unit's {unit_prop!r}")
    return tuple(reasons)


#: The Circe keys that carry a numeric bound -- the ones ``build_measurement_value_filter`` emits.
NUMERIC_BOUND_ATTRIBUTES = frozenset({"ValueAsNumber", "RangeHighRatio", "RangeLowRatio"})


def carries_numeric_bound(criteria_attributes: Mapping[str, Any]) -> bool:
    """Whether a Circe Measurement (or the value filter about to become one) bounds the result."""
    return any(key in criteria_attributes for key in NUMERIC_BOUND_ATTRIBUTES)


@dataclass(frozen=True)
class SpecimenVerdict:
    """What the gate reports for one criterion: the offending lab tests and the builder's answer.

    ``severity`` is FAIL when the builder would repair the set and WARN when it declines -- the
    decline being the same :func:`plan_specimen_refinement` call the builder makes, so the gate
    cannot call repairable a set the builder leaves alone, or the reverse.
    """

    violations: tuple[tuple[LabTest, tuple[str, ...]], ...] = ()
    declined: str | None = None

    @property
    def severity(self) -> str | None:
        if not self.violations:
            return None
        return "WARN" if self.declined else "FAIL"


def specimen_verdict(
    *,
    member_ids: Sequence[int],
    lab_tests: Mapping[int, LabTest],
    words: frozenset[str],
    description_words: frozenset[str],
    unit_prop: str | None,
    numeric_bound: bool,
    analyte_lab_tests: Callable[[str], Sequence[LabTest]],
) -> SpecimenVerdict:
    """The lab tests a criterion holds in a specimen or property it did not state, and whether
    the builder would repair them. Takes exactly :func:`plan_specimen_refinement`'s arguments.

    A set with no LOINC lab test has nothing this rule reads and returns no violation at all.
    """
    lab = [lab_tests[cid] for cid in dict.fromkeys(member_ids) if cid in lab_tests]
    violations = tuple((t, r) for t in lab if (r := _member_violations(t, words, unit_prop)))
    if not violations:
        return SpecimenVerdict()
    plan = plan_specimen_refinement(
        member_ids=member_ids,
        lab_tests=lab_tests,
        words=words,
        description_words=description_words,
        unit_prop=unit_prop,
        numeric_bound=numeric_bound,
        analyte_lab_tests=analyte_lab_tests,
    )
    return SpecimenVerdict(violations=violations, declined=plan.declined)


def plan_specimen_refinement(
    *,
    member_ids: Sequence[int],
    lab_tests: Mapping[int, LabTest],
    words: frozenset[str],
    description_words: frozenset[str],
    unit_prop: str | None,
    numeric_bound: bool,
    analyte_lab_tests: Callable[[str], Sequence[LabTest]],
) -> SpecimenPlan:
    """Decide which LOINC lab tests to drop from a criterion's concept set and which to add.

    1. The analyte is the component (challenge stripped) held by a strict majority of the lab
       tests in an acceptable specimen -- those whose property matches the unit when any do.
       No majority: decline, set unchanged.
    2. Drop a lab test in a specimen the criterion did not name, one whose property contradicts
       the unit, and a challenge variant of the analyte whose challenge the description does
       not state.
    3. Only when the criterion carries a numeric bound: add every standard, point-in-time,
       quantitative lab test of the analyte in an acceptable specimen, in the unit's property
       (or the majority's properties when the unit names none), challenge variants only where
       stated. A bound-less criterion ("Glycaemic control insufficient") states no quantity to
       widen toward, and a timed collection or study summary is not the measurement a
       threshold is written against. Removal (2) does not depend on either.
    4. Decline rather than leave the set without a single lab test: the unit then contradicts
       every member, which is an extraction defect the gate reports, not a specimen choice.

    Non-LOINC members are never touched.
    """
    have = set(member_ids)
    lab = [lab_tests[cid] for cid in dict.fromkeys(member_ids) if cid in lab_tests]
    if not lab:
        return SpecimenPlan(declined="no LOINC lab-test member")
    in_specimen = [t for t in lab if system_allowed(t.system, words)]
    if not in_specimen:
        return SpecimenPlan(
            declined="no LOINC lab-test member in a serum, plasma, blood or named system"
        )
    voters = [t for t in in_specimen if unit_prop is None or t.property == unit_prop] or in_specimen
    votes = Counter(t.analyte for t in voters)
    analyte, count = votes.most_common(1)[0]
    if count * 2 <= len(voters):
        return SpecimenPlan(
            declined=f"no analyte majority among {len(voters)} lab tests: {dict(votes)}"
        )

    removed = []
    for test in lab:
        reasons = list(_member_violations(test, words, unit_prop))
        if (
            test.analyte == analyte
            and test.challenge is not None
            and not challenge_stated(test.challenge, description_words)
        ):
            reasons.append(f"challenge {test.challenge!r} is not stated by the description")
        if reasons:
            removed.append((test.concept_id, tuple(reasons)))

    properties = {unit_prop} if unit_prop else {t.property for t in voters if t.analyte == analyte}
    # The analyte is the component concept the set's own non-challenge members carry; a
    # challenge variant is a different component by definition and is matched by its prefix.
    component_ids = {t.component_id for t in voters if t.analyte == analyte and t.challenge is None}
    added = []
    candidates = analyte_lab_tests(analyte) if numeric_bound else []
    for test in sorted(candidates, key=lambda t: t.concept_id):
        if test.concept_id in have or test.analyte != analyte:
            continue
        if test.challenge is None and component_ids and test.component_id not in component_ids:
            continue
        if test.domain_id != MEASUREMENT_DOMAIN or not system_allowed(test.system, words):
            continue
        if test.scale != QUANTITATIVE_SCALE or test.time_aspect != POINT_IN_TIME:
            continue
        if test.property not in properties:
            continue
        if test.challenge is not None and not challenge_stated(test.challenge, description_words):
            continue
        have.add(test.concept_id)
        added.append(test)

    if len(removed) == len(lab) and not added:
        if unit_prop and all(any("contradicts" in r for r in rs) for _, rs in removed):
            why = (
                f"the unit's property {unit_prop!r} contradicts every LOINC lab test in the set "
                f"and the vocabulary offers no {analyte!r} test in it, so the extracted unit is "
                f"the suspect"
            )
        else:
            why = (
                f"refinement would leave no LOINC lab-test member ({len(removed)} removed, none "
                f"added{'' if numeric_bound else ': no additions without a numeric bound'})"
            )
        return SpecimenPlan(analyte=analyte, declined=why)
    return SpecimenPlan(analyte=analyte, removed=tuple(removed), added=tuple(added))


def claims_lab_test(item: Mapping[str, Any]) -> bool:
    """Whether a Circe item's own concept metadata says it is a LOINC lab test."""
    concept = item.get("concept") or {}
    return (
        concept.get("VOCABULARY_ID") == LOINC_VOCABULARY
        and concept.get("CONCEPT_CLASS_ID") == LAB_TEST_CLASS
    )


def _circe_item(test: LabTest) -> dict[str, Any]:
    return {
        "concept": {
            "CONCEPT_ID": test.concept_id,
            "CONCEPT_NAME": test.concept_name,
            "DOMAIN_ID": test.domain_id,
            "VOCABULARY_ID": LOINC_VOCABULARY,
            "CONCEPT_CLASS_ID": LAB_TEST_CLASS,
            "STANDARD_CONCEPT": "S",
            "STANDARD_CONCEPT_CAPTION": "Standard",
            "CONCEPT_CODE": test.concept_code,
            "INVALID_REASON": None,
            "INVALID_REASON_CAPTION": None,
        },
        "includeDescendants": False,
        "includeMapped": False,
        "isExcluded": False,
    }


def refine_measurement_concept_set(
    expression: Mapping[str, Any],
    *,
    seed: str,
    description: str | None,
    value_filter: Mapping[str, Any],
    vocabulary: LabTestVocabulary,
) -> tuple[dict[str, Any], SpecimenPlan]:
    """Apply :func:`plan_specimen_refinement` to a Circe concept-set expression.

    ``value_filter`` is the fragment the criterion emits (``build_measurement_value_filter``):
    its ``Unit`` sets the property, and its presence means the criterion carries a bound.
    Returns a new expression; the input is not modified. The vocabulary is consulted only when
    an item's own metadata claims a LOINC lab test.
    """
    items = list(expression.get("items") or [])
    if not any(claims_lab_test(i) and not i.get("isExcluded") for i in items):
        return dict(expression), SpecimenPlan(declined="no LOINC lab-test member")
    member_ids = [int(i["concept"]["CONCEPT_ID"]) for i in items if not i.get("isExcluded")]
    claimed = [
        int(i["concept"]["CONCEPT_ID"])
        for i in items
        if claims_lab_test(i) and not i.get("isExcluded")
    ]
    plan = plan_specimen_refinement(
        member_ids=member_ids,
        lab_tests=vocabulary.lab_tests(claimed),
        words=criterion_words(seed, description),
        description_words=criterion_words(description),
        unit_prop=value_filter_unit_property(value_filter),
        numeric_bound=carries_numeric_bound(value_filter),
        analyte_lab_tests=vocabulary.analyte_lab_tests,
    )
    if not plan.changed:
        return dict(expression), plan
    all_ids = {int(i["concept"]["CONCEPT_ID"]) for i in items}
    removed = {cid for cid, _ in plan.removed}
    kept = [
        deepcopy(i)
        for i in items
        if i.get("isExcluded") or int(i["concept"]["CONCEPT_ID"]) not in removed
    ]
    added = [_circe_item(t) for t in plan.added if t.concept_id not in all_ids]
    return {**expression, "items": kept + added}, plan


# --------------------------------------------------------------------------------------
# The vocabulary
# --------------------------------------------------------------------------------------

_AXES_SQL = """
SELECT c.concept_id, c.concept_name, c.concept_code, c.domain_id,
       MAX(CASE WHEN r.relationship_id = 'Has component' THEN x.concept_name END),
       MAX(CASE WHEN r.relationship_id = 'Has component' THEN x.concept_id END),
       MAX(CASE WHEN r.relationship_id = 'Has system' THEN x.concept_name END),
       MAX(CASE WHEN r.relationship_id = 'Has property' THEN x.concept_name END),
       MAX(CASE WHEN r.relationship_id = 'Has scale type' THEN x.concept_name END),
       MAX(CASE WHEN r.relationship_id = 'Has time aspect' THEN x.concept_name END)
  FROM {schema}.concept c
  JOIN {schema}.concept_relationship r
    ON r.concept_id_1 = c.concept_id AND r.invalid_reason IS NULL
   AND r.relationship_id IN (
       'Has component', 'Has system', 'Has property', 'Has scale type', 'Has time aspect'
   )
  JOIN {schema}.concept x ON x.concept_id = r.concept_id_2
 WHERE c.concept_id = ANY(%s)
   AND c.vocabulary_id = 'LOINC' AND c.concept_class_id = 'Lab Test'
 GROUP BY 1, 2, 3, 4
"""

_ANALYTE_SQL = """
SELECT DISTINCT c.concept_id
  FROM {schema}.concept_relationship r
  JOIN {schema}.concept c ON c.concept_id = r.concept_id_1
  JOIN {schema}.concept x ON x.concept_id = r.concept_id_2
 WHERE r.relationship_id = 'Has component' AND r.invalid_reason IS NULL
   AND x.vocabulary_id = 'LOINC' AND x.concept_class_id = 'LOINC Component'
   AND (x.concept_name = %s OR x.concept_name LIKE %s)
   AND c.vocabulary_id = 'LOINC' AND c.concept_class_id = 'Lab Test'
   AND c.standard_concept = 'S' AND c.invalid_reason IS NULL
"""


_PROPERTY_SQL = """
SELECT c.concept_id, MAX(x.concept_name)
  FROM {schema}.concept c
  JOIN {schema}.concept_relationship r
    ON r.concept_id_1 = c.concept_id AND r.invalid_reason IS NULL
   AND r.relationship_id = 'Has property'
  JOIN {schema}.concept x ON x.concept_id = r.concept_id_2
 WHERE c.concept_id = ANY(%s) AND c.vocabulary_id = 'LOINC'
 GROUP BY 1
"""


_COMPONENT_SQL = """
SELECT c.concept_id, x.concept_id
  FROM {schema}.concept c
  JOIN {schema}.concept_relationship r
    ON r.concept_id_1 = c.concept_id AND r.invalid_reason IS NULL
   AND r.relationship_id = 'Has component'
  JOIN {schema}.concept x ON x.concept_id = r.concept_id_2 AND x.vocabulary_id = 'LOINC'
 WHERE c.concept_id = ANY(%s) AND c.vocabulary_id = 'LOINC'
"""


def _like_prefix(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "^%"


class PostgresLabTestVocabulary:
    """:class:`LabTestVocabulary` over an OMOP vocabulary schema. The only I/O in this module."""

    def __init__(self, dsn: str, schema: str) -> None:
        import psycopg2  # noqa: PLC0415 -- lazy, so importing the module needs no driver

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError(f"not a schema name: {schema!r}")
        self._schema = schema
        self._conn = psycopg2.connect(dsn)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PostgresLabTestVocabulary:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def lab_tests(self, concept_ids: Iterable[int]) -> dict[int, LabTest]:
        ids = sorted({int(c) for c in concept_ids})
        if not ids:
            return {}
        with self._conn.cursor() as cur:
            cur.execute(_AXES_SQL.format(schema=self._schema), (ids,))
            rows = cur.fetchall()
        return {
            row[0]: LabTest(
                concept_id=row[0],
                concept_name=row[1],
                concept_code=row[2] or "",
                domain_id=row[3],
                component=row[4] or "",
                component_id=row[5],
                system=row[6],
                property=row[7],
                scale=row[8],
                time_aspect=row[9],
            )
            for row in rows
        }

    def properties(self, concept_ids: Iterable[int]) -> dict[int, str]:
        """LOINC ``Has property`` name per concept, any concept class; a non-LOINC id is absent."""
        ids = sorted({int(c) for c in concept_ids})
        if not ids:
            return {}
        with self._conn.cursor() as cur:
            cur.execute(_PROPERTY_SQL.format(schema=self._schema), (ids,))
            return {row[0]: row[1] for row in cur.fetchall() if row[1] is not None}

    def components(self, concept_ids: Iterable[int]) -> dict[int, set[int]]:
        """LOINC ``Has component`` concept ids per concept, any LOINC concept class.

        What a member of a concept set measures, read off the vocabulary; a non-LOINC id is
        absent. ``circe_lint.iter_confusable_members`` compares these, never names.
        """
        ids = sorted({int(c) for c in concept_ids})
        if not ids:
            return {}
        with self._conn.cursor() as cur:
            cur.execute(_COMPONENT_SQL.format(schema=self._schema), (ids,))
            found: dict[int, set[int]] = {}
            for concept_id, component_id in cur.fetchall():
                found.setdefault(concept_id, set()).add(component_id)
            return found

    def analyte_lab_tests(self, analyte: str) -> list[LabTest]:
        with self._conn.cursor() as cur:
            cur.execute(_ANALYTE_SQL.format(schema=self._schema), (analyte, _like_prefix(analyte)))
            ids = [row[0] for row in cur.fetchall()]
        return list(self.lab_tests(ids).values())
