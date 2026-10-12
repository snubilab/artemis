"""SPEC-INFRA-004: collapse restated criteria, decided by structured fields alone.

`SPEC-INFRA-003` fixed restated-cluster duplication for Demographics (`restated_demographics.py`).
The same duplication exists in Condition, Drug, Procedure, Observation and Measurement: Agent 1
emits one protocol fact several times, each copy is mapped on its own, and the cohort filters
on the union of the divergent concept sets.

**Two rows state the same fact when every structured field the cohort is built from is equal**
(RFC-016 §5, E6). The distinctness key is

```
key = ( domain , sourceText , window , valueConstraint , logicType )
```

compared by exact equality on each component. ``sourceText`` is the entity the concept set is
mapped from, so it stands for the concept set's identity; the collapse runs before mapping.
Nothing is read out of ``description``: the stem test this replaces grouped rows whose
descriptions were equal after one trailing parenthetical was stripped.

**The logic a row sits in is part of the fact.** Two rows with one key collapse only when they
sit in the same place in the rule tree:

* both top-level, or
* in groups of the same type whose non-label members carry the same multiset of keys -- one
  group, or a group and its restatement.

So a member is never moved out of its group into a different group or onto a top-level rule,
where it would change what the cohort requires. A key class whose members sit in different
places is reported as intact with reason ``context-distinct``.

Three kinds of row never collapse: a group label (a container that mints no concept set, so it
cannot stand in for a member), a row with no ``sourceText`` (no concept-set identity to compare),
and a restatable demographic -- the Demographics path's territory. That last gate is the
complement of `is_restatable_demographic`, never ``domain != "Demographics"``, so the two paths
stay disjoint without orphaning a Demographics row that carries a value constraint (REQ-013).

Within a class the survivor is the first member in document order and the rest are dropped.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from src.services.restated_demographics import is_restatable_demographic

#: Recorded on each dropped criterion via `_record_skip`, and on each collapse record. Distinct
#: from `restated_demographics.COLLAPSE_REASON` so the generation census attributes each drop to
#: the path that made it.
COLLAPSE_REASON = "restated-distinctness-duplicate"

#: Named on every record rather than left implicit in the iteration order.
SURVIVOR_RULE = "first-in-document-order"

#: Rows share a key but sit in different places in the rule tree.
WITHHELD_CONTEXT_DISTINCT = "context-distinct"

def _canonical(value: Any) -> str:
    """Return a form of `value` that compares equal exactly when `value` does.

    Nested mappings (``window``, ``valueConstraint``) serialise with sorted keys, so key order
    does not separate two equal values while any difference in an actual value does. A value
    outside the JSON shapes falls back to ``repr`` rather than raising.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)


