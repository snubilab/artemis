"""SPEC-INFRA-003 REQ-001 / REQ-007: collapse restated demographics to one criterion.

`restated_clusters.py` supplies the *measurement* (REQ-005) and deliberately stops
there. This module supplies a fix for one shape, and it is a separate signal rather
than an extension of that one because the stem test cannot reach the shape that needs
fixing most: EMPA-REG's pair shares no description stem, which `spec.md` §2.5.2 records
as the stem signal's one known false negative.

**The signal: restated-demographics collapse.** Within one study and one role, among
top-level criteria satisfying all four structural gates

1. ``domain == "Demographics"``, **and**
2. ``valueConstraint is None``, **and**
3. ``groupId is None``, **and**
4. ``isGroupLabel`` falsy

-- if two or more such criteria exist, they collapse to exactly one survivor: the first
in document order. No scoring, no tie-break, no sort.

**Why this is a cardinality invariant rather than a similarity match.** It never
compares two descriptions to each other. A Demographics criterion carrying no numeric
constraint has no attribute for two different facts to bind to, so two of them in the
same (study, role) are restating one fact *by construction* -- however differently they
happen to be worded. That is precisely what lets it reach EMPA-REG {27, 28}, whose two
descriptions (`Pre-menopausal women criteria` / `Pre-menopausal women
contraception/pregnancy status`) have nothing lexical in common.

`plan.md` §G forbids deduping on description similarity, and this obeys that: there is
no threshold, no edit distance, no embedding, and no criterion-id or study-id special
case. Gate 2 remains the load-bearing one. CARMELINA's ALT/AST/AP triple differs only
by an `(AST)` / `(AP)` suffix -- the same surface shape as the `(<= 1 year)` /
`(General)` suffixes that ARE duplicates -- and gate 2 excludes it without judgment
because each analyte carries `{op: gte, value: 3.0, unitText: "x ULN"}` bound to a
different named entity (`spec.md` §2.3.3). Gate 1 excludes the same triple a second
time over, since its domain is Measurement.

Gates 3 and 4 keep the signal off criteria that are already somebody else's business:
a grouped criterion is governed by its group's semantics (and, for all-ABSENCE groups,
by REQ-004), and a declared heading states no condition of its own.

**Verified against the live reference store**
(`tmp/tte_six_20260823_patternG_v2/studies.json`, 10 studies / 506 criteria): exactly
three (study, role) groups reach n >= 2 -- CARMELINA exclusion {11, 12, 18}, CAROLINA
exclusion {21, 53}, and EMPA-REG exclusion {27, 28}, which are precisely the three
clusters `spec.md` §2.1 enumerates as fix scope. Every other group in the gated class
is a singleton, so the signal fires nowhere else in the corpus.

**Survivor selection is document order, and for EMPA-REG that is contested.** For the
two pure-restatement groups the choice is immaterial or actively right: CAROLINA's pair
is byte-identical, and CARMELINA's first member is the unsuffixed one AC-001 wants kept.
EMPA-REG is the exception -- `spec.md` §2.4 reads id 27 as the protocol *heading* and
id 28 as already-merged content, which argues for keeping id 28, the opposite of what
document order picks. That reading rests on ASSUMPTION-1, which `spec.md` §2.4 records
as assumed rather than established and `plan.md` M2 leaves open. No structural signal
can see that id 27 is a heading, because the extraction failed to label it as one --
gate 4 sees `isGroupLabel: false`. Resolving it needs the SPEC-level decision M2 carries,
so the survivor rule is recorded on every emitted record rather than being silently
assumed correct.
"""
from __future__ import annotations

from typing import Any

#: `spec.md` §2.1 -- every affected criterion carries this domain.
_DEMOGRAPHICS = "Demographics"

#: Recorded on each dropped criterion via `_record_skip`, and on each collapse record.
COLLAPSE_REASON = "restated-demographics-duplicate"

#: Named on every record so the contested EMPA-REG choice is visible in the artifact
#: rather than implicit in the iteration order.
SURVIVOR_RULE = "first-in-document-order"


def is_restatable_demographic(criterion: dict[str, Any]) -> bool:
    """Return whether a criterion satisfies all four structural gates.

    The four gates are conjunctive and none is redundant: gate 1 scopes the signal to
    the domain `spec.md` §2.1 confirms the defect in, gate 2 excludes any criterion
    carrying an attribute two distinct facts could bind to, and gates 3 and 4 exclude
    criteria already governed by a group or declared as a heading.

    Args:
        criterion: A top-level IR criterion. Absent keys are treated as null/false,
            so a criterion built before a field existed is not mistaken for one that
            explicitly carries it.

    Returns:
        True when the criterion is eligible to participate in a collapse.
    """
    return (
        (criterion.get("domain") or "").strip() == _DEMOGRAPHICS
        and criterion.get("valueConstraint") is None
        and criterion.get("groupId") is None
        and not criterion.get("isGroupLabel")
    )


def collapse_restated_demographics(
    criteria: list[dict[str, Any]],
    *,
    role: str,
) -> tuple[set[tuple[str, str]], list[dict[str, Any]]]:
    """Collapse one role's restated demographics to a single survivor.

    Args:
        criteria: Top-level criteria for a single role of a single study, in document
            order. Order is load-bearing -- the survivor is the first eligible member.
        role: "inclusion" or "exclusion". Recorded on the collapse record and used in
            the drop keys; a collapse never spans roles, so one criterion in each role
            is two singletons rather than a pair.

    Returns:
        A `(drop_keys, records)` pair. `drop_keys` holds `(role, criterion id as str)`
        for every criterion to drop, keyed to match `_record_skip`'s string ids.
        `records` holds at most one dict describing the collapse, or none when fewer
        than two eligible criteria are present.
    """
    eligible = [c for c in criteria or [] if is_restatable_demographic(c)]
    # One eligible criterion is not a duplication, and zero is not either. Both are
    # reported as the same nothing, which is correct here -- unlike the stability
    # measurement in `restated_clusters.cluster_key`, this signal only ever acts on a
    # surplus.
    if len(eligible) < 2:
        return set(), []

    survivor, *dropped = eligible
    drop_keys = {(role, str(c.get("id", ""))) for c in dropped}
    record = {
        "role": role,
        "domain": _DEMOGRAPHICS,
        "survivorId": survivor.get("id"),
        "droppedIds": [c.get("id") for c in dropped],
        "survivorRule": SURVIVOR_RULE,
        "reason": COLLAPSE_REASON,
    }
    return drop_keys, [record]


def collapse_all_restated_demographics(
    *,
    inclusion_criteria: list[dict[str, Any]],
    exclusion_criteria: list[dict[str, Any]],
) -> tuple[set[tuple[str, str]], list[dict[str, Any]]]:
    """Collapse restated demographics across both roles of one study.

    Args:
        inclusion_criteria: The study's top-level inclusion criteria, in document order.
        exclusion_criteria: The study's top-level exclusion criteria, in document order.

    Returns:
        A `(drop_keys, records)` pair merging both roles, with inclusion-role records
        first. Roles are collapsed independently.
    """
    inc_keys, inc_records = collapse_restated_demographics(inclusion_criteria, role="inclusion")
    exc_keys, exc_records = collapse_restated_demographics(exclusion_criteria, role="exclusion")
    return inc_keys | exc_keys, inc_records + exc_records
