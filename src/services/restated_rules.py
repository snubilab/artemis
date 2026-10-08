"""Collapse an inclusion rule that another inclusion rule already says, after the rules are built.

The defect, ``deliveries/2026-09-23/carmelina_{treatment,comparator}.circe.json``:

    #11 'Exclusion of GLP-1 receptor agonists if recent + ...'  ALL(==0 GLP1, ==0 DPP4, ==0 SGLT2)
    #14 'Use of GLP-1 receptor agonists + ...'                   ALL(==0 GLP1, ==0 DPP4, ==0 SGLT2)
    #15 'DPP-4 inhibitors'                                       ALL(==0 DPP4)

over member-identical sets in the same 7-day window. The protocol states the restriction in two
places, and the extraction carried both: #11 comes from the inclusion group under "Drug-naive or
pre-treated ... (excluding GLP-1, DPP-4, SGLT-2 if recent)", #14 and #15 from two exclusion
groups. CIRCE AND-combines every ``InclusionRules`` entry, so #14 and #15 select nothing #11 has
not already selected -- both sites' Atlas reports give #11 and #14 the same N.

WHY THE IR-LEVEL RESTATED PATHS CANNOT REACH IT. :mod:`src.services.restated_distinctness` and
:mod:`src.services.restated_demographics` decide per role, inside one (domain, description stem)
group, before mapping. Here the pair spans two roles (inclusion 85eaf366 against exclusion
773392a3) and every member has its own stem ('Exclusion of GLP-1 receptor agonists if recent',
'Use of GLP-1 receptor agonists', 'DPP-4 inhibitors'), and #15 is not a restatement of any ONE
criterion but of one conjunct of a three-criterion rule. Identity is only decidable on what the
rules SELECT, which exists only after the concept sets are minted -- so this runs on the built
expression, not on the IR.

THE PREDICATE, exact and structural, with no threshold and no names:

* A rule is eligible only when every group in it is ``ALL`` -- a pure conjunction. A rule with an
  ``ANY`` / ``AT_LEAST`` / ``AT_MOST`` node anywhere is never collapsed and never a survivor, so
  nothing here ever reasons across a disjunction.
* A rule's conjuncts are its criteria and demographic criteria, collected through ``ALL`` nodes.
  Each is compared as its whole JSON with every ``CodesetId`` replaced by the CONTENT of the
  concept set it names: the set of ``(CONCEPT_ID, includeDescendants, isExcluded, includeMapped)``
  items. The concept set's name and id never take part. Everything else -- the CDM table, value
  and ratio filters, units, ``Occurrence``, ``StartWindow`` / ``EndWindow``, restrict-visit -- is
  compared verbatim, so a different window or a different operator is a different conjunct.
* ``identical``: two rules with the same conjunct set. ``implied``: a rule whose conjunct set is a
  proper subset of another's. Nothing weaker: no concept-ancestor closure, no window containment,
  no bound containment.

Which rule survives: a rule that no other rule implies and that has no earlier identical twin --
a *maximal* rule. Every collapsed rule is recorded onto a maximal rule, the identical one if it
has one, else the first in document order, so a rule is never collapsed onto a rule that was
itself collapsed. ``PrimaryCriteria`` is never read or written.

Role is not an input. An exclusion reaches CIRCE as an inclusion rule demanding exactly 0
occurrences, which is what the conjunct compares, so an exclusion that restates an inclusion
collapses exactly as two inclusions would -- the CARMELINA pair is one of each.

THE RECORD. Each collapsed rule leaves one record under :data:`RESTATED_RULE_COLLAPSE_KEY`,
present and empty when nothing collapsed (the contract every sibling key carries: absent means
"predates the record", never "nothing collapsed"). It names both rules, both sets of criterion
keys, the reason, and carries the removed rule's expression verbatim, because the delivery gate
re-derives the relation from the file it is handed rather than trusting the record --
``scripts/verify_circe_delivery.py`` ``restated_rule_collapse_violations``. The removed rule's
concept sets stay in ``ConceptSets`` for that reason; Atlas and WebAPI ignore an unused set.

``_generationCensus`` is deliberately untouched, for the reason
``drop_unreadable_value_criteria`` and :mod:`src.services.restated_absence_repair` leave it
alone: it counts what the mapper did with each criterion, and these criteria DID map. What
changed is that their rule says nothing the file does not already say.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

#: Where each collapse is recorded on the built expression.
RESTATED_RULE_COLLAPSE_KEY = "_restatedRuleCollapse"

#: The rule's conjunct set equals another rule's.
IDENTICAL_REASON = "restated-rule-identical"

#: The rule's conjunct set is a proper subset of another rule's.
IMPLIED_REASON = "restated-rule-implied"

#: The only reasons a record may carry; the gate refuses any other.
COLLAPSE_REASONS = frozenset({IDENTICAL_REASON, IMPLIED_REASON})

#: Named on every record rather than left implicit in the iteration order.
SURVIVOR_RULE = "maximal-rule-identical-first-else-first-in-document-order"

_RELATION_REASON = {"identical": IDENTICAL_REASON, "implied": IMPLIED_REASON}


def _concept_set_contents(
    concept_sets: Sequence[Mapping[str, Any]] | None,
) -> dict[Any, list[list[Any]]]:
    contents: dict[Any, list[list[Any]]] = {}
    for concept_set in concept_sets or []:
        if not isinstance(concept_set, Mapping):
            continue
        items = ((concept_set.get("expression") or {}).get("items")) or []
        contents[concept_set.get("id")] = sorted(
            {
                (
                    (item.get("concept") or {}).get("CONCEPT_ID"),
                    bool(item.get("includeDescendants")),
                    bool(item.get("isExcluded")),
                    bool(item.get("includeMapped")),
                )
                for item in items
                if isinstance(item, Mapping)
            },
            key=repr,
        )
    return contents


def _resolve_codesets(node: Any, contents: Mapping[Any, Any]) -> Any:
    """``node`` with every ``CodesetId`` replaced by the content of the set it names.

    An id naming no set in the file resolves to a marker carrying the id, so two unresolvable
    references compare equal only when they name the same id -- never equal to a real set.
    """
    if isinstance(node, Mapping):
        return {
            key: (["codeset", contents[value]] if value in contents else ["missing-codeset", value])
            if key == "CodesetId"
            else _resolve_codesets(value, contents)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_resolve_codesets(value, contents) for value in node]
    return node


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)


def _conjuncts(group: Any, contents: Mapping[Any, Any]) -> frozenset[str] | None:
    """The conjunct set of a group reached through ``ALL`` only, or None when it is not one."""
    if not isinstance(group, Mapping) or (group.get("Type") or "ALL") != "ALL":
        return None
    found: set[str] = set()
    for key in ("CriteriaList", "DemographicCriteriaList"):
        for entry in group.get(key) or []:
            found.add(_canonical(_resolve_codesets(entry, contents)))
    for subgroup in group.get("Groups") or []:
        nested = _conjuncts(subgroup, contents)
        if nested is None:
            return None
        found |= nested
    return frozenset(found)


def _relation(rule: frozenset[str] | None, other: frozenset[str] | None) -> str | None:
    if not rule or other is None:
        return None
    if rule == other:
        return "identical"
    if rule < other:
        return "implied"
    return None


def rule_relation(
    rule_expression: Mapping[str, Any],
    other_expression: Mapping[str, Any],
    concept_sets: Sequence[Mapping[str, Any]] | None,
) -> str | None:
    """Whether ``rule_expression`` adds nothing once ``other_expression`` is required.

    The one predicate both the builder's collapse and the delivery gate apply.

    :param rule_expression: an ``InclusionRules`` entry's ``expression``.
    :param other_expression: another rule's ``expression``.
    :param concept_sets: the ``ConceptSets`` both rules' ``CodesetId`` values resolve against.
    :returns: ``"identical"`` when the two conjunct sets are equal, ``"implied"`` when the
        rule's conjuncts are a proper subset of the other's, else None -- including whenever
        either rule has a non-``ALL`` node or the rule has no conjuncts at all.
    """
    contents = _concept_set_contents(concept_sets)
    return _relation(_conjuncts(rule_expression, contents), _conjuncts(other_expression, contents))


def missing_codeset_ids(node: Any, concept_sets: Sequence[Mapping[str, Any]] | None) -> list[Any]:
    """Every ``CodesetId`` under ``node`` that names no set in ``concept_sets``, sorted.

    :param node: any part of a CIRCE expression, typically one rule's ``expression``.
    :param concept_sets: the ``ConceptSets`` it should resolve against.
    :returns: the unresolvable ids; empty when every reference resolves.
    """
    contents = _concept_set_contents(concept_sets)
    missing: set[Any] = set()

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key == "CodesetId":
                    if child not in contents:
                        missing.add(child)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return sorted(missing, key=repr)


def redundant_inclusion_rules(expression: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every inclusion rule another inclusion rule in the same file makes redundant.

    :param expression: a CIRCE expression.
    :returns: one dict per redundant rule, in document order, carrying ``index``,
        ``survivorIndex`` and ``reason``. A survivor is always a maximal rule -- implied by no
        rule and with no earlier identical twin -- so it is never itself in the list.
    """
    contents = _concept_set_contents(expression.get("ConceptSets"))
    rules = [r for r in expression.get("InclusionRules") or []]
    conjuncts = [
        _conjuncts(r.get("expression"), contents) if isinstance(r, Mapping) else None for r in rules
    ]

    def dominated(index: int) -> bool:
        return any(
            relation == "implied" or (relation == "identical" and other < index)
            for other in range(len(rules))
            if other != index
            for relation in [_relation(conjuncts[index], conjuncts[other])]
        )

    maximal = [bool(conjuncts[i]) and not dominated(i) for i in range(len(rules))]
    found: list[dict[str, Any]] = []
    for index in range(len(rules)):
        if not conjuncts[index] or maximal[index]:
            continue
        candidates = [
            (other, relation)
            for other in range(len(rules))
            if other != index and maximal[other]
            for relation in [_relation(conjuncts[index], conjuncts[other])]
            if relation is not None
        ]
        if not candidates:
            # Unreachable for a finite rule list -- a chain of strict supersets ends at a
            # maximal rule -- and stated so a future edit that breaks the property fails loudly
            # rather than silently keeping a rule this function called redundant.
            raise AssertionError(f"rule {index} is dominated but no maximal rule covers it")
        survivor, relation = next((c for c in candidates if c[1] == "identical"), candidates[0])
        found.append(
            {"index": index, "survivorIndex": survivor, "reason": _RELATION_REASON[relation]}
        )
    return found


