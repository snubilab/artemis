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

Everything structural is read off the LOINC axes in the vocabulary (``Has component``, ``Has
system``, ``Has property``, ``Has scale type``, ``Has time aspect``). No concept id, analyte name
or trial appears in the logic, and no text is read to decide meaning (RFC-016 step 4, A17 + C3):

* Which specimen and which challenge the criterion means is NOT a vocabulary fact. The 1,045
  ``Is a`` edges among ``LOINC System`` concepts are radiology anatomy only, and the one other
  structural path -- a lab test's ``Is a`` SNOMED procedure, its ``Has specimen``, and the
  SNOMED specimen hierarchy -- reaches 30 of the 196 LOINC lab tests in the 2026-10-12 candidate
  store's concept sets, and files ``Red Blood Cells`` and ``DBS`` under blood. So it is judged:
  a :data:`SpecimenJudge` is handed the analyte and the (System, challenge) options of the set's
  members and candidates and answers which ones the criterion states. The builder's judge is the
  specimen critic (``src.agents.agent2.specimen_critic``), told the annotation's ``specimen``
  field and the protocol line; the gate's judge is that decision as the builder recorded it
  (:func:`recorded_judge`).
* :data:`_UNIT_DIMENSION` / :data:`_PROPERTY_BY_DIMENSIONS`. OMOP holds no edge from a UCUM unit
  to a LOINC property, so the property is derived from the UCUM code's grammar: the dimension of
  each '/'-separated atom (mass, substance, catalytic, count, volume, time, area). Unit ids are
  never consulted. Only concentrations and volume rates are named; see the table for why ratios
  are not.

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
PERCENT_FRACTION_PROPERTIES = frozenset(
    {
        "Mass fraction",
        "Substance Fraction",
        "Volume Fraction",
        "Number Fraction",
        "Arbitrary fraction",
        "Catalytic Fraction",
        "Length fraction",
        "Saturation Fraction",
        "Area Fraction",
        "Time Fraction",
        "Circumference Fraction",
    }
)
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
    #: The ``Has system`` concept.
    system_id: int | None = None

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
class SpecimenOption:
    """The specimen a LOINC lab test is performed on, and the challenge it is taken under.

    :param system_id: the ``Has system`` concept, None when the row did not carry it.
    :param system: that concept's name -- shown to the judge, never read by code.
    :param challenge: the component's part after '^' (LOINC's own syntax), None for none.
    """

    system_id: int | None
    system: str | None
    challenge: str | None

    @property
    def key(self) -> tuple[int | None, str | None, str | None]:
        return (self.system_id, self.system, self.challenge)


def option_of(test: LabTest) -> SpecimenOption:
    """The (System, challenge) option a lab test is one instance of."""
    return SpecimenOption(test.system_id, test.system, test.challenge)


#: ``(analyte, options) -> accepted option keys``, or None when no judgement could be made.
#: The builder's judge is the specimen critic; the gate's is :func:`recorded_judge`.
SpecimenJudge = Callable[
    [str, Sequence[SpecimenOption]], "frozenset[tuple[int | None, str | None, str | None]] | None"
]


def recorded_judge(accepted: Iterable[Mapping[str, Any]] | None) -> SpecimenJudge:
    """A judge that answers with a decision recorded earlier, whatever it is offered.

    :param accepted: the ``accepted`` options of a builder record (``systemId``, ``system``,
        ``challenge``); None when no decision was recorded, which judges nothing.
    """
    if accepted is None:
        return lambda _analyte, _options: None
    keys = frozenset(
        (entry.get("systemId"), entry.get("system"), entry.get("challenge"))
        for entry in accepted
        if isinstance(entry, Mapping)
    )
    return lambda _analyte, _options: keys