def distinctness_key(criterion: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Return the structured key a criterion is compared under.

    Exact equality on each component, with no normalisation: a wrong collapse deletes a
    criterion silently, while a missed one stays visible in the intact report.

    Args:
        criterion: A top-level IR criterion. Absent keys read as empty/null.

    Returns:
        ``(domain, sourceText, canonical window, canonical valueConstraint, logicType)``.
    """
    return (
        (criterion.get("domain") or "").strip(),
        criterion.get("sourceText") or "",
        _canonical(criterion.get("window")),
        _canonical(criterion.get("valueConstraint")),
        criterion.get("logicType") or "",
    )


def considered_by_generalized_path(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the criteria this path may act on, in document order.

    Excludes restatable demographics (the Demographics path's own), group labels and rows with
    no ``sourceText``.
    """
    return [
        c
        for c in criteria or []
        if not is_restatable_demographic(c)
        and not c.get("isGroupLabel")
        and (c.get("sourceText") or "").strip()
    ]


def _group_contexts(criteria: list[dict[str, Any]]) -> dict[str, tuple[Any, ...]]:
    """``groupId`` -> the group's type and the multiset of its non-label members' keys."""
    members: dict[str, Counter] = {}
    group_type: dict[str, Any] = {}
    for c in criteria or []:
        group_id = c.get("groupId")
        if group_id is None:
            continue
        group_type.setdefault(str(group_id), c.get("groupType"))
        if not c.get("isGroupLabel"):
            members.setdefault(str(group_id), Counter())[distinctness_key(c)] += 1
    return {
        gid: (group_type.get(gid), tuple(sorted(members.get(gid, Counter()).items())))
        for gid in group_type
    }


def _logic_context(criterion: dict[str, Any], groups: dict[str, tuple[Any, ...]]) -> tuple[Any, ...]:
    group_id = criterion.get("groupId")
    if group_id is None:
        return ("top-level",)
    return ("group", groups[str(group_id)], criterion.get("parentGroupId") is None)


def _describe_key(key: tuple[str, str, str, str, str]) -> dict[str, str]:
    domain, source_text, window, value_constraint, logic_type = key
    return {
        "domain": domain,
        "sourceText": source_text,
        "window": window,
        "valueConstraint": value_constraint,
        "logicType": logic_type,
    }


def analyze_restated_groups(
    criteria: list[dict[str, Any]],
    *,
    role: str,
) -> list[dict[str, Any]]:
    """Report every key class of two or more considered rows, with its partition by context.

    Args:
        criteria: Top-level criteria for a single role of a single study, in document order.
        role: "inclusion" or "exclusion"; a class never spans roles.

    Returns:
        One dict per key class of two or more rows, in first-appearance order, carrying
        ``role``, ``domain``, ``distinctnessKey``, ``criterionIds``, ``classes`` (one per
        place in the rule tree: ``criterionIds``, ``survivorId``, ``droppedIds``,
        ``collapsible``), ``collapses`` and ``reason`` -- None where something collapses.
    """
    groups = _group_contexts(criteria)
    by_key: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for criterion in considered_by_generalized_path(criteria):
        by_key.setdefault(distinctness_key(criterion), []).append(criterion)

    reports: list[dict[str, Any]] = []
    for key, members in by_key.items():
        if len(members) < 2:
            continue
        by_context: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for criterion in members:
            by_context.setdefault(_logic_context(criterion, groups), []).append(criterion)
        classes = [
            {
                "criterionIds": [c.get("id") for c in same],
                "survivorId": same[0].get("id"),
                "droppedIds": [c.get("id") for c in same[1:]],
                "collapsible": len(same) >= 2,
            }
            for same in by_context.values()
        ]
        collapses = any(cls["collapsible"] for cls in classes)
        reports.append(
            {
                "role": role,
                "domain": key[0],
                "distinctnessKey": _describe_key(key),
                "criterionIds": [c.get("id") for c in members],
                "classes": classes,
                "collapses": collapses,
                "reason": None if collapses else WITHHELD_CONTEXT_DISTINCT,
            }
        )
    return reports


def collapse_restated_criteria(
    criteria: list[dict[str, Any]],
    *,
    role: str,
) -> tuple[set[tuple[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse one role's restated criteria, one survivor per (key, context) class.

    Args:
        criteria: Top-level criteria for a single role of a single study, in document order.
            Order is load-bearing: the survivor is each class's first member.
        role: "inclusion" or "exclusion". Recorded on every record and used in the drop keys.

    Returns:
        ``(drop_keys, records, intact)``. ``drop_keys`` holds ``(role, criterion id as str)``
        for every criterion to drop, matching `_record_skip`'s string ids. ``records`` holds
        one dict per collapsed class. ``intact`` holds one dict per key class that nothing
        collapsed, so a duplicate the context keeps apart stays visible in the artifact.
    """
    drop_keys: set[tuple[str, str]] = set()
    records: list[dict[str, Any]] = []
    intact: list[dict[str, Any]] = []

    for group in analyze_restated_groups(criteria, role=role):
        if not group["collapses"]:
            intact.append({k: v for k, v in group.items() if k != "collapses"})
            continue
        for cls in group["classes"]:
            if not cls["collapsible"]:
                continue
            drop_keys |= {(role, str(i)) for i in cls["droppedIds"]}
            records.append(
                {
                    "role": role,
                    "domain": group["domain"],
                    "distinctnessKey": group["distinctnessKey"],
                    "survivorId": cls["survivorId"],
                    "droppedIds": cls["droppedIds"],
                    "survivorRule": SURVIVOR_RULE,
                    "reason": COLLAPSE_REASON,
                }
            )
    return drop_keys, records, intact


def collapse_all_restated_criteria(
    *,
    inclusion_criteria: list[dict[str, Any]],
    exclusion_criteria: list[dict[str, Any]],
) -> tuple[set[tuple[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse restated criteria across both roles of one study, inclusion first.

    The roles are collapsed independently, so an inclusion and an exclusion row never collapse
    into each other.
    """
    inc_keys, inc_records, inc_intact = collapse_restated_criteria(
        inclusion_criteria, role="inclusion"
    )
    exc_keys, exc_records, exc_intact = collapse_restated_criteria(
        exclusion_criteria, role="exclusion"
    )
    return (
        inc_keys | exc_keys,
        inc_records + exc_records,
        inc_intact + exc_intact,
    )
