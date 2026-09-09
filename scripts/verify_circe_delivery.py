#!/usr/bin/env python
"""Delivery gate for an existing per-arm CIRCE export directory.

Run this against a directory produced by ``export_seeded_cohorts.py`` (or any
other directory of ``*.circe.json`` files) before anything in it is sent to a
site. It never writes or fixes anything — it only checks and reports.

Checks per file:

(a) zero no-op exclusion rules (see ``src.utils.circe_lint.noop_exclusion_rules``)
(b) the file's InclusionRules names equal the store study's rule names as a
    multiset, allowing at most one extra rule (the appended arm drug rule).
    The store side is first reconciled against the file's own ``_droppedCriteria``
    records: the emission-time repair removes a criterion whose value filter its CDM
    table cannot read, which either removes its rule outright or rewrites the rule's
    name from the members that survived, while the store keeps the pre-drop text. So
    a repaired export diverged from its own store on 8 of 12 files. A drop is
    forgiven only to the exact extent a record explains it — an unrecorded missing
    rule still fails, and so does a record naming a rule the store does not carry or
    a (criteria type, attribute) pair that is not actually unreadable.
(c) the file's PrimaryCriteria entry concept ids equal the store study's
    entry set, OR — for a comparator — the entry may legitimately be either
    a disease-anchored ``ConditionOccurrence`` set (the placebo-comparator
    design) or a ``DrugEra`` set naming the study's own second treatment arm
    (the active-comparator design, e.g. CAROLINA's comparator is legitimately
    "glimepiride", not linagliptin)
(d) if a ``manifest.json`` sits beside the files, its recorded md5s match the
    files on disk and its ``store_sha256`` matches the ``--store`` file
(h) a disease-anchored comparator entry is the trial's OWN registered condition.
    Check (c) accepts ANY ``ConditionOccurrence`` entry on a comparator, because the
    swap itself is legitimate -- so it passed LEADER's comparator entering on
    ``LV systolic or diastolic dysfunction`` (one of several alternative
    cardiovascular-risk qualifiers) instead of type 2 diabetes, which is a fraction of
    the trial population. The expected anchor comes from
    ``src.utils.disease_anchor.expected_anchor_concept_ids``, the same function the
    generator chooses with, against ``trialMetadata.conditions``. A study with no
    registered condition FAILS rather than passing unchecked -- backfill it with
    ``scripts/backfill_registered_conditions.py``.

(g) every criterion's concept set shares at least one OMOP domain with the CDM
    table that criterion reads. A ``ConditionOccurrence`` criterion over a Drug
    concept set joins ``condition_occurrence.condition_concept_id`` against drug
    products and matches nothing; as an ABSENCE rule that means everyone
    satisfies it and the exclusion is never applied. CAROLINA shipped that shape
    ("Glimepiride", codeset 56) and passed checks (a) to (f), because none of
    them reads a criterion's domain against its own concept set. Measured
    against WebAPI rather than reasoned — see
    ``src.utils.circe_lint.domain_mismatched_criteria`` and
    ``output/site_gap/2026-09-06/plan048_domain_repair/``.

(i) the file's own criterion accounting — ``_generationCensus``,
    ``_unmappedCriteria``, ``_skippedCriteria`` — balances and records no loss.
    The generator has always written these three keys into the delivered payload
    and nothing read them: ``rg -c _unmappedCriteria`` over this script and
    ``export_seeded_cohorts.py`` exited 1. So
    ``output/anchor_after/aristotle_comparator.circe.json`` shipped with two
    protocol exclusions recorded as unmapped ("Aspirin and thienopyridine
    combination", "Investigational drug use") and this gate printed PASS. Check
    (b) structurally cannot catch it: it compares the file's rule names against
    the store ``structuredExpression`` produced by the SAME generation, so both
    sides are missing the same criteria and the multiset matches.
    See ``criterion_accounting`` below for the failure condition and for why
    ``skipped > 0`` is not one. A recorded skip is a permit, not a verdict: each
    one under an allowed reason is re-derived here from the store criterion it
    names and from the delivered file — a ``group-label`` row must be a group label
    whose threshold strands no member and at least one of whose members emitted, a
    ``demographic-no-rule`` row must be demographic-domain and carry no bound, and a
    restated-* row must have a collapse record naming a survivor that emitted. An
    ``_unmappedCriteria`` row is never permitted whatever its reason says, and one
    carrying no reason at all fails on its own line.

And one check across files rather than per file:

(f) no rule requires zero occurrences of a concept set that intersects the
    cohort's own entry set. Such a rule empties the cohort by construction, and
    every other per-file check reads one property in isolation, so none of them
    can see it. CARMELINA shipped that shape and passed.

(e) every arm a mapped study declares in the store produced a file. Checks (a)
    to (d) all read a file that exists, so a delivery that is SHORT an arm
    passes all of them -- which is what happened on 2026-09-05, when a five-file
    export with a silently dropped EMPA-REG comparator exited 0. Only studies
    that produced at least one file are checked, so a deliberate single-study
    export still passes; the expected arm set comes from the store's own
    ``treatmentArms``, so a genuinely single-arm study needs no opt-out.

The 2026-08-31 delivery (``artemis/output/circe_be/2026-08-31/``) is the
counterexample this gate exists to catch — see ``AGENTS.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.restated_demographics import (  # noqa: E402
    COLLAPSE_REASON as RESTATED_DEMOGRAPHICS_REASON,
)
from src.services.restated_distinctness import (  # noqa: E402
    COLLAPSE_REASON as RESTATED_DISTINCTNESS_REASON,
)
from src.services.value_constraint import (  # noqa: E402
    STRANDED_GROUP_CONSTRAINT_REASON,
    resolve_group_member_constraint,
)
from src.utils.circe_lint import (  # noqa: E402
    DROP_OUTCOME_RULE_KEPT,
    DROP_OUTCOME_RULE_REMOVED,
    DROP_OUTCOME_RULE_RENAMED,
    DROPPED_CRITERIA_KEY,
    contradictory_absence_rules,
    domain_mismatched_criteria,
    entry_concept_ids,
    entry_concept_set_name,
    entry_matches_expected,
    missing_arm_roles,
    noop_exclusion_rules,
    rule_names,
    unreadable_value_attributes,
)
from src.utils.delivery_mode import (  # noqa: E402
    DeliveryModeConflictError,
    resolve_drug_anchored_entry,
)
from src.utils.disease_anchor import DiseaseAnchorError, expected_anchor_concept_ids
from src.utils.store_resolution import StoreMismatchError, resolve_store_path  # noqa: E402

DEFAULT_MAP = "carmelina=9,empa-reg=8,carolina=10,aristotle=3,plato=2,leader=1"

#: The three keys ``TTEService._build_seeded_target_circe`` writes together to
#: account for every criterion that did not become a rule. Emitted as a set —
#: present-and-empty rather than absent — so a partial set means something removed
#: one after generation, which is checked separately from an artifact that carries
#: none of them because it predates the accounting.
ACCOUNTING_KEYS = ("_generationCensus", "_unmappedCriteria", "_skippedCriteria")

#: Skip reasons that are NOT criterion loss, so a delivery carrying them still
#: ships. Derived from what this tree's own exported artifacts contain — the 108
#: ``*.circe.json`` under ``output/`` that carry the records, of 151 present — one
#: entry per reason actually observed there:
#:
#: * ``group-label`` (1046 rows) — a container row. Its members map and emit as one
#:   grouped inclusion rule; the label itself never carried a concept set. Every
#:   observed row has ``isGroupLabel: true``.
#: * ``demographic-no-rule`` (106 rows) — a Demographics row with no single usable
#:   ``valueConstraint`` ("Age and Sex", "Age >= 50 with prior CVD",
#:   "Age (region-conditional)"). The components emit on their own.
#: * the two collapse reasons (458 rows) — a restatement deliberately dropped onto
#:   its retained sibling, which does emit. Both are recorded a second time under
#:   ``_restatedDemographicsCollapse`` / ``_restatedDistinctnessCollapse``.
#:
#: The two collapse spellings are imported from the modules that own them rather
#: than retyped; the other two are bare literals in ``tte_service.py`` with no
#: owning constant, so they are spelled here. That is safe in one direction only,
#: and it is the right one: this is a PERMIT list, so any drift — a renamed reason,
#: a typo here, a new silent branch — leaves the reason unrecognised and FAILS the
#: delivery rather than quietly passing it.
#:
#: Each entry is a PERMIT that :func:`skipped_criteria_violations` re-judges against
#: the store criterion and the delivered file — it is not a verdict the record gets to
#: assert about itself. ``group-label`` is re-judged as: the store row is actually a
#: group label, its own threshold is not one ``resolve_group_member_constraint``
#: refuses to hand down, and at least one member of its group emitted.
#: ``demographic-no-rule`` as: the store row is demographic-domain and carries no
#: numeric bound. The two restated-* reasons as: the file carries a collapse record
#: naming the criterion as dropped, whose survivor exists in the store and was not
#: itself lost. A record the gate cannot re-judge — one naming a criterion absent
#: from the store, or a collapse list absent from the file — fails closed.
#:
#: ``STRANDED_GROUP_CONSTRAINT_REASON`` is deliberately absent. It records a group
#: label whose absolute threshold reached no member, so the members emit
#: unconstrained and the exclusion is not what the protocol wrote. It occurs in the
#: real 2026-09-08 batch (CAROLINA exclusion 44 and EMPA-REG exclusion 56,
#: "Glucose"), where the file then emits the three members as UNFILTERED absence
#: criteria — measured in ``carolina_treatment``: rule 36 excludes any glucose
#: measurement of any value in the last 180 days while inclusion rule 5 REQUIRES an
#: HbA1c in the same window, and the two codesets overlap on 4 of 6 presence
#: concepts. So the emitted shape over-excludes rather than under-excludes, and
#: check (f) cannot see it because it tests absence against the ENTRY set only.
#: Keeping the reason off this list is what makes the re-judgement above load-bearing:
#: a producer that stopped recording it and wrote plain ``group-label`` instead would
#: otherwise launder four real losses straight through the permit.
#: ``exclusion-demographic-eq-unsupported`` is absent for the same reason — it drops
#: an exclusion age bound CIRCE cannot invert, which is a lost bound.
ALLOWED_SKIP_REASONS = frozenset(
    {
        "group-label",
        "demographic-no-rule",
        RESTATED_DEMOGRAPHICS_REASON,
        RESTATED_DISTINCTNESS_REASON,
    }
)


#: The three outcomes a drop record may claim for the rule its criterion sat in.
#: Imported from the producer rather than retyped, for the same reason the two
#: collapse reasons above are.
DROP_OUTCOMES = frozenset(
    {DROP_OUTCOME_RULE_REMOVED, DROP_OUTCOME_RULE_RENAMED, DROP_OUTCOME_RULE_KEPT}
)


#: Where the second record of a collapse lives, per collapse reason. The reasons are
#: the producer's own constants; the two KEY spellings are not — no module owns them,
#: they are literals in ``TTEService._build_seeded_target_circe``. That asymmetry is
#: safe in one direction only and it is this one: a misspelling here finds no list and
#: the skip FAILS as unreconcilable rather than passing unchecked.
COLLAPSE_RECORD_KEYS = {
    RESTATED_DISTINCTNESS_REASON: "_restatedDistinctnessCollapse",
    RESTATED_DEMOGRAPHICS_REASON: "_restatedDemographicsCollapse",
}


def _describe(record: dict[str, Any]) -> str:
    role = record.get("role") or "?"
    return f"{role} #{record.get('criterionId', '?')} {str(record.get('label', ''))!r}"


def dropped_criteria_violations(records: Any) -> list[str]:
    """Whether each ``_droppedCriteria`` record actually describes a legal drop.

    Read on its own, a drop record is a self-report by the artifact being checked, and
    check (b) forgives a rule-set mismatch to the extent these records explain it. So
    the record must be more than well-formed: the ``(criteria type, attribute)`` pair
    it names is re-judged here by :func:`unreadable_value_attributes`, the same
    predicate the generator refused with. A record claiming ``Measurement`` carried an
    unreadable ``Unit`` describes no defect — Measurement reads Unit — so it explains
    no removal, and a rule cannot be laundered out of a file by inventing one.

    :param records: the value under ``_droppedCriteria``, of any shape.
    :returns: one line per malformed or unjustified record; empty when every record
        describes a drop this tree would actually have performed.
    """
    if records is None:
        return []
    if not isinstance(records, list):
        return [f"{DROPPED_CRITERIA_KEY} is not a list: {type(records).__name__}"]

    violations: list[str] = []
    for index, record in enumerate(records):
        where = f"{DROPPED_CRITERIA_KEY}[{index}]"
        if not isinstance(record, dict):
            violations.append(f"{where} is not a record: {record!r}")
            continue

        rule = record.get("rule")
        if not isinstance(rule, str) or not rule:
            violations.append(f"{where} names no rule: {record.get('rule')!r}")

        outcome = record.get("outcome")
        rule_after = record.get("ruleAfter")
        if outcome not in DROP_OUTCOMES:
            violations.append(f"{where} carries an unknown outcome {outcome!r}")
        elif outcome == DROP_OUTCOME_RULE_REMOVED and rule_after is not None:
            violations.append(
                f"{where} says the rule was removed but names a surviving rule "
                f"{rule_after!r}"
            )
        elif outcome == DROP_OUTCOME_RULE_RENAMED and (
            not isinstance(rule_after, str) or not rule_after or rule_after == rule
        ):
            violations.append(
                f"{where} says the rule was renamed but its new name is {rule_after!r}"
            )
        elif outcome == DROP_OUTCOME_RULE_KEPT and rule_after != rule:
            violations.append(
                f"{where} says the rule name was kept but records {rule_after!r} "
                f"beside {rule!r}"
            )

        unreadable = record.get("unreadable")
        if not isinstance(unreadable, list) or not unreadable:
            violations.append(f"{where} records no unreadable value attribute")
            continue
        for detail in unreadable:
            if not isinstance(detail, dict):
                violations.append(f"{where} carries a malformed detail {detail!r}")
                continue
            criteria_type = detail.get("criteriaType")
            attributes = detail.get("attributes")
            if not isinstance(criteria_type, str) or not isinstance(attributes, list):
                violations.append(f"{where} carries a malformed detail {detail!r}")
                continue
            # The predicate, not the record, decides. A probe body keyed by the
            # recorded attribute names is enough: `unreadable_value_attributes` reads
            # keys only.
            judged = unreadable_value_attributes(
                criteria_type, {name: None for name in attributes}
            )
            if sorted(judged) != sorted(str(name) for name in attributes):
                violations.append(
                    f"{where} claims {criteria_type} cannot read "
                    f"{', '.join(str(a) for a in attributes)}, but the allowlist says "
                    f"it cannot read {', '.join(judged) or 'nothing there'} — the "
                    "record justifies no drop"
                )
    return violations


def reconcile_dropped_rules(
    expression: dict[str, Any], store_names: list[str]
) -> tuple[list[str], list[str]]:
    """Replay the file's recorded drops onto the store's rule names.

    The emission-time repair mutates the expression being delivered and leaves the
    store's ``structuredExpression`` alone, so the two rule multisets legitimately
    differ after a drop. Each record says which rule it changed and how, so the store
    side can be moved forward to what the drop should have produced — and only that
    far. A missing rule no record accounts for survives the reconciliation and still
    fails check (b).

    :param expression: the delivered CIRCE expression.
    :param store_names: the store study's ``InclusionRules`` names.
    :returns: ``(adjusted store names, violations)``. Violations name a record whose
        rule the store does not carry, which means the record describes some other
        file's drop and explains nothing about this one.
    """
    records = expression.get(DROPPED_CRITERIA_KEY)
    if not isinstance(records, list) or not records:
        return list(store_names), []

    counter = Counter(store_names)
    violations: list[str] = []

    # One transformation per rule the drop touched, not one per criterion: CARMELINA's
    # incretin rule loses two members and leaves the file once. `ruleIndex` keys it, so
    # two distinct rules that happen to share a name stay two transformations.
    transformations: list[tuple[Any, str, Any, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        key = (
            record.get("ruleIndex"),
            str(record.get("rule") or ""),
            record.get("ruleAfter"),
            record.get("outcome"),
        )
        if key not in transformations:
            transformations.append(key)

    for _rule_index, rule, rule_after, outcome in transformations:
        if outcome == DROP_OUTCOME_RULE_KEPT:
            continue
        if outcome not in (DROP_OUTCOME_RULE_REMOVED, DROP_OUTCOME_RULE_RENAMED):
            # Reported by `dropped_criteria_violations`; replaying an outcome this
            # function does not understand would forgive a mismatch on a record
            # nobody validated.
            continue
        if counter[rule] <= 0:
            violations.append(
                f"{DROPPED_CRITERIA_KEY} records a drop from rule {rule!r}, which the "
                "store study does not carry"
            )
            continue
        counter[rule] -= 1
        if outcome == DROP_OUTCOME_RULE_RENAMED:
            counter[str(rule_after)] += 1

    return list(counter.elements()), violations


def criteria_index(study: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """``(role, criterionId)`` -> the store criterion row, for both roles.

    Store ids are ints and every record spells them as strings, so the key is
    stringified on both sides here — the same thing ``TTEService._record_skip`` does
    when it writes ``str(criterion.get("id", ""))``. A comparison that skipped that
    would find nothing and turn every reconciliation into a false failure.
    """
    eligibility = study.get("eligibility") or {}
    return {
        (role, str(criterion.get("id", ""))): criterion
        for role, rows in (
            ("inclusion", eligibility.get("inclusionCriteria") or []),
            ("exclusion", eligibility.get("exclusionCriteria") or []),
        )
        for criterion in rows
        if isinstance(criterion, dict)
    }


def unmapped_criteria_violations(
    records: Any, index: dict[tuple[str, str], dict[str, Any]]
) -> list[str]:
    """Whether each ``_unmappedCriteria`` record is a record at all.

    Deliberately NOT a classification of unmapped criteria: every one of them is
    criterion loss and fails the file on the line below this one, whatever its reason
    text says. There is no allowlist and there must not be, because
    ``"No concept mapping found for 'X'"`` is byte-for-byte the same string for a
    placeholder the mapper was right to refuse (PLATO's "Table II criteria", a pointer
    to a table in the protocol) and for a data-gap miss ("Contraindication to
    clopidogrel", whose concepts are standard and merely absent from the index). No
    reason string separates the two, so allowlisting any of them allowlists real loss.

    What IS checked is that the record can be re-judged at all: a reason that is empty
    or whitespace-only, or a ``(role, criterionId)`` the store study does not carry.
    Six rows of the 2026-09-08 batch (ARISTOTLE 26/27, PLATO 16, over two arms each)
    carry ``reason: ""`` because the producer records ``str(e)`` and
    ``str(TimeoutError())`` is the empty string — the run log shows a 5-second Stage 1
    search timeout booked as a mapping refusal. Such a row is reported on its own line
    so that no future allowlist can ever cover it.

    :param records: the value under ``_unmappedCriteria``, of any shape.
    :param index: the store study's criteria, from :func:`criteria_index`.
    :returns: one line per record that cannot be re-judged; empty when every record is
        well-formed and attributable.
    """
    if records is None:
        return []
    if not isinstance(records, list):
        return [f"_unmappedCriteria is not a list: {type(records).__name__}"]

    violations: list[str] = []
    for position, record in enumerate(records):
        where = f"_unmappedCriteria[{position}]"
        if not isinstance(record, dict):
            violations.append(f"{where} is not a record: {record!r}")
            continue
        role = record.get("role")
        criterion_id = str(record.get("criterionId") or "").strip()
        if role not in ("inclusion", "exclusion"):
            violations.append(
                f"{where} {_describe(record)} carries an unrecognised role {role!r}"
            )
        elif not criterion_id:
            violations.append(f"{where} {_describe(record)} names no criterion")
        elif (role, criterion_id) not in index:
            violations.append(
                f"{where} {_describe(record)} names a criterion the store study does "
                "not carry, so the refusal cannot be re-judged"
            )
        if not str(record.get("reason") or "").strip():
            violations.append(
                f"{where} {_describe(record)} carries no reason — the producer recorded "
                "str(e) of an exception with an empty message (a TimeoutError on the "
                "Stage 1 search in the 2026-09-08 batch); a refusal that does not say "
                "why it refused cannot be reconciled"
            )
    return violations


def _group_label_violations(
    where: str,
    label: dict[str, Any],
    role: str,
    index: dict[tuple[str, str], dict[str, Any]],
    lost: set[tuple[str, str]],
) -> list[str]:
    """Re-derive a ``group-label`` permit from the store rows of its own group."""
    violations: list[str] = []
    if not label.get("isGroupLabel"):
        violations.append(
            f"{where} is recorded as group-label but the store row is not a group label"
        )

    group_id = label.get("groupId")
    if not group_id:
        return violations
    members = [
        (key, criterion)
        for key, criterion in index.items()
        if key[0] == role
        and not criterion.get("isGroupLabel")
        and str(criterion.get("groupId")) == str(group_id)
    ]

    # The laundering guard. `resolve_group_member_constraint` is the one place that
    # decides whether a label's threshold reaches its members; asking it here means a
    # producer that stopped recording STRANDED and wrote plain `group-label` instead
    # cannot slip the loss past this permit, because the decision is re-made rather
    # than read off the record.
    label_constraint = label.get("valueConstraint")
    if label_constraint and any(
        criterion.get("valueConstraint") is None for _key, criterion in members
    ):
        resolution = resolve_group_member_constraint(label_constraint, None)
        if resolution.refusal_reason == STRANDED_GROUP_CONSTRAINT_REASON:
            violations.append(
                f"{where} is recorded as group-label but the producer's own predicate "
                f"says its absolute threshold {label_constraint!r} reaches no member: "
                f"that is {STRANDED_GROUP_CONSTRAINT_REASON}, which is loss and is off "
                "the allowlist"
            )

    # A container row loses nothing BECAUSE its members emit. When every member was
    # itself lost the group left the cohort entirely and nothing carries it.
    if members and all(key in lost for key, _criterion in members):
        violations.append(
            f"{where} is a group label skipped while none of its {len(members)} "
            "member(s) emitted, so the whole group left the cohort"
        )
    return violations


def _collapse_violations(
    where: str,
    reason: str,
    role: str,
    criterion_id: str,
    expression: dict[str, Any],
    index: dict[tuple[str, str], dict[str, Any]],
    unmapped_keys: set[tuple[str, str]],
    skipped_by_key: dict[tuple[str, str], dict[str, Any]],
) -> list[str]:
    """Re-derive a restated-* permit from the collapse record in the same file."""
    key = COLLAPSE_RECORD_KEYS[reason]
    collapses = expression.get(key)
    if not isinstance(collapses, list):
        return [
            f"{where} is recorded as {reason} but the file carries no {key}, so nothing "
            "says which criterion it was collapsed onto"
        ]
    record = next(
        (
            candidate
            for candidate in collapses
            if isinstance(candidate, dict)
            and candidate.get("role") == role
            and criterion_id in {str(x) for x in (candidate.get("droppedIds") or [])}
        ),
        None,
    )
    if record is None:
        return [f"{where} is recorded as {reason} but no collapse record names it as dropped"]

    survivor_id = record.get("survivorId")
    survivor = (role, str(survivor_id))
    if survivor not in index:
        return [
            f"{where} was collapsed onto survivor #{survivor_id}, which the store study "
            "does not carry"
        ]
    if survivor in unmapped_keys:
        return [
            f"{where} was collapsed onto survivor #{survivor_id}, which was itself "
            "recorded unmapped — the restatement and the row it was folded into are "
            "both absent"
        ]
    survivor_skip = skipped_by_key.get(survivor)
    if survivor_skip is not None and survivor_skip.get("reason") not in ALLOWED_SKIP_REASONS:
        return [
            f"{where} was collapsed onto survivor #{survivor_id}, which was itself "
            f"skipped for {survivor_skip.get('reason')!r}"
        ]
    return []


def skipped_criteria_violations(
    records: Any,
    index: dict[tuple[str, str], dict[str, Any]],
    expression: dict[str, Any],
) -> list[str]:
    """Whether each ALLOWED skip reason actually holds for the criterion it names.

    :data:`ALLOWED_SKIP_REASONS` read on its own is an amnesty: the reason string is
    written by the artifact being checked, so a producer that renamed one branch's
    reason to another's would have its loss forgiven by a gate whose own test pins the
    original reason off the list. This is the same standard ``b6a4f2f`` set for
    ``_droppedCriteria`` — a drop is excused exactly as far as its record can be
    re-judged, and no further — applied to the channel that was still taken on trust.

    Only records whose reason IS on the allowlist are examined; an off-list reason is
    already failed by the caller and needs no re-derivation. Anything unre-judgeable
    fails closed: a record naming a criterion the store does not carry, or a collapse
    list the file does not carry.

    :param records: the value under ``_skippedCriteria``.
    :param index: the store study's criteria, from :func:`criteria_index`.
    :param expression: the delivered file, read for its collapse records and for the
        unmapped list that says which siblings were themselves lost.
    :returns: one line per permit that does not hold; empty when every allowed skip
        re-derives.
    """
    if not isinstance(records, list):
        return [f"_skippedCriteria is not a list: {type(records).__name__}"]

    # Deferred, not module-scope: `src.api.models.tte` reaches `src.settings`, whose
    # import runs `load_dotenv()`, and every src.* import in this tree must stay behind
    # `resolve_store_path`. Imported from the model module rather than from
    # `tte_service`, which re-exports it from here.
    from src.api.models.tte import DEMOGRAPHIC_DOMAINS

    unmapped_records = expression.get("_unmappedCriteria") or []
    unmapped_keys = {
        (record.get("role"), str(record.get("criterionId") or ""))
        for record in unmapped_records
        if isinstance(record, dict)
    }
    skipped_by_key = {
        (record.get("role"), str(record.get("criterionId") or "")): record
        for record in records
        if isinstance(record, dict)
    }
    lost = unmapped_keys | set(skipped_by_key)

    violations: list[str] = []
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        reason = record.get("reason")
        if reason not in ALLOWED_SKIP_REASONS:
            continue
        where = f"_skippedCriteria[{position}] {_describe(record)}"
        role = record.get("role")
        criterion_id = str(record.get("criterionId") or "").strip()
        criterion = index.get((role, criterion_id))
        if criterion is None:
            violations.append(
                f"{where} names a criterion the store study does not carry, so its "
                f"{reason!r} permit cannot be re-judged"
            )
            continue

        if reason == "group-label":
            violations.extend(_group_label_violations(where, criterion, role, index, lost))
        elif reason == "demographic-no-rule":
            domain = (criterion.get("domain") or "").strip()
            if domain not in DEMOGRAPHIC_DOMAINS:
                violations.append(
                    f"{where} is recorded as demographic-no-rule but the store row's "
                    f"domain {domain!r} is not a demographic domain"
                )
            # Meaning-derived rather than a copy of `_build_demographic_rule`: the
            # permit says the row had NO usable bound, so a row that carried a number
            # the builder happened not to support is a lost age bound, not a container.
            constraint = criterion.get("valueConstraint")
            if isinstance(constraint, dict) and constraint.get("value") is not None:
                violations.append(
                    f"{where} is a demographic criterion carrying a bound {constraint!r} "
                    "recorded as demographic-no-rule: the producer had a number and "
                    "built no rule from it"
                )
        else:
            violations.extend(
                _collapse_violations(
                    where,
                    reason,
                    role,
                    criterion_id,
                    expression,
                    index,
                    unmapped_keys,
                    skipped_by_key,
                )
            )
    return violations


def criterion_accounting(
    expression: dict[str, Any], study: dict[str, Any]
) -> tuple[list[str], str]:
    """Re-judge a delivered file's own drop records: ``(violations, summary)``.

    The failure condition is ``unmapped > 0``, plus ``skipped > 0`` for any reason
    not in :data:`ALLOWED_SKIP_REASONS`, plus any allowed skip whose permit does not
    re-derive. ``skipped`` alone is not loss — see that constant for what is permitted
    and why — so a batch with 32 skips and nothing unmapped (the measured CAROLINA
    case) still passes, but only once each of those 32 has been reconciled against the
    store criterion it names and the collapse record in the file beside it.

    ``study`` is required and has no default. The reconciliation needs the store's
    criteria rows, and a missing store would silently turn every re-derivation into a
    no-op — which is the shape of amnesty this function exists to remove. A record the
    store cannot answer for fails closed instead.

    The balance identity ``total == mapped + unmapped + demographicRules + skipped``
    is asserted here against the DELIVERED file.
    ``tests/test_generation_census_accounts_for_every_criterion.py`` asserts it
    against the generator, which is a different claim: between the two the payload
    is pruned, deep-copied and written to disk, and nothing re-checked it at the
    boundary where it is handed to a site.

    ``summary`` is returned even when there are no violations, and the caller prints
    it on a passing row — a check whose only output is silence cannot be told from a
    check that never ran.
    """
    # The emission-time drop record, checked and reported on every path below. It is
    # NOT in ACCOUNTING_KEYS: those three are written together by the generator, so a
    # partial set means one was removed after the fact, while this fourth key is
    # written a stage later and is legitimately absent from any artifact exported
    # before it existed. Folding it into that set would fail every such artifact as
    # "incomplete" rather than reporting it as unrecorded.
    dropped = expression.get(DROPPED_CRITERIA_KEY)
    drop_violations = dropped_criteria_violations(dropped)
    if dropped is None:
        drop_clause = ""
    elif isinstance(dropped, list) and dropped:
        detail = "; ".join(
            str(record.get("summary") or record.get("rule"))
            for record in dropped
            if isinstance(record, dict)
        )
        drop_clause = f", {len(dropped)} dropped at emission ({detail})"
    else:
        drop_clause = ", 0 dropped at emission"

    present = [key for key in ACCOUNTING_KEYS if key in expression]
    if not present:
        # Every current export writes all three. An artifact carrying none of them
        # was built before the accounting existed, so the identity cannot be
        # evaluated at all; saying so on the row is the honest report. This is a
        # known hole -- a pre-accounting artifact is not verifiable here and still
        # passes -- and closing it means re-exporting rather than re-reading.
        return (
            drop_violations,
            "criterion accounting: NOT RECORDED "
            f"(artifact predates _generationCensus){drop_clause}",
        )

    missing = [key for key in ACCOUNTING_KEYS if key not in expression]
    if missing:
        return (
            drop_violations
            + [
                "criterion accounting incomplete: "
                f"{', '.join(missing)} absent while {', '.join(present)} present"
            ],
            f"criterion accounting: INCOMPLETE{drop_clause}",
        )

    census = expression["_generationCensus"] or {}
    unmapped = expression["_unmappedCriteria"] or []
    skipped = expression["_skippedCriteria"] or []

    violations: list[str] = list(drop_violations)

    total = census.get("total")
    parts = {
        "mapped": census.get("mapped"),
        "unmapped": census.get("unmapped"),
        "demographicRules": census.get("demographicRules"),
        "skipped": census.get("skipped"),
    }
    if total is None or any(value is None for value in parts.values()):
        violations.append(f"census is missing a counter: {census!r}")
    else:
        balance = sum(parts.values())
        if total != balance:
            violations.append(
                f"census does not balance: total={total} != "
                + " + ".join(f"{name} {value}" for name, value in parts.items())
                + f" = {balance}"
            )
        # The counters and the lists are two records of the same event, so they are
        # cross-checked rather than trusted individually: a stripped list with its
        # counter left behind balances perfectly and reads as clean.
        if parts["unmapped"] != len(unmapped):
            violations.append(
                f"census counter disagrees with its record list: unmapped={parts['unmapped']} "
                f"but _unmappedCriteria carries {len(unmapped)}"
            )
        if parts["skipped"] != len(skipped):
            violations.append(
                f"census counter disagrees with its record list: skipped={parts['skipped']} "
                f"but _skippedCriteria carries {len(skipped)}"
            )
        by_reason = census.get("skippedByReason") or {}
        if sum(by_reason.values()) != parts["skipped"]:
            violations.append(
                "census counter disagrees with its own breakdown: skippedByReason sums to "
                f"{sum(by_reason.values())}, skipped={parts['skipped']}"
            )
        mappable = census.get("mappable")
        if mappable is not None and mappable != parts["mapped"] + parts["unmapped"]:
            violations.append(
                f"census counter disagrees: mappable={mappable} != "
                f"mapped {parts['mapped']} + unmapped {parts['unmapped']}"
            )

    # The store's criteria, for the two re-derivations below. Built here rather than at
    # the top because the two early returns above (a pre-accounting artifact, an
    # incomplete record set) have nothing to reconcile.
    index = criteria_index(study)

    # Record integrity first, and on its own line: an unmapped row carrying no reason
    # at all is a different defect from the loss it also is, and no future allowlist
    # over reason strings could ever cover it.
    violations.extend(unmapped_criteria_violations(unmapped, index))

    if unmapped:
        # Every unmapped record is loss, whatever its reason says -- there is no
        # allowlist here and `unmapped_criteria_violations` deliberately builds none.
        # The producer records `"reason": str(e)`, which is empty for any exception
        # constructed without an argument -- 3 of the 13 distinct unmapped criteria
        # across every exported artifact carry `""` (ARISTOTLE 26/27, PLATO 16).
        # Saying "reason not recorded" rather than printing nothing keeps that gap
        # visible here until the producer records `repr(e)` and the class as well.
        details = []
        for record in unmapped:
            reason = str(record.get("reason") or "").strip()
            details.append(f"{_describe(record)} — {reason or 'reason not recorded'}")
        violations.append(f"unmapped criteria ({len(unmapped)}): " + "; ".join(details))

    off_list = [
        r for r in skipped if isinstance(r, dict) and r.get("reason") not in ALLOWED_SKIP_REASONS
    ]
    if off_list:
        violations.append(
            f"criteria skipped for a reason not on the allowlist ({len(off_list)}): "
            + "; ".join(f"{r.get('reason')!r} {_describe(r)}" for r in off_list)
        )

    # And the permits that ARE on the allowlist, re-derived rather than trusted.
    unreconciled = skipped_criteria_violations(skipped, index, expression)
    if unreconciled:
        violations.append(
            f"skips recorded under an allowed reason that does not hold "
            f"({len(unreconciled)}): " + "; ".join(unreconciled)
        )

    # "all permitted" now means permitted AND reconciled.
    notes = []
    if off_list:
        notes.append(f"{len(off_list)} not permitted")
    if unreconciled:
        notes.append(f"{len(unreconciled)} not reconciled")
    permitted = ", ".join(notes) if notes else "all permitted"
    summary = (
        f"criterion accounting: {census.get('mapped')} mapped, {len(unmapped)} unmapped, "
        f"{len(skipped)} skipped ({permitted}){drop_clause}"
    )
    return violations, summary


def _parse_map(raw: str) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        slug, _, study_id_str = part.partition("=")
        mapping[slug.strip()] = int(study_id_str.strip())
    return mapping


def _split_filename(path: Path) -> tuple[str, str] | None:
    """Return (slug, role) for '<slug>_treatment.circe.json' /
    '<slug>_comparator.circe.json', or None if the name doesn't match."""
    stem = path.name
    if stem.endswith(".circe.json"):
        stem = stem[: -len(".circe.json")]
    for role in ("treatment", "comparator"):
        suffix = f"_{role}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)], role
    return None


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rule_multiset_check(file_names: list[str], store_names: list[str]) -> tuple[bool, str]:
    file_counter = Counter(file_names)
    store_counter = Counter(store_names)
    missing = store_counter - file_counter
    extra = file_counter - store_counter
    missing_count = sum(missing.values())
    extra_count = sum(extra.values())
    if missing_count == 0 and extra_count <= 1:
        if extra_count == 0:
            detail = "matches store rule set"
        else:
            detail = f"matches + 1 extra ({next(iter(extra))!r})"
        return True, detail
    detail = f"missing={missing_count} extra={extra_count}"
    return False, detail


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path, help="Export directory to verify")
    parser.add_argument("--store", required=True, type=Path, help="Explicit studies.json path")
    parser.add_argument(
        "--map",
        default=DEFAULT_MAP,
        help='"slug=study_id,..." mapping from filename prefix to store study id',
    )
    parser.add_argument(
        "--allow-skeleton",
        action="store_true",
        help="Skip files with fewer than 2 InclusionRules instead of failing them",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # The same resolver the exporter runs, for the same reason and in the same
    # order. Check (c) below expects a treatment arm's entry to equal the store's
    # own DrugEra entry, which is only what a drug-anchored export produces; a gate
    # resolving a different mode from the exporter compares against the wrong
    # expected entry, which is worse than no gate at all.
    try:
        mode = resolve_drug_anchored_entry()
    except DeliveryModeConflictError as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2
    print(mode.summary(), file=sys.stderr)

    try:
        store_path = resolve_store_path(args.store)
    except (StoreMismatchError, FileNotFoundError) as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2

    slug_to_id = _parse_map(args.map)

    with store_path.open(encoding="utf-8") as fh:
        store_payload = json.load(fh)
    studies = store_payload.get("studies") if isinstance(store_payload, dict) else store_payload
    studies_by_id = {int(s["id"]): s for s in studies}

    circe_files = sorted(args.dir.glob("*.circe.json"))
    if not circe_files:
        print(f"No *.circe.json files found under {args.dir}", file=sys.stderr)
        return 1

    manifest_path = args.dir / "manifest.json"
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as fh:
            manifest = json.load(fh)

    rows: list[dict[str, Any]] = []
    any_fail = False
    produced_roles_by_study: dict[int, set[str]] = {}

    for path in circe_files:
        parsed = _split_filename(path)
        if parsed is None:
            rows.append(
                {
                    "file": path.name,
                    "status": "FAIL",
                    "reasons": ["filename does not match '<slug>_treatment|comparator.circe.json'"],
                }
            )
            any_fail = True
            continue
        slug, role = parsed

        with path.open(encoding="utf-8") as fh:
            expression = json.load(fh)

        skeleton_study_id = slug_to_id.get(slug)
        if skeleton_study_id in studies_by_id:
            produced_roles_by_study.setdefault(skeleton_study_id, set()).add(role)

        rules = rule_names(expression)
        if len(rules) < 2 and args.allow_skeleton:
            rows.append(
                {
                    "file": path.name,
                    "status": "SKIPPED",
                    "reasons": [f"skeleton ({len(rules)} rule(s)) — allowed via --allow-skeleton"],
                }
            )
            continue

        study_id = slug_to_id.get(slug)
        if study_id is None or study_id not in studies_by_id:
            rows.append(
                {
                    "file": path.name,
                    "status": "FAIL",
                    "reasons": [f"no --map entry (or no store study) for slug {slug!r}"],
                }
            )
            any_fail = True
            continue
        study = studies_by_id[study_id]
        produced_roles_by_study.setdefault(study_id, set()).add(role)
        comparison_mode = study.get("comparisonMode") or ""
        store_structured = (study.get("eligibility") or {}).get("structuredExpression") or {}
        store_rule_names = rule_names(store_structured)
        store_domain, store_concept_ids = entry_concept_ids(store_structured)
        study_arms = study.get("treatmentArms") or []
        comparator_arm_name = study_arms[1].get("name") if len(study_arms) > 1 else None

        reasons: list[str] = []

        # (a) no-op exclusion rules
        noops = noop_exclusion_rules(expression)
        if noops:
            reasons.append(f"no-op rules ({len(noops)}): {', '.join(noops)}")

        # (b) rule-name multiset vs store, allowing one extra. The store side is moved
        # forward by whatever the file's own drop records say the emission-time repair
        # did to it -- and by nothing else, so a rule missing without a record naming
        # it is still a mismatch.
        expected_rule_names, drop_reconcile_violations = reconcile_dropped_rules(
            expression, store_rule_names
        )
        reasons.extend(drop_reconcile_violations)
        rules_ok, rules_detail = _rule_multiset_check(rules, expected_rule_names)
        if not rules_ok:
            reasons.append(f"rule set mismatch: {rules_detail}")
        elif Counter(expected_rule_names) != Counter(store_rule_names):
            rules_detail += " (after recorded emission-time drops)"

        # (c) entry concept ids vs store, with the sanctioned comparator swaps
        file_domain, file_concept_ids = entry_concept_ids(expression)
        file_entry_name = entry_concept_set_name(expression)
        entry_ok = entry_matches_expected(
            file_domain,
            file_concept_ids,
            store_domain,
            store_concept_ids,
            is_comparator=(role == "comparator"),
            comparison_mode=comparison_mode,
            file_entry_name=file_entry_name,
            comparator_arm_name=comparator_arm_name,
        )
        if entry_ok:
            if (file_domain, file_concept_ids) == (store_domain, store_concept_ids):
                case = "exact match"
            elif file_domain == "ConditionOccurrence":
                case = "disease-anchored comparator swap (target_minus_treatment)"
            else:
                case = f"active-comparator drug entry ({file_entry_name!r} matches arm 2)"
        else:
            case = "FAIL"
            reasons.append(
                f"entry mismatch: file={file_domain} {sorted(file_concept_ids)} "
                f"store={store_domain} {sorted(store_concept_ids)}"
            )

        # (h) a disease-anchored comparator must enter on the trial's registered
        # condition, not on whichever Condition rule the file happens to carry.
        if entry_ok and file_domain == "ConditionOccurrence" and (
            (file_domain, file_concept_ids) != (store_domain, store_concept_ids)
        ):
            registered = (study.get("trialMetadata") or {}).get("conditions")
            try:
                expected_anchor = expected_anchor_concept_ids(store_structured, registered)
            except DiseaseAnchorError as exc:
                reasons.append(f"disease anchor unverifiable: {exc}")
            else:
                if file_concept_ids != expected_anchor:
                    reasons.append(
                        "disease anchor mismatch: file enters on "
                        f"{file_entry_name!r} {sorted(file_concept_ids)} but the trial's "
                        f"registered condition ({', '.join(repr(c) for c in registered or [])}) "
                        f"resolves to {sorted(expected_anchor)}"
                    )
                    case = "FAIL"

        # (f) a rule that excludes what the cohort enters on -- an empty cohort.
        contradictions = contradictory_absence_rules(expression)
        if contradictions:
            reasons.append(
                f"contradictory absence rules ({len(contradictions)}): "
                f"{', '.join(contradictions)}"
            )

        # (g) a criterion whose concept set shares no domain with the CDM table it
        # reads -- the join matches nothing, so an absence rule excludes nobody.
        domain_mismatches = domain_mismatched_criteria(expression)
        if domain_mismatches:
            reasons.append(
                f"criterion domain mismatch ({len(domain_mismatches)}): "
                f"{'; '.join(domain_mismatches)}"
            )

        # (i) the file's own drop records: recorded criterion loss, and whether the
        # census that reports it still balances on the delivered artifact.
        accounting_violations, accounting_summary = criterion_accounting(expression, study)
        reasons.extend(accounting_violations)

        # (d) manifest cross-check, if present
        if manifest is not None:
            manifest_entry = next(
                (f for f in manifest.get("files", []) if f.get("file") == path.name), None
            )
            if manifest_entry is None:
                reasons.append("manifest.json present but has no entry for this file")
            elif manifest_entry.get("md5") != _file_md5(path):
                reasons.append("manifest md5 does not match file on disk")
            manifest_store_sha = manifest.get("store_sha256")
            if manifest_store_sha is not None and manifest_store_sha != _file_sha256(store_path):
                reasons.append("manifest store_sha256 does not match --store file")

        status = "PASS" if not reasons else "FAIL"
        if status == "FAIL":
            any_fail = True
        rows.append(
            {
                "file": path.name,
                "status": status,
                # The accounting summary rides EVERY row, passing or failing. On a
                # passing row because a check that only ever speaks up on failure is
                # indistinguishable from a check that was never wired in -- which is
                # exactly how these keys went unread from the day they were written.
                # On a failing row because every file of the six-study batch fails on
                # recorded criterion loss, so a summary printed only on success would
                # never once have said what the emission-time repair removed.
                "reasons": (
                    reasons + [accounting_summary]
                    if reasons
                    else [f"entry: {case}; rules: {rules_detail}; {accounting_summary}"]
                ),
            }
        )

    # (e) arm completeness, across files rather than per file.
    id_to_slug = {study_id: slug for slug, study_id in slug_to_id.items()}
    for study_id in sorted(produced_roles_by_study):
        study = studies_by_id[study_id]
        missing = missing_arm_roles(study, produced_roles_by_study[study_id])
        for role in missing:
            slug = id_to_slug.get(study_id, str(study_id))
            rows.append(
                {
                    "file": f"{slug}_{role}.circe.json",
                    "status": "MISSING",
                    "reasons": [
                        f"study {study_id} declares arm {role!r} "
                        f"({[a.get('name') for a in study.get('treatmentArms') or []]}) "
                        "but no file was produced for it"
                    ],
                }
            )
            any_fail = True

    print(f"{'file':<40}  {'status':<8}  reasons")
    for row in rows:
        print(f"{row['file']:<40}  {row['status']:<8}  {'; '.join(row['reasons'])}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