@dataclass(frozen=True)
class SpecimenPlan:
    """What :func:`plan_specimen_refinement` decided, and why when it decided nothing.

    ``violations`` are the lab-test members the plan finds wrong whether or not it acts;
    ``removed`` is what it acts on (empty when it declines). ``judged`` is None when the judge
    was not asked (no LOINC lab test), False when it gave no answer -- the specimen was then
    not decided and only the unit's property removed anything -- and True when it answered.
    """

    analyte: str | None = None
    removed: tuple[tuple[int, tuple[str, ...]], ...] = ()
    added: tuple[LabTest, ...] = ()
    declined: str | None = None
    violations: tuple[tuple[int, tuple[str, ...]], ...] = ()
    judged: bool | None = None
    accepted: tuple[SpecimenOption, ...] = ()
    #: The stated unit's LOINC property is no lab-test member's: the unit and the set name
    #: different quantities, so the criterion cannot be emitted as either.
    unit_contradicts_every_member: bool = False

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


# --------------------------------------------------------------------------------------
# The decisions
# --------------------------------------------------------------------------------------


def _member_violations(
    test: LabTest,
    accepted: frozenset[tuple[int | None, str | None, str | None]] | None,
    unit_prop: str | None,
) -> tuple[str, ...]:
    reasons = []
    if accepted is not None and option_of(test).key not in accepted:
        challenge = f" under {test.challenge!r}" if test.challenge else ""
        reasons.append(f"specimen {test.system!r}{challenge} is not one the criterion states")
    if unit_prop and test.property != unit_prop:
        reasons.append(f"property {test.property!r} contradicts the unit's {unit_prop!r}")
    return tuple(reasons)


def _parts_of_other_members(
    lab: Sequence[LabTest], component_ancestors: Mapping[int, frozenset[int]]
) -> dict[int, str]:
    """Members whose LOINC Component ``Is a`` descendant of another member's component.

    Such a member measures a part of that member's quantity -- 'Aspartate aminotransferase.
    macromolecular/total' under 'Aspartate aminotransferase', the bone, heat-stable and other
    fractions under 'Alkaline phosphatase' -- so a bound written on the quantity does not read
    it. Unrelated components (Troponin I and Troponin T in one "I or T" criterion) are each
    their own quantity and are kept. The hierarchy is the vocabulary's; no name is read.

    :returns: member concept id -> the reason.
    """
    held = {t.component_id: t.component for t in lab if t.component_id is not None}
    found: dict[int, str] = {}
    for test in lab:
        above = (component_ancestors.get(test.component_id) or frozenset()) & held.keys()
        above.discard(test.component_id)
        if above:
            whole = held[min(above)]
            found[test.concept_id] = (
                f"component {test.component!r} is a part of {whole!r}, which the set also holds"
            )
    return found


def _with_unbounded_members(
    violations: tuple[tuple[int, tuple[str, ...]], ...],
    lab: Sequence[LabTest],
    parts: Mapping[int, str],
) -> tuple[tuple[int, tuple[str, ...]], ...]:
    """``violations`` plus the members a numeric bound cannot be compared against.

    A non-quantitative scale (an Ord '[Presence]' result has no number), as `_candidates`
    already requires of an addition, and a member measuring a part of another member's quantity
    (:func:`_parts_of_other_members`). P7 EMPA-REG's "AST > 3x ULN" carried both. The time axis
    stays additions-only: a 24-hour UACR the mapper chose is still a ratio a bound reads
    (``test_loinc_specimen::TestTimeAspect``).
    """
    by_id = {cid: list(reasons) for cid, reasons in violations}
    for test in lab:
        reasons = []
        if test.scale != QUANTITATIVE_SCALE:
            reasons.append(f"scale {test.scale!r} cannot carry the criterion's number")
        if test.concept_id in parts:
            reasons.append(parts[test.concept_id])
        if reasons:
            by_id.setdefault(test.concept_id, []).extend(reasons)
    return tuple((t.concept_id, tuple(by_id[t.concept_id])) for t in lab if t.concept_id in by_id)


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
    unit_contradicts_every_member: bool = False

    @property
    def severity(self) -> str | None:
        if not self.violations:
            return None
        # The builder refuses such a criterion, so one that was delivered is a defect, not a
        # decline to respect.
        if self.unit_contradicts_every_member:
            return "FAIL"
        return "WARN" if self.declined else "FAIL"


