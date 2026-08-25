"""SPEC-INFRA-004: collapse restated criteria in every domain, gated on a distinctness key.

`SPEC-INFRA-003` fixed restated-cluster duplication for one domain. `restated_demographics.py`
collapses a whole role's constraint-free Demographics criteria to a single survivor, justified
by a cardinality argument that only holds where no criterion carries an attribute two distinct
facts could bind to. The same duplication exists in Condition, Drug, Procedure, Observation,
and Measurement, where that argument does not hold.

This module generalizes the fix **by adding a distinctness key, not by relaxing the domain
gate**. The distinction is the whole content of the SPEC: a naive domain-gate relaxation would
leave `groupId is None` as the only thing standing between the collapse and EMPA-REG's
`Cardiovascular Disease` cluster, and `spec.md` §2.3 records grouping state moving between
regenerations of identical input. The first run that emitted that cluster ungrouped would
silently and permanently delete `Myocardial Infarction` and `Heart Failure`, admitting patients
with a history of either into a trial that excludes them.

**The signal.** Within one (study, role, `domain`, description stem) group of two or more
top-level criteria, partition the members into equivalence classes under

```
key = ( sourceText , valueConstraint , logicType )
```

compared by exact equality on each component, and retain one survivor per class -- the first in
document order. Classes of one are untouched.

**Per class, never per group.** This is the property most easily got wrong, and getting it wrong
re-creates the regression `SPEC-INFRA-003` `AC-004` exists to prevent. EMPA-REG's `Liver disease`
group holds six criteria forming three classes -- the ALT / AST / ALP triple emitted twice. The
correct outcome is six to **three**. Any mechanism that reduces a stem group to a single survivor
yields six to **one** and destroys two real analytes. Partitioning and reducing are different
operations, and only the first one is a fix.

**Three properties make the key safe, and each is load-bearing:**

1. Different `sourceText` means a different class, so a member is never collapsed into one it
   does not match -- and this holds regardless of `groupId`, `groupType`, or `isGroupLabel`
   (REQ-003), which is what `spec.md` §2.3 requires.
2. Different `valueConstraint` means a different class, preserving `SPEC-INFRA-003` `AC-004`
   and keeping subgroup-value variants intact.
3. Per-class partitioning yields three survivors on the liver case rather than one.

It is exact equality throughout: no threshold, no edit distance, no embedding, no synonym table,
and no criterion-id or study-id special case (REQ-006, REQ-010). The cost of that restraint is a
small set of recorded false negatives -- CAROLINA `Participation in another trial` {22,59}, whose
members read `Investigational drug` and `Investigational Medicinal/Medical Product`, and
EMPA-REG `eGFR` {41,42}, whose constraints differ only in `unitConceptId`. Both are reported
rather than engineered around (REQ-011), because a genuine duplicate the signal cannot reach must
be visible in the artifact rather than silently absent.

**Disjointness from the Demographics path is by construction, not by coincidence** (REQ-013).
The generalized path considers a criterion only where `is_restatable_demographic` returns false.
The two eligible sets are then complementary by definition, so no criterion is ever seen by both
paths under any `sourceText` state. Gating on the predicate rather than on `domain !=
"Demographics"` matters: CAROLINA inclusion `Age >= 70 years` {4,33} is Demographics *and*
carries a non-null `valueConstraint`, so the Demographics path rejects it on gate 2 -- under a
domain gate that genuine duplicate would be collapsed by neither path.
"""
from __future__ import annotations

import json
from typing import Any

from src.services.restated_clusters import description_stem
from src.services.restated_demographics import is_restatable_demographic

#: Recorded on each dropped criterion via `_record_skip`, and on each collapse record. Distinct
#: from `restated_demographics.COLLAPSE_REASON` so the generation census attributes each drop to
#: the path that made it.
COLLAPSE_REASON = "restated-distinctness-duplicate"

#: Named on every record rather than left implicit in the iteration order.
SURVIVOR_RULE = "first-in-document-order"

#: The members' keys differ, so the key would keep them apart whatever `sourceText` becomes.
WITHHELD_KEY_DISTINCT = "key-distinct"

#: A class of two or more exists but at least one member carries no `sourceText` (REQ-004).
WITHHELD_EMPTY_SOURCE_TEXT = "empty-sourceText"

#: Fewer than two members survive the REQ-013 gate: the group is the Demographics path's
#: territory, which is a routing outcome rather than a failure of this signal.
WITHHELD_DEMOGRAPHICS_PATH = "demographics-path"


