"""Pure lint functions over a CIRCE cohort expression dict.

No I/O and no WebAPI calls — every function here takes an already-parsed
expression dict and returns a plain value, so they are safe to unit test
with small inline fixtures instead of the multi-megabyte real store.

``noop_exclusion_rules`` exists to catch the 2026-08-31 defect class: an
``InclusionRules`` entry whose top-level expression is ``ANY`` over two or
more groups whose criteria are *all* absence occurrences
(``Occurrence: {Type: 0, Count: 0}``). "At least one of these things never
happened" is a near-vacuous filter compared to the intended "none of these
things happened" (an ``ALL`` over the same groups) — almost every patient
satisfies it, so the rule silently does nothing.
"""

from __future__ import annotations

from typing import Any

_ABSENT_OCCURRENCE = (0, 0)


def rule_names(expression: dict[str, Any]) -> list[str]:
    """Return the ``InclusionRules`` names, in file order."""
    return [rule.get("name", "") for rule in expression.get("InclusionRules") or []]


def _collect_occurrences(node: dict[str, Any]) -> list[tuple[Any, Any]]:
    """Recursively collect every ``(Occurrence.Type, Occurrence.Count)`` pair
    under a rule-expression node, descending into nested ``Groups``."""
    occurrences: list[tuple[Any, Any]] = []
    for criterion in node.get("CriteriaList") or []:
        occurrence = criterion.get("Occurrence") or {}
        occurrences.append((occurrence.get("Type"), occurrence.get("Count")))
    for group in node.get("Groups") or []:
        occurrences.extend(_collect_occurrences(group))
    return occurrences


def noop_exclusion_rules(expression: dict[str, Any]) -> list[str]:
    """Names of rules whose expression is ``ANY`` over >=2 groups whose
    criteria (recursively, including nested ``Groups``) are ALL absence
    occurrences (``Occurrence: {Type: 0, Count: 0}``).

    A rule with no criteria at all (vacuous groups) is not flagged — there is
    nothing to invert.
    """
    flagged: list[str] = []
    for rule in expression.get("InclusionRules") or []:
        rule_expression = rule.get("expression") or {}
        if rule_expression.get("Type") != "ANY":
            continue
        groups = rule_expression.get("Groups") or []
        if len(groups) < 2:
            continue
        occurrences = [occ for group in groups for occ in _collect_occurrences(group)]
        if occurrences and all(occ == _ABSENT_OCCURRENCE for occ in occurrences):
            flagged.append(rule.get("name", ""))
    return flagged


def _entry_domain_and_codeset(expression: dict[str, Any]) -> tuple[str, Any]:
    """Return ``(domain, codeset_id)`` for the ``PrimaryCriteria`` entry
    criterion, or ``("", None)`` when there is none."""
    primary_criteria = expression.get("PrimaryCriteria") or {}
    criteria_list = primary_criteria.get("CriteriaList") or []
    if not criteria_list:
        return "", None
    entry_criterion = criteria_list[0] or {}
    if not entry_criterion:
        return "", None
    domain = next(iter(entry_criterion))
    codeset_id = (entry_criterion.get(domain) or {}).get("CodesetId")
    return domain, codeset_id


def _find_concept_set(expression: dict[str, Any], codeset_id: Any) -> dict[str, Any] | None:
    if codeset_id is None:
        return None
    for concept_set in expression.get("ConceptSets") or []:
        if concept_set.get("id") == codeset_id:
            return concept_set
    return None


def entry_concept_ids(expression: dict[str, Any]) -> tuple[str, set[int]]:
    """Return ``(domain, concept_ids)`` for the ``PrimaryCriteria`` entry codeset.

    ``domain`` is the single domain key present on
    ``PrimaryCriteria.CriteriaList[0]`` (e.g. ``"DrugEra"``,
    ``"ConditionOccurrence"``). ``concept_ids`` are the ``CONCEPT_ID`` values
    of the ``ConceptSets`` entry whose ``id`` matches that criterion's
    ``CodesetId``.

    Returns ``("", set())`` when ``PrimaryCriteria`` carries no criterion or
    the referenced codeset cannot be found.
    """
    domain, codeset_id = _entry_domain_and_codeset(expression)
    if not domain:
        return "", set()

    concept_ids: set[int] = set()
    concept_set = _find_concept_set(expression, codeset_id)
    if concept_set is not None:
        items = (concept_set.get("expression") or {}).get("items") or []
        for item in items:
            concept_id = (item.get("concept") or {}).get("CONCEPT_ID")
            if concept_id is not None:
                concept_ids.add(int(concept_id))

    return domain, concept_ids