def specimen_verdict(
    *,
    member_ids: Sequence[int],
    lab_tests: Mapping[int, LabTest],
    unit_prop: str | None,
    numeric_bound: bool,
    analyte_lab_tests: Callable[[str], Sequence[LabTest]],
    judge: SpecimenJudge,
    component_ancestors: Mapping[int, frozenset[int]] | None = None,
) -> SpecimenVerdict:
    """The lab tests a criterion holds in a specimen or property it did not state, and whether
    the builder would repair them. Takes exactly :func:`plan_specimen_refinement`'s arguments.

    A set with no LOINC lab test has nothing this rule reads and returns no violation at all.
    """
    plan = plan_specimen_refinement(
        member_ids=member_ids,
        lab_tests=lab_tests,
        unit_prop=unit_prop,
        numeric_bound=numeric_bound,
        analyte_lab_tests=analyte_lab_tests,
        judge=judge,
        component_ancestors=component_ancestors,
    )
    violations = tuple((lab_tests[cid], reasons) for cid, reasons in plan.violations)
    return SpecimenVerdict(
        violations=violations,
        declined=plan.declined if violations else None,
        unit_contradicts_every_member=plan.unit_contradicts_every_member,
    )


def offered(test: LabTest) -> bool:
    """Whether the judge may be shown ``test``'s option.

    A LOINC challenge (the component's part after '^') is a test condition: a state the patient
    is in, or a substance given, before the sample is taken. No criterion field states a test
    condition, so no challenge variant is offered or added, and a challenge-variant member is
    removed whenever the judge answers. Measured on the 2026-10-12 P3 dry arm A, where they were
    offered: the critic accepted 33 challenge options for CAROLINA exclusion 11 and not the
    routine serum code, 37 for ARISTOTLE exclusion 29 and 48 for LEADER exclusion 9.
    """
    return test.challenge is None


def _candidates(
    analyte: str,
    voters: Sequence[LabTest],
    unit_prop: str | None,
    have: set[int],
    analyte_lab_tests: Callable[[str], Sequence[LabTest]],
) -> list[LabTest]:
    """Standard, point-in-time, quantitative lab tests of ``analyte`` the set could gain.

    In the unit's property, or the voters' properties when the unit names none. The analyte is
    the component concept the set's own non-challenge members carry. No challenge variant is a
    candidate (:func:`offered`).
    """
    properties = {unit_prop} if unit_prop else {t.property for t in voters if t.analyte == analyte}
    component_ids = {t.component_id for t in voters if t.analyte == analyte and t.challenge is None}
    found = []
    for test in sorted(analyte_lab_tests(analyte), key=lambda t: t.concept_id):
        if test.concept_id in have or test.analyte != analyte or not offered(test):
            continue
        if component_ids and test.component_id not in component_ids:
            continue
        if test.domain_id != MEASUREMENT_DOMAIN:
            continue
        if test.scale != QUANTITATIVE_SCALE or test.time_aspect != POINT_IN_TIME:
            continue
        if test.property not in properties:
            continue
        found.append(test)
    return found