def _canonical(value: Any) -> str:
    """Return a form of `value` that compares equal exactly when `value` does.

    `valueConstraint` is a nested mapping, so identity and `==` are both wrong here -- the
    former for obvious reasons, the latter because the result has to key a dict. Serializing
    with sorted keys gives a hashable form whose equality is structural, so two constraints
    written with their keys in different orders land in one class while any difference in an
    actual value separates them.

    Args:
        value: Any JSON-shaped value from a criterion field.

    Returns:
        A canonical string. Values outside the JSON shapes fall back to `repr` rather than
        raising, so an unexpected field type degrades to "compares unequal unless identical"
        instead of breaking the collapse.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)


def distinctness_key(criterion: dict[str, Any]) -> tuple[str, str, str]:
    """Return the `spec.md` §2.6 distinctness key a criterion partitions under.

    Exact equality on each of the three components, with no normalization of any kind. The
    absence of normalization is deliberate rather than unfinished: `unitConceptId` is plausibly
    a mapping artifact rather than a semantic component of a threshold, but "plausibly" is the
    wrong standard when the harm is asymmetric -- a wrong collapse deletes a clinical criterion
    silently, while a missed collapse leaves a defect that the REQ-011 report keeps visible.

    Args:
        criterion: A top-level IR criterion. Absent keys are treated as empty/null, so a
            criterion built before a field existed is not mistaken for one that carries it.

    Returns:
        `(sourceText, canonical valueConstraint, logicType)`.
    """
    return (
        criterion.get("sourceText") or "",
        _canonical(criterion.get("valueConstraint")),
        criterion.get("logicType") or "",
    )


def partition_by_distinctness(
    members: list[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Partition criteria into equivalence classes under the distinctness key.

    Both the class order and the member order within each class are document order, which
    REQ-005 depends on: the survivor is a class's first member, and "first" is only meaningful
    because nothing here sorts.

    Args:
        members: Criteria of one stem group, in document order.

    Returns:
        A mapping from distinctness key to that class's members, insertion-ordered.
    """
    classes: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for criterion in members or []:
        classes.setdefault(distinctness_key(criterion), []).append(criterion)
    return classes


def _has_source_text(criterion: dict[str, Any]) -> bool:
    return bool((criterion.get("sourceText") or "").strip())


def _describe_class(
    key: tuple[str, str, str],
    members: list[dict[str, Any]],
) -> dict[str, Any]:
    survivor, *dropped = members
    collapsible = len(members) >= 2 and all(_has_source_text(c) for c in members)
    return {
        "distinctnessKey": {
            "sourceText": key[0],
            "valueConstraint": key[1],
            "logicType": key[2],
        },
        "criterionIds": [c.get("id") for c in members],
        "survivorId": survivor.get("id"),
        "droppedIds": [c.get("id") for c in dropped],
        "collapsible": collapsible,
    }


def _withheld_reason(considered: list[dict[str, Any]], classes: list[dict[str, Any]]) -> str:
    """Return why a group was left intact, under the `spec.md` §2.6.1 precedence rule.

    `key-distinct` outranks `empty-sourceText` where both apply, and the ordering is not
    cosmetic. `key-distinct` is a property of the criteria themselves and holds whatever
    `sourceText` later becomes; `empty-sourceText` is a property of the current store and
    evaporates the moment the field is populated -- which `plan.md` B-1 records as having
    already happened once. Reporting the store-independent reason means the label does not
    churn across regenerations, and a reader learns the stronger fact.
    """
    if len(considered) < 2:
        return WITHHELD_DEMOGRAPHICS_PATH
    if all(len(cls["criterionIds"]) == 1 for cls in classes):
        return WITHHELD_KEY_DISTINCT
    return WITHHELD_EMPTY_SOURCE_TEXT


def analyze_restated_groups(
    criteria: list[dict[str, Any]],
    *,
    role: str,
) -> list[dict[str, Any]]:
    """Report every stem group of two or more members, with its partition and verdict.

    This is the measurement, and it is deliberately independent of the collapse: a group is
    reported whether or not anything is dropped, which is what makes REQ-011 satisfiable. A
    genuine duplicate the key cannot reach appears here as an intact group carrying its
    per-member keys, rather than vanishing.

    Grouping happens **before** the REQ-013 gate and the gate is applied inside each group, so
    a group whose members all belong to the Demographics path is still reported -- as
    `demographics-path`, which tells a reader it was routed elsewhere rather than missed. A
    gate applied before grouping would make those groups disappear from the census entirely.

    Args:
        criteria: Top-level criteria for a single role of a single study, in document order.
        role: "inclusion" or "exclusion". Recorded on each group; a group never spans roles,
            so one criterion in each role is two singletons rather than a pair.

    Returns:
        One dict per stem group of two or more members, in first-appearance order, each
        carrying `role`, `domain`, `stem`, `criterionIds` (every member), `consideredIds`
        (those the REQ-013 gate admits), `classes`, `collapses`, and `reason` -- the last
        being None where the group collapses.
    """
    by_stem: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for criterion in criteria or []:
        key = (
            (criterion.get("domain") or "").strip(),
            description_stem(criterion.get("description")),
        )
        by_stem.setdefault(key, []).append(criterion)

    groups: list[dict[str, Any]] = []
    for (domain, stem), members in by_stem.items():
        if len(members) < 2:
            continue
        considered = [c for c in members if not is_restatable_demographic(c)]
        classes = [_describe_class(k, v) for k, v in partition_by_distinctness(considered).items()]
        collapses = any(cls["collapsible"] for cls in classes)
        groups.append(
            {
                "role": role,
                "domain": domain,
                "stem": stem,
                "criterionIds": [c.get("id") for c in members],
                "consideredIds": [c.get("id") for c in considered],
                "classes": classes,
                "collapses": collapses,
                "reason": None if collapses else _withheld_reason(considered, classes),
            }
        )
    return groups
