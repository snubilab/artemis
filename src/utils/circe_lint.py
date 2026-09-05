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


#: The ``StartWindow.End`` of a washout that stops the day before the index date.
#: ``{"Days": 1, "Coeff": -1}`` is index-1; ``{"Days": 0, "Coeff": 1}`` is index+0.
INDEX_EXCLUSIVE_END = {"Days": 1, "Coeff": -1}


def _absence_entries_under_conjunction(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Absence criteria ENTRIES reachable through ``ALL`` nodes only.

    An entry is the dict carrying ``Criteria``, ``StartWindow`` and ``Occurrence``
    together -- the whole entry rather than just its ``Criteria`` body, because the
    window boundary is what separates a prior-use washout from a self-contradiction
    and it lives one level up from the concept-set reference.

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
            found.append(entry)
    for group in node.get("Groups") or []:
        found.extend(_absence_entries_under_conjunction(group))
    return found


def _leaf_codeset_id(entry: dict[str, Any]) -> Any:
    """The ``CodesetId`` a criteria entry references, or ``None``.

    Tolerates an entry handed in already unwrapped (no ``Criteria`` key), which is
    the shape some hand-written fixtures use.
    """
    body_source = entry.get("Criteria")
    if not isinstance(body_source, dict):
        body_source = entry
    for _domain, body in body_source.items():
        if isinstance(body, dict) and "CodesetId" in body:
            return body["CodesetId"]
    return None


def _effective_end_days(entry: dict[str, Any]) -> float | None:
    """Days from the index date to the end of the entry's ``StartWindow``.

    ``None`` when that offset is not provable from the file: no window (unbounded),
    no explicit ``Days`` (also unbounded), a non-numeric value, or a window rebased
    by ``UseIndexEnd`` / ``UseEventEnd`` onto an era end date whose distance from the
    index date the file does not record. Every unprovable case is treated by the
    callers as "may contain the index day", so uncertainty never silences the check
    and never triggers a rewrite.
    """
    window = entry.get("StartWindow")
    if not isinstance(window, dict):
        return None
    if window.get("UseIndexEnd") or window.get("UseEventEnd"):
        return None
    end = window.get("End")
    if not isinstance(end, dict):
        return None
    days, coeff = end.get("Days"), end.get("Coeff")
    if isinstance(days, bool) or isinstance(coeff, bool):
        return None
    if not isinstance(days, (int, float)) or not isinstance(coeff, (int, float)):
        return None
    return days * coeff


def _colliding_absence_entries(
    expression: dict[str, Any], rule: dict[str, Any], entry_ids: set[int]
) -> list[dict[str, Any]]:
    """Absence entries in one rule whose excluded set shares a concept with the entry.

    Overlap is tested on the literal concept ids of both sets: a descendant-level test
    would need the vocabulary, and this module is deliberately I/O-free.
    """
    colliding: list[dict[str, Any]] = []
    for leaf_entry in _absence_entries_under_conjunction(rule.get("expression") or {}):
        codeset_id = _leaf_codeset_id(leaf_entry)
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
            colliding.append(leaf_entry)
    return colliding


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

    So the boundary is exactly the index day. THE ONE EXEMPTION IS THE ONE ARM 3
    MEASURED: a window that provably ends BEFORE the index day counts no entry
    exposure and returns the full population, so it is a sound prior-use washout and
    is not flagged. Everything else still is -- a window ending exactly ON index
    (`End.Days == 0`, the shape that shipped), a window running past it, an absence
    rule with no window at all, and any window whose end offset the file does not
    make provable. Do not widen that exemption to `End.Days > 0` on the intuition
    that a washout is harmless; re-run
    `output/site_gap/2026-09-05/circe_index_window_experiment.py` first.
    """
    _entry_domain, entry_ids = entry_concept_ids(expression)
    if not entry_ids:
        return []
    flagged: list[str] = []
    for rule in expression.get("InclusionRules") or []:
        for leaf_entry in _colliding_absence_entries(expression, rule, entry_ids):
            end_days = _effective_end_days(leaf_entry)
            if end_days is not None and end_days < 0:
                continue
            flagged.append(rule.get("name", ""))
            break
    return flagged


def end_entry_colliding_washouts_before_index(expression: dict[str, Any]) -> list[str]:
    """Move an absence window that ends ON the index day back to the day before it.

    Mutates ``expression`` in place and returns the names of the rules changed.

    Under a drug-anchored entry every entrant necessarily has a class exposure on the
    index day, because the index event IS an exposure to a drug in that class. A
    class-level washout whose concept set contains the entry drug therefore excludes
    people for the very event that admitted them, and the cohort is empty -- which is
    what `contradictory_absence_rules` reports and what arm 2 of the WebAPI experiment
    measured. Ending the window at `index-1` restores the intended reading ("no prior
    use of this class BEFORE the patient starts the study drug") and, per arm 3,
    the full population.

    Two things this deliberately does NOT do:

    - It does not subtract the study drug from its own class concept set. A patient
      who used linagliptin six months before index is not a new user and must stay
      excluded; removing the drug from the class set would admit prior users of the
      study drug and break the new-user design.
    - It does not touch a window running PAST the index day. That is not a boundary
      off-by-one -- it excludes people for taking the drug AFTER entry, which is a
      different rule with a different meaning (the 2026-08-31 `No <drug>` placebo
      collision had this shape, `[-180, +365]`). Silently moving it would rewrite the
      rule and leave `contradictory_absence_rules` with nothing left to fire on.

    Scope is the collision itself: an absence leaf reachable through `ALL` nodes only,
    whose excluded concept set shares a concept id with the entry set, and whose
    window provably ends on the index date. A study with no such rule does not move.
    """
    _entry_domain, entry_ids = entry_concept_ids(expression)
    if not entry_ids:
        return []
    changed: list[str] = []
    for rule in expression.get("InclusionRules") or []:
        moved = False
        for leaf_entry in _colliding_absence_entries(expression, rule, entry_ids):
            if _effective_end_days(leaf_entry) != 0:
                continue
            leaf_entry["StartWindow"]["End"] = dict(INDEX_EXCLUSIVE_END)
            moved = True
        if moved:
            changed.append(rule.get("name", ""))
    return changed


# --- criterion domain vs concept-set domain ---------------------------------
#
# A CIRCE criterion names the CDM table it reads. `ConditionOccurrence` joins
# `condition_occurrence.condition_concept_id` against the codeset; that column holds
# Condition-domain concepts and nothing else. Point such a criterion at a Drug concept
# set and the join matches no row — the rule is inert, and nothing in the file says so.
#
# CAROLINA shipped exactly that: `InclusionRules[22]` "Glimepiride", a
# `ConditionOccurrence` absence criterion over a concept set holding `1597756
# glimepiride`. Because it is an ABSENCE rule, matching nothing means EVERY patient
# satisfies it, so the exclusion is simply never applied and the cohort silently
# carries people it claims to exclude. That direction is the quiet one: a rule that
# empties a cohort is noticed at the first generation, a rule that excludes nobody
# never is.
#
# MEASURED, not reasoned — WebAPI 2.15.1, source SYNTHEA (`synthea_cdm`), six cohort
# definitions each with its own design hash and "Cache is absent ... Calculating" in
# the WebAPI log (`output/site_gap/2026-09-06/plan048_domain_repair/`):
#
#     entry only, no rule                                   10093 persons
#     acetaminophen via DrugExposure        (matching)       3339 persons
#     acetaminophen via ConditionOccurrence (MISMATCHED)        0 persons
#     Gingivitis    via ConditionOccurrence (matching)       5975 persons
#
# Arm 4 is the control that makes arm 3's zero mean something: the same criterion type
# over a Condition-domain set returns people, so `ConditionOccurrence` rules work and
# only the domain disagreement empties one. All four agree exactly with an independent
# SQL count over the same CDM. The arms are PRESENCE rules because zero-versus-non-zero
# is illegible under an absence rule, where matching nothing admits everyone.
#
# The check is deliberately conservative — a delivery gate is expensive to be wrong in.
# It fires only when EVERY concept in the set is outside the criterion's domains, and
# stays silent on an unmodelled criterion type, a dangling codeset reference, and a set
# with no readable domain. Each of those is an unknown, and a claim the check cannot
# establish from the file alone would be an unobserved defect claim.

#: The OMOP `domain_id` values a CIRCE criterion's own CDM table can hold. A criterion
#: type absent from this map is not checked rather than guessed at.
CRITERIA_TYPE_DOMAINS: dict[str, frozenset[str]] = {
    "ConditionOccurrence": frozenset({"Condition"}),
    "ConditionEra": frozenset({"Condition"}),
    "DrugExposure": frozenset({"Drug"}),
    "DrugEra": frozenset({"Drug"}),
    "DoseEra": frozenset({"Drug"}),
    "ProcedureOccurrence": frozenset({"Procedure"}),
    "Measurement": frozenset({"Measurement"}),
    "Observation": frozenset({"Observation"}),
    "DeviceExposure": frozenset({"Device"}),
    "VisitOccurrence": frozenset({"Visit"}),
    "VisitDetail": frozenset({"Visit"}),
    "Specimen": frozenset({"Specimen"}),
    # The death record carries a cause concept, which the vocabulary files under
    # either Condition or Observation.
    "Death": frozenset({"Condition", "Observation"}),
}

#: OMOP writes compound domains with abbreviations ("Condition/Meas",
#: "Measurement/Obs"). Expanded so a `Condition/Meas` concept — a real shape, 8
#: concepts in this vocabulary — counts for BOTH tables it is routed to.
_DOMAIN_ABBREVIATIONS = {"Meas": "Measurement", "Obs": "Observation"}


def _concept_set_domains(concept_set: dict[str, Any]) -> set[str]:
    """Every OMOP domain the set's concepts can be read from, compound ids split.

    An item with no readable ``DOMAIN_ID`` contributes nothing rather than a guess.
    """
    domains: set[str] = set()
    for item in (concept_set.get("expression") or {}).get("items") or []:
        raw = (item.get("concept") or {}).get("DOMAIN_ID")
        if not isinstance(raw, str):
            continue
        for part in raw.split("/"):
            part = part.strip()
            if part:
                domains.add(_DOMAIN_ABBREVIATIONS.get(part, part))
    return domains


def _criterion_references(body: dict[str, Any]) -> list[tuple[str, Any]]:
    """``(criteria_type, codeset_id)`` for every reference in one criterion body.

    Accepts both CIRCE shapes: an ``InclusionRules`` entry wrapping its body under
    ``Criteria``, and a ``PrimaryCriteria`` / ``CensoringCriteria`` entry that is the
    body itself.
    """
    inner = body.get("Criteria")
    if not isinstance(inner, dict):
        inner = body
    found: list[tuple[str, Any]] = []
    for criteria_type, payload in inner.items():
        if isinstance(payload, dict) and "CodesetId" in payload:
            found.append((criteria_type, payload["CodesetId"]))
    return found


def _walk_criteria_entries(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Every criterion entry under a group expression, descending nested groups.

    ``CorrelatedCriteria`` is followed too. No such node appears in the six files
    delivered so far, but CIRCE emits them and a gate that quietly skipped one would
    be a hole rather than a conservative choice.
    """
    entries: list[dict[str, Any]] = []
    for entry in node.get("CriteriaList") or []:
        if not isinstance(entry, dict):
            continue
        entries.append(entry)
        body = entry.get("Criteria")
        body = body if isinstance(body, dict) else entry
        for payload in body.values():
            if isinstance(payload, dict) and isinstance(
                payload.get("CorrelatedCriteria"), dict
            ):
                entries.extend(_walk_criteria_entries(payload["CorrelatedCriteria"]))
    for group in node.get("Groups") or []:
        if isinstance(group, dict):
            entries.extend(_walk_criteria_entries(group))
    return entries


def domain_mismatched_criteria(expression: dict[str, Any]) -> list[str]:
    """Locators for criteria whose concept set shares no domain with their CDM table.

    Each finding reads ``"<where>: <CriteriaType> over codeset <id> <name!r> (<domains>)"``
    so the gate output names the rule, the criterion and the offending domain without
    the reader reopening the file.

    Silent — by design — on the three cases the file cannot settle: a criterion type
    absent from :data:`CRITERIA_TYPE_DOMAINS`, a ``CodesetId`` with no matching
    ``ConceptSets`` entry, and a set whose concepts carry no ``DOMAIN_ID``. A set that
    mixes domains and includes the criterion's own is sound and is not flagged: one
    matching item is enough for the join to return rows.
    """
    locations: list[tuple[str, dict[str, Any]]] = []

    primary = expression.get("PrimaryCriteria") or {}
    for entry in primary.get("CriteriaList") or []:
        if isinstance(entry, dict):
            locations.append(("PrimaryCriteria", entry))

    additional = expression.get("AdditionalCriteria")
    if isinstance(additional, dict):
        for entry in _walk_criteria_entries(additional):
            locations.append(("AdditionalCriteria", entry))

    for rule in expression.get("InclusionRules") or []:
        rule_name = rule.get("name", "")
        for entry in _walk_criteria_entries(rule.get("expression") or {}):
            locations.append((rule_name, entry))

    for entry in expression.get("CensoringCriteria") or []:
        if isinstance(entry, dict):
            locations.append(("CensoringCriteria", entry))

    findings: list[str] = []
    for where, entry in locations:
        for criteria_type, codeset_id in _criterion_references(entry):
            allowed = CRITERIA_TYPE_DOMAINS.get(criteria_type)
            if allowed is None:
                continue
            concept_set = _find_concept_set(expression, codeset_id)
            if concept_set is None:
                continue
            domains = _concept_set_domains(concept_set)
            if not domains or domains & allowed:
                continue
            findings.append(
                f"{where}: {criteria_type} over codeset {codeset_id} "
                f"{concept_set.get('name')!r} ({', '.join(sorted(domains))})"
            )
    return findings