def plan_specimen_refinement(
    *,
    member_ids: Sequence[int],
    lab_tests: Mapping[int, LabTest],
    unit_prop: str | None,
    numeric_bound: bool,
    analyte_lab_tests: Callable[[str], Sequence[LabTest]],
    judge: SpecimenJudge,
    component_ancestors: Mapping[int, frozenset[int]] | None = None,
) -> SpecimenPlan:
    """Decide which LOINC lab tests to drop from a criterion's concept set and which to add.

    1. Candidates, only when the criterion carries a numeric bound: for each analyte (component,
       challenge stripped) among the members, every standard, point-in-time, quantitative,
       challenge-free lab test of it in the unit's property (or the members' properties when the
       unit names none). A bound-less criterion states no quantity to widen toward, and a timed
       collection or study summary is not the measurement a threshold is written against.
    2. The judge is shown the members' plurality analyte and every offered (System, challenge)
       option among the members and candidates (:func:`offered`: no challenge variant), once,
       and answers which options the criterion states. Specimen is its decision; code reads no
       System name and no criterion text. An answer naming an option not offered is ignored, so
       a challenge-variant member is not accepted.
    3. The analyte is the one held by a strict majority of the members in an accepted option --
       those whose property matches the unit when any do. No majority: decline, set unchanged.
       No member accepted: decline.
    4. Drop a member whose option was not accepted, or whose property contradicts the unit, or --
       with a numeric bound -- whose scale cannot carry the number or whose component is a part
       of another member's (:func:`_with_unbounded_members`; such a part does not vote in 3);
       add a candidate of the analyte whose option was
       accepted. When the judge gives no answer the
       specimen is not decided: every member votes, only the unit's property removes, and
       nothing is added.
    5. Decline rather than leave the set without a single lab test. When the unit's property is
       no member's, ``unit_contradicts_every_member`` is set: the builder refuses that criterion
       and the gate FAILs a delivered one -- the unit and the set name different quantities.

    A declined plan still carries its ``violations``, so the gate can report them as a WARN.
    Non-LOINC members are never touched.
    """
    have = set(member_ids)
    lab = [lab_tests[cid] for cid in dict.fromkeys(member_ids) if cid in lab_tests]
    if not lab:
        return SpecimenPlan(declined="no LOINC lab-test member")

    # With a bound, a member measuring a part of another member's quantity neither votes nor stays.
    parts = _parts_of_other_members(lab, component_ancestors or {}) if numeric_bound else {}
    measured = [t for t in lab if t.concept_id not in parts] or lab
    in_unit = [t for t in measured if unit_prop is None or t.property == unit_prop] or measured
    candidates: dict[str, list[LabTest]] = {}
    if numeric_bound:
        for analyte in dict.fromkeys(t.analyte for t in in_unit):
            candidates[analyte] = _candidates(analyte, in_unit, unit_prop, have, analyte_lab_tests)
    every_candidate = [t for found in candidates.values() for t in found]
    options = list(
        {option_of(t).key: option_of(t) for t in [*lab, *every_candidate] if offered(t)}.values()
    )
    plurality = Counter(t.analyte for t in in_unit).most_common(1)[0][0]
    accepted = judge(plurality, options)
    judged = accepted is not None
    if judged:
        # A recorded decision answers whatever it is offered; only an offered option counts.
        accepted = frozenset(accepted) & {o.key for o in options}

    violations = tuple(
        (test.concept_id, reasons)
        for test in lab
        if (reasons := _member_violations(test, accepted, unit_prop))
    )
    common = dict(
        violations=violations,
        judged=judged,
        accepted=tuple(o for o in options if judged and o.key in accepted),
    )

    in_specimen = [t for t in measured if not judged or option_of(t).key in accepted]
    if not in_specimen:
        return SpecimenPlan(
            declined="no LOINC lab-test member in a specimen the criterion states", **common
        )
    voters = [t for t in in_specimen if unit_prop is None or t.property == unit_prop] or in_specimen
    votes = Counter(t.analyte for t in voters)
    analyte, count = votes.most_common(1)[0]
    if count * 2 <= len(voters):
        return SpecimenPlan(
            declined=f"no analyte majority among {len(voters)} lab tests: {dict(votes)}", **common
        )

    if numeric_bound:
        violations = _with_unbounded_members(violations, lab, parts)
        common["violations"] = violations
    added = tuple(t for t in candidates.get(analyte, []) if judged and option_of(t).key in accepted)
    if len(violations) == len(lab) and not added:
        if unit_prop and all(t.property != unit_prop for t in lab):
            why = (
                f"the unit's property {unit_prop!r} contradicts every LOINC lab test in the set "
                f"and the vocabulary offers no {analyte!r} test in it"
            )
            return SpecimenPlan(
                analyte=analyte, declined=why, unit_contradicts_every_member=True, **common
            )
        why = (
            f"refinement would leave no LOINC lab-test member ({len(violations)} removed, none "
            f"added{'' if numeric_bound else ': no additions without a numeric bound'})"
        )
        return SpecimenPlan(analyte=analyte, declined=why, **common)
    return SpecimenPlan(analyte=analyte, removed=violations, added=added, **common)


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
    value_filter: Mapping[str, Any],
    vocabulary: LabTestVocabulary,
    judge: SpecimenJudge,
) -> tuple[dict[str, Any], SpecimenPlan]:
    """Apply :func:`plan_specimen_refinement` to a Circe concept-set expression.

    ``value_filter`` is the fragment the criterion emits (``build_measurement_value_filter``):
    its ``Unit`` sets the property, and its presence means the criterion carries a bound.
    ``judge`` decides specimen and challenge (the builder passes the specimen critic).
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
    lab_tests = vocabulary.lab_tests(claimed)
    numeric_bound = carries_numeric_bound(value_filter)
    # Read only for a bound, and only from a vocabulary that offers it (test fakes need not).
    read_ancestors = getattr(vocabulary, "component_ancestors", None)
    plan = plan_specimen_refinement(
        member_ids=member_ids,
        lab_tests=lab_tests,
        unit_prop=value_filter_unit_property(value_filter),
        numeric_bound=numeric_bound,
        analyte_lab_tests=vocabulary.analyte_lab_tests,
        judge=judge,
        component_ancestors=(
            read_ancestors({t.component_id for t in lab_tests.values() if t.component_id})
            if numeric_bound and callable(read_ancestors)
            else None
        ),
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


def decision_record(plan: SpecimenPlan) -> dict[str, Any]:
    """The builder's specimen decision, in the shape gate (u) re-reads with :func:`recorded_judge`.

    The caller adds where it applies (``codesetId``) and what the judge was told.
    """
    return {
        "analyte": plan.analyte,
        "judged": plan.judged,
        "accepted": [
            {"systemId": o.system_id, "system": o.system, "challenge": o.challenge}
            for o in plan.accepted
        ],
        "removed": [[cid, list(reasons)] for cid, reasons in plan.removed],
        "added": [t.concept_id for t in plan.added],
        "declined": plan.declined,
    }


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
       MAX(CASE WHEN r.relationship_id = 'Has time aspect' THEN x.concept_name END),
       MAX(CASE WHEN r.relationship_id = 'Has system' THEN x.concept_id END)
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


#: Every LOINC Component a component ``Is a`` (transitively). LOINC Components are not in
#: ``concept_ancestor``, so the edge is walked; depth is bounded for a malformed cycle.
_COMPONENT_ANCESTOR_SQL = """
WITH RECURSIVE up(start_id, anc_id, depth) AS (
  SELECT c.concept_id, c.concept_id, 0 FROM {schema}.concept c WHERE c.concept_id = ANY(%s)
  UNION
  SELECT up.start_id, r.concept_id_2, up.depth + 1
    FROM up
    JOIN {schema}.concept_relationship r
      ON r.concept_id_1 = up.anc_id AND r.relationship_id = 'Is a' AND r.invalid_reason IS NULL
    JOIN {schema}.concept p
      ON p.concept_id = r.concept_id_2 AND p.vocabulary_id = 'LOINC'
     AND p.concept_class_id = 'LOINC Component'
   WHERE up.depth < 12
)
SELECT start_id, anc_id FROM up WHERE depth > 0
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
                system_id=row[10],
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

    def component_ancestors(self, component_ids: Iterable[int]) -> dict[int, frozenset[int]]:
        """LOINC Component ``Is a`` ancestors per component (``_parts_of_other_members``)."""
        ids = sorted({int(c) for c in component_ids})
        if not ids:
            return {}
        found: dict[int, set[int]] = {}
        with self._conn.cursor() as cur:
            cur.execute(_COMPONENT_ANCESTOR_SQL.format(schema=self._schema), (ids,))
            for start, ancestor in cur.fetchall():
                found.setdefault(int(start), set()).add(int(ancestor))
        return {cid: frozenset(anc) for cid, anc in found.items()}

    def analyte_lab_tests(self, analyte: str) -> list[LabTest]:
        with self._conn.cursor() as cur:
            cur.execute(_ANALYTE_SQL.format(schema=self._schema), (analyte, _like_prefix(analyte)))
            ids = [row[0] for row in cur.fetchall()]
        return list(self.lab_tests(ids).values())