def collapse_redundant_inclusion_rules(
    expression: dict[str, Any],
    rule_criterion_keys: Sequence[Sequence[str]] | None = None,
) -> list[dict[str, Any]]:
    """Remove each redundant inclusion rule and record it onto its survivor; mutates ``expression``.

    :param expression: a built CIRCE expression.
    :param rule_criterion_keys: per ``InclusionRules`` entry, the ``role:id`` keys of the
        criteria it was built from, in the same order. Recorded on each record so every
        collapsed criterion is named; omitted, the records carry empty key lists.
    :returns: the records written under :data:`RESTATED_RULE_COLLAPSE_KEY`, which is set
        present-and-empty when nothing collapsed.
    :raises ValueError: when ``rule_criterion_keys`` does not align one-to-one with the rules
        -- a misaligned list would name the wrong criteria on every record.
    """
    rules = expression.get("InclusionRules") or []
    if rule_criterion_keys is not None and len(rule_criterion_keys) != len(rules):
        raise ValueError(
            f"{len(rule_criterion_keys)} criterion-key lists for {len(rules)} inclusion rules"
        )
    keys = (
        [list(k) for k in rule_criterion_keys]
        if rule_criterion_keys is not None
        else [[] for _ in rules]
    )

    records: list[dict[str, Any]] = []
    for finding in redundant_inclusion_rules(expression):
        index, survivor = finding["index"], finding["survivorIndex"]
        records.append(
            {
                "reason": finding["reason"],
                "rule": rules[index].get("name"),
                "ruleIndex": index,
                "criterionKeys": keys[index],
                "survivorRule": rules[survivor].get("name"),
                "survivorRuleIndex": survivor,
                "survivorCriterionKeys": keys[survivor],
                "survivorRuleSelection": SURVIVOR_RULE,
                "expression": deepcopy(rules[index].get("expression")),
            }
        )
    removed = {record["ruleIndex"] for record in records}
    expression["InclusionRules"] = [rule for i, rule in enumerate(rules) if i not in removed]
    expression[RESTATED_RULE_COLLAPSE_KEY] = records
    return records


def redundant_inclusion_rule_findings(expression: Mapping[str, Any]) -> list[str]:
    """One line per redundant inclusion rule still present in a delivered file -- the gate's check.

    :param expression: a delivered CIRCE expression.
    :returns: human-readable findings, 1-based rule numbers, empty when the file has none.
    """
    rules = expression.get("InclusionRules") or []
    return [
        f"#{f['index'] + 1} {rules[f['index']].get('name')!r} is "
        + (
            "identical to"
            if f["reason"] == IDENTICAL_REASON
            else "implied by (every conjunct appears in)"
        )
        + f" #{f['survivorIndex'] + 1} {rules[f['survivorIndex']].get('name')!r}"
        for f in redundant_inclusion_rules(expression)
    ]