def entry_concept_set_name(expression: dict[str, Any]) -> str | None:
    """Return the ``name`` of the ``ConceptSets`` entry the ``PrimaryCriteria``
    entry criterion references, or ``None`` when it cannot be resolved.

    Used to recognize an active-comparator's own drug entry (built at export
    time from the study's second treatment-arm name) as distinct from the
    store's target-drug entry, which carries a different concept-set name.
    """
    domain, codeset_id = _entry_domain_and_codeset(expression)
    if not domain:
        return None
    concept_set = _find_concept_set(expression, codeset_id)
    if concept_set is None:
        return None
    name = concept_set.get("name")
    return name if isinstance(name, str) else None


def entry_matches_expected(
    file_domain: str,
    file_concept_ids: set[int],
    store_domain: str,
    store_concept_ids: set[int],
    *,
    is_comparator: bool,
    comparison_mode: str,
    file_entry_name: str | None = None,
    comparator_arm_name: str | None = None,
) -> bool:
    """True when a per-arm CIRCE's entry is an acceptable match for the
    study's store entry (the one shared entry point export_seeded_cohorts.py
    and verify_circe_delivery.py both gate on).

    A treatment/target arm's entry must equal the store's entry exactly
    (same domain, same concept ids) — that is the drug the study is anchored
    to, and a mismatch there is the exact 2026-08-31 defect class (a
    resolver landing on the wrong drug for a name like "BI 10773").

    A comparator arm has two sanctioned exceptions, both checked only when
    ``is_comparator`` is true:

    1. A disease-anchored ``ConditionOccurrence`` entry (the ADR-019/ADR-028
       placebo-comparator design) — the swap alone is not a violation.
    2. An **active comparator**'s own drug entry: a ``DrugEra`` set whose
       ``ConceptSets`` name equals (case-insensitive, stripped) the study's
       second ``treatmentArms`` name — e.g. CAROLINA's comparator entry is
       legitimately "glimepiride", not linagliptin, because the comparator
       arm IS glimepiride. This is checked independently of
       ``comparison_mode``: every real study observed so far (CAROLINA,
       ARISTOTLE, PLATO) carries ``comparisonMode: "target_minus_treatment"`
       even though its second arm is a genuine active drug, not a placebo —
       ``comparison_mode`` alone does not distinguish an active comparator
       from a placebo one; the arm name does. ``file_entry_name`` /
       ``comparator_arm_name`` are read via ``entry_concept_set_name`` and
       the store's ``treatmentArms[1]["name"]`` respectively by the caller.

    A treatment arm never gets either exception — only ``is_comparator``
    call sites can match them.
    """
    if file_domain == store_domain and file_concept_ids == store_concept_ids:
        return True
    if not is_comparator:
        return False
    if comparison_mode == "target_minus_treatment" and file_domain == "ConditionOccurrence":
        return True
    if (
        file_domain == "DrugEra"
        and file_entry_name is not None
        and comparator_arm_name is not None
        and file_entry_name.strip().lower() == comparator_arm_name.strip().lower()
    ):
        return True
    return False


# --- arm completeness -------------------------------------------------------
#
# Every other check in this module reads a file that exists. A delivery can also
# be wrong by being SHORT a file: the 2026-09-05 wiring-fix export wrote five
# CIRCE files and a manifest recording five, and passed the gate, while EMPA-REG
# carried only a treatment arm -- its comparator builder had raised and the
# exception was swallowed. Nothing looked for the absence.
#
# Both the exporter and the gate answer "which arms should exist" from here, so
# they cannot drift apart the way the two criterion walks in
# `_build_seeded_target_circe` did.

_ARM_ROLES_BY_INDEX = ("treatment", "comparator")


def expected_arm_roles(study: dict[str, Any]) -> list[str]:
    """The per-arm roles a study is expected to produce, from its own arm list.

    Arm 0 is the treatment cohort and arm 1 the comparator, which is the same
    convention the exporter uses when it names files. Reading the count from
    ``treatmentArms`` rather than assuming two is what lets a study that
    legitimately declares one arm pass without an opt-out flag -- a flag that
    let a delivery gate ignore a missing file would be a hole in the gate.
    """
    arms = study.get("treatmentArms") or []
    return list(_ARM_ROLES_BY_INDEX[: min(len(arms), len(_ARM_ROLES_BY_INDEX))])


def missing_arm_roles(study: dict[str, Any], produced_roles: Any) -> list[str]:
    """Expected arm roles with no produced file, in expected order.

    ``produced_roles`` is any iterable of role strings actually emitted for this
    study. An unexpected extra role is not reported here -- the filename and
    rule-set checks already cover a file that should not exist.
    """
    produced = set(produced_roles or ())
    return [role for role in expected_arm_roles(study) if role not in produced]


# --- self-contradictory cohorts ---------------------------------------------
#
# `No <drug>` requires zero occurrences of a concept set. When that set intersects
# the PrimaryCriteria entry set, the definition asks for people who both entered on
# a drug and never took it, and no person can satisfy it. CARMELINA shipped exactly
# that and passed every check here, because each existing check reads ONE property
# of a file and none of them compares the entry against what the rules exclude.
#
# Its cause was `_swap_primary_to_disease` early-returning under
# TTE_DRUG_ANCHORED_ENTRY, leaving the treatment DrugEra as the entry of a
# comparator whose whole job is to exclude that drug. Once the swap is applied to
# the placebo arm the entry is a Condition and this check no longer fires on a
# placebo comparator -- which is the point. It stays as the regression guard for
# the collision itself: if the swap is skipped again by a flag, a new anchor
# branch, or a study whose NCT enters the anchor table, the emptiness is caught at
# the gate rather than at a hospital.


def _absence_leaves_under_conjunction(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Absence leaves reachable through ``ALL`` nodes only.

    ``ANY`` means at least one alternative holds, so a single unsatisfiable
    alternative does not empty the rule; descending into one would produce false
    positives, which is the expensive direction for a delivery gate to be wrong in.
    """
    if (node.get("Type") or "ALL") != "ALL":
        return []
    found: list[dict[str, Any]] = []
    for entry in node.get("CriteriaList") or []:
        occurrence = entry.get("Occurrence") or {}
        if (occurrence.get("Type"), occurrence.get("Count")) == _ABSENT_OCCURRENCE:
            found.append(entry.get("Criteria") or entry)
    for group in node.get("Groups") or []:
        found.extend(_absence_leaves_under_conjunction(group))
    return found


def contradictory_absence_rules(expression: dict[str, Any]) -> list[str]:
    """Names of rules that exclude a concept set overlapping the cohort's own entry.

    Such a rule empties the cohort by construction. Overlap is tested on the literal
    concept ids of both sets: a descendant-level test would need the vocabulary, and
    this module is deliberately I/O-free, so the check is deliberately conservative
    -- it reports a contradiction it can prove from the file alone.

    A WINDOW ENDING AT INDEX IS NOT AN EXEMPTION, AND THIS WAS MEASURED. The obvious
    narrowing -- "only flag windows extending PAST index, since one ending at index is
    an ordinary prior-use washout" -- is wrong: CIRCE counts the index exposure itself.
    Three cohorts generated against WebAPI 2.15.1, source SYNTHEA (schema
    `synthea_cdm`), entry `DrugEra(19069022)` sodium fluoride, each a separate
    definition with its own design hash and "Cache is absent ... Calculating" in the
    WebAPI log:

        no inclusion rule                        10093 persons
        absence of the same drug, [-365, index]      0 persons
        absence of the same drug, [-365, index-1] 10093 persons

    So the boundary is exactly the index day, and a washout ending at `index+0` on a
    concept set containing the entry drug empties the cohort. Do not narrow this check
    to `End.Days > 0` on the intuition that a washout is harmless; re-run
    `output/site_gap/2026-09-05/circe_index_window_experiment.py` first.
    """
    _entry_domain, entry_ids = entry_concept_ids(expression)
    if not entry_ids:
        return []
    flagged: list[str] = []
    for rule in expression.get("InclusionRules") or []:
        for leaf in _absence_leaves_under_conjunction(rule.get("expression") or {}):
            codeset_id = None
            for _domain, body in leaf.items():
                if isinstance(body, dict) and "CodesetId" in body:
                    codeset_id = body["CodesetId"]
                    break
            if codeset_id is None:
                continue
            concept_set = _find_concept_set(expression, codeset_id)
            if concept_set is None:
                continue
            excluded = {
                item["concept"]["CONCEPT_ID"]
                for item in (concept_set.get("expression") or {}).get("items") or []
                if isinstance(item.get("concept"), dict)
                and isinstance(item["concept"].get("CONCEPT_ID"), int)
            }
            if excluded & entry_ids:
                flagged.append(rule.get("name", ""))
                break
    return flagged
