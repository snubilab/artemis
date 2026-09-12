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

import re
from collections.abc import Mapping, Sequence
from typing import Any

# Importing the refusal vocabulary keeps this module pure: `criterion_refusal` has no
# I/O and no imports of its own beyond `__future__`. The codes live there and nowhere
# else -- a code retyped at a raise site is a code that eventually gets retyped wrong,
# and the mismatch is silent at the gate rather than loud here.
from src.utils.criterion_refusal import (
    REFUSAL_DOMAIN_CONTRADICTION,
    REFUSAL_UNREADABLE_VALUE_FILTER,
    CriterionRefused,
)

# Same purity contract as `criterion_refusal` above: `naming_words` has no I/O and no
# imports beyond `re`. It lives outside `src/agents/planner/decomposer.py`, which owns
# the other caller, precisely so this module does not pull the model stack in.
from src.utils.naming_words import naming_words

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


def entry_concept_set(expression: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ``ConceptSets`` entry the ``PrimaryCriteria`` entry references.

    Returns ``None`` when there is no entry criterion, the codeset cannot be
    found, or the set has no items. Domain filtering (Drug vs Condition) is
    the caller's job — this is the resolved set, not a clinical choice.
    """
    _domain, codeset_id = _entry_domain_and_codeset(expression)
    concept_set = _find_concept_set(expression, codeset_id)
    if concept_set is None:
        return None
    if not (concept_set.get("expression") or {}).get("items"):
        return None
    return concept_set


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


def _conjoined_entries(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Criteria ENTRIES reachable through ``ALL`` nodes only.

    An entry is the dict carrying ``Criteria``, ``StartWindow`` and ``Occurrence``
    together -- the whole entry rather than just its ``Criteria`` body, because the
    window boundary is what separates a prior-use washout from a self-contradiction
    and it lives one level up from the concept-set reference.

    ``ANY`` means at least one alternative holds, so a single unsatisfiable
    alternative does not empty the rule; descending into one would produce false
    positives, which is the expensive direction for a delivery gate to be wrong in.

    One home for the descent, because two readers disagreeing about which nodes are
    mandatory is how a gate goes quiet on half a file:
    :func:`_absence_entries_under_conjunction` and
    :func:`contradictory_presence_absence_criteria` both read it.
    """
    if (node.get("Type") or "ALL") != "ALL":
        return []
    found: list[dict[str, Any]] = list(node.get("CriteriaList") or [])
    for group in node.get("Groups") or []:
        found.extend(_conjoined_entries(group))
    return found


def _absence_entries_under_conjunction(node: dict[str, Any]) -> list[dict[str, Any]]:
    """The :data:`_ABSENT_OCCURRENCE` entries among :func:`_conjoined_entries`."""
    return [
        entry
        for entry in _conjoined_entries(node)
        if ((entry.get("Occurrence") or {}).get("Type"),
            (entry.get("Occurrence") or {}).get("Count")) == _ABSENT_OCCURRENCE
    ]


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


# --- the window a criterion gets when the extraction carried none -----------
#
# `window` is MANDATORY in the extraction prompt and the model omits it anyway: 57 of
# the 557 criteria in `tmp/tte_cold6_20260908/studies.json` (10%) carry `window: null`,
# in nine of the ten studies. So the emitter needs a default, and until 2026-09-10 it
# had an unnamed one -- a flat 365-day lookback applied to every domain alike, written
# as a literal at the emit site in `tte_service._build_seeded_eligibility_rule` while
# `agent1/prompts.NCT_SYSTEM_PROMPT` documented four DIFFERENT per-domain values to the
# model. The same decision had two homes that disagreed, and the emitter's won silently
# whenever the model did what the prompt says it must not.
#
# It was wrong in BOTH directions, measured on one ARISTOTLE pair -- both
# `ConditionOccurrence` exclusions in the same delivered file
# (`output/site_gap/2026-09-09/deliver_v3/aristotle_treatment.circe.json`):
#
#     Active infective endocarditis        Start = 9999d   window present in the store
#     Prosthetic mechanical heart valve    Start =  365d   window null -> flat default
#
# A prosthetic mechanical heart valve is permanent. "Implanted within the last 365
# days" excludes almost nobody, so that exclusion was effectively not applied and the
# cohort silently admitted patients the protocol excludes. Narrowing is the quiet
# direction -- the same asymmetry the domain check above is built around. In the other
# direction a Measurement got 365 where the documented default is 180, widening a lab
# window past what the protocol would recognise.
#
# The values are the ones the extraction prompt already documents, and they are keyed
# by OMOP domain because that is the vocabulary the prompt, the extraction and the
# clinical judgement all speak: how long a Condition stays true is a fact about
# conditions, not about the CIRCE table that happens to read them.

#: The `window` a criterion is emitted with when the extraction carried none, per OMOP
#: domain, in the IR's own `{"start": <negative days>, "end": 0}` shape so the emitter
#: runs ONE conversion to CIRCE `Start`/`End` for defaulted and extracted windows alike.
#:
#: These four numbers have exactly one home, and all three readers come here for them:
#: `agent1/prompts.py` renders its four statements of them from this table
#: (`render_default_window_prompt_line`) rather than retyping them; the emitter
#: `TTEService._build_seeded_target_circe` reads it through `default_criterion_window`;
#: and so does the IR pipeline's own builder, `CohortAssembler._start_window`. A fourth
#: copy is the defect, not the fix -- when the assembler carried its own, the two
#: disagreed on Drug and Measurement and nothing compared them.
#:
#: 9999 days is "all prior history" (~27 years) -- the flat value the assembler used
#: for EVERY domain until 2026-09-10, which is why Condition and Procedure are
#: byte-identical across that change and only Drug and Measurement moved.
DEFAULT_WINDOW_START_DAYS_BY_DOMAIN: dict[str, int] = {
    "Condition": -9999,
    "Drug": -365,
    "Measurement": -180,
    "Procedure": -9999,
}

#: The lookback for a domain the table above does not list -- Observation, Visit,
#: Device, Death, and anything the vocabulary adds later.
#:
#: This is a JUDGEMENT, not a documented value: the extraction prompt states defaults
#: for four domains and is silent on the rest. "All prior history" is the honest reading
#: of a protocol that stated no time frame, and it is the only choice that cannot
#: silently NARROW a criterion the protocol left unbounded -- the failure direction that
#: produced the ARISTOTLE defect above and the one no generated cohort makes visible. A
#: too-wide window shrinks the cohort, which is loud; a too-narrow exclusion admits
#: people it claims to exclude, which is not.
#:
#: Unreached by the measured batch: of the 57 null-window criteria in the cold-6 store,
#: every one is Condition (20), Drug (15), Measurement (10), Procedure (2) or
#: Demographics (10) -- and Demographics criteria build demographic rules, not
#: occurrence criteria. The 15 Observation criteria all carry a window. So this constant
#: is a guard against a shape not yet observed, and the record below is what would
#: surface it if one arrives.
DEFAULT_WINDOW_START_DAYS_UNLISTED_DOMAIN = -9999

#: The key `TTEService._build_seeded_target_circe` writes the defaulted-window records
#: under. Spelled once and imported by every reader, for the reason
#: :data:`DROPPED_CRITERIA_KEY` is.
#:
#: A defaulted window used to be indistinguishable from an extracted one: the emitted
#: file records a `StartWindow` and nothing about where it came from, so the ARISTOTLE
#: pair above reads as two deliberate clinical choices rather than one choice and one
#: fallback. Same present-and-empty contract as `_droppedCriteria` / `_unmappedCriteria`
#: -- an absent key would be indistinguishable from a clean run on an artifact built
#: before this.
DEFAULTED_WINDOW_CRITERIA_KEY = "_defaultedWindowCriteria"

#: `source` on a defaulted-window record: the domain was in
#: :data:`DEFAULT_WINDOW_START_DAYS_BY_DOMAIN` and its documented value was used.
DEFAULT_WINDOW_SOURCE_DOMAIN_TABLE = "domain-default"
#: `source` on a defaulted-window record: the domain was NOT in the table, so
#: :data:`DEFAULT_WINDOW_START_DAYS_UNLISTED_DOMAIN` was used. A row carrying this is
#: the signal that a domain needs a documented value, not a judged one.
DEFAULT_WINDOW_SOURCE_UNLISTED_DOMAIN = "unlisted-domain-default"


def default_criterion_window(domain: str | None) -> tuple[dict[str, int], str]:
    """The `window` to emit for a criterion whose extraction carried none.

    :param domain: the criterion's OMOP domain, as resolved at the emit site. Empty or
        ``None`` counts as unlisted -- an absent domain is not evidence of a short one.
    :returns: ``({"start": <negative days>, "end": 0}, source)`` where ``source`` is
        :data:`DEFAULT_WINDOW_SOURCE_DOMAIN_TABLE` or
        :data:`DEFAULT_WINDOW_SOURCE_UNLISTED_DOMAIN`. The source travels with the value
        so the caller can record WHICH default it applied without re-deriving it from
        the number -- two domains share -9999, so the number alone does not say.
    """
    key = (domain or "").strip()
    if key in DEFAULT_WINDOW_START_DAYS_BY_DOMAIN:
        return (
            {"start": DEFAULT_WINDOW_START_DAYS_BY_DOMAIN[key], "end": 0},
            DEFAULT_WINDOW_SOURCE_DOMAIN_TABLE,
        )
    return (
        {"start": DEFAULT_WINDOW_START_DAYS_UNLISTED_DOMAIN, "end": 0},
        DEFAULT_WINDOW_SOURCE_UNLISTED_DOMAIN,
    )


def render_default_window_prompt_line(
    groups: Sequence[Sequence[str]], *, escape_braces: bool = False
) -> str:
    """Render the per-domain defaults as the extraction prompts state them.

    The prompts are strings, so they cannot import a number -- but they can be BUILT
    from one. This renders the sentence fragment each prompt already carried, from
    :data:`DEFAULT_WINDOW_START_DAYS_BY_DOMAIN`, so the four statements of these values
    across `agent1/prompts.py` stop being four copies to keep in step with the emitter.

    Byte-identity with the text those prompts carried before is deliberate and is what
    `groups` and `escape_braces` exist for. `NCT_SYSTEM_PROMPT` and the rendered
    `NCT_DECOMPOSITION_PROMPT` are both hashed into the Agent 1 IR cache key
    (`agent1/parser.py`), so rewording them re-runs extraction for every trial in
    `data/cache/agent1_ir`. The cost of that is measured in GPU hours and buys nothing
    here: the defect was retyped NUMBERS, not divergent prose. The tradeoff is that this
    function carries two presentation shapes it would not need if the four prompts
    agreed on wording -- unifying them is a separate change, and a cache-invalidating one.

    :param groups: domains in render order; a group of more than one renders as
        ``"A/B"`` and every member must share a value, so splitting one domain's default
        without the other raises here instead of rendering a false claim to the model.
    :param escape_braces: double the braces, for a prompt consumed by ``str.format``.
    :returns: e.g. ``"Condition -> {start: -9999, end: 0}, Drug -> ..."`` (arrow is U+2192).
    :raises KeyError: a named domain has no documented default.
    :raises ValueError: a collapsed group's members do not share a value.
    """
    open_brace, close_brace = ("{{", "}}") if escape_braces else ("{", "}")
    parts: list[str] = []
    for group in groups:
        values = {DEFAULT_WINDOW_START_DAYS_BY_DOMAIN[domain] for domain in group}
        if len(values) != 1:
            raise ValueError(
                f"cannot render {'/'.join(group)} as one default: "
                + ", ".join(
                    f"{d}={DEFAULT_WINDOW_START_DAYS_BY_DOMAIN[d]}" for d in group
                )
            )
        start = values.pop()
        parts.append(
            f"{'/'.join(group)} → {open_brace}start: {start}, end: 0{close_brace}"
        )
    return ", ".join(parts)


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


def concept_set_domains(concept_set: dict[str, Any]) -> set[str]:
    """Every OMOP domain the set's concepts can be read from, compound ids split.

    An item with no readable ``DOMAIN_ID`` contributes nothing rather than a guess.

    Public because the generator asks the same question one step earlier, before a
    criterion is emitted (:func:`refuse_domain_contradiction`): the delivery gate
    and the generator must read a concept set's domains the same way or the generator can
    emit a shape the gate then rejects.

    :param concept_set: anything carrying ``expression.items[].concept.DOMAIN_ID`` —
        a CIRCE ``ConceptSets`` entry or a mapper answer in the same shape.
    :returns: the domain ids, with compound ids such as ``Condition/Meas`` split into both.
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


def refuse_domain_contradiction(
    criteria_key: str, mapped_criterion: dict[str, Any], label: str
) -> None:
    """Raise when the mapped concept set cannot be read from the criterion's own table.

    A criterion carries two independent answers about its domain: the one it declares,
    which picks the CDM table, and the one the mapper returns with the concept set.
    Nothing compared them, so a mapper answer from another domain was written into a
    criterion that cannot read it and the rule matched no row at all.

    CAROLINA is the measured case. Store study 10, `exclusionCriteria` id 25 declares
    `domain = "Condition"` for "Hypersensitivity to investigational product or
    glimepiride", but its `sourceText` had already lost the head noun down to
    "Glimepiride", so the mapper answered with glimepiride Drug products. The emitted
    `ConditionOccurrence` rule returns 0 persons where the same criterion over a
    Condition set returns 5,975 of 10,093 -- and because it is an ABSENCE rule,
    matching nothing means the exclusion is never applied to anybody.

    This is :func:`domain_mismatched_criteria` applied one step earlier, against
    the same :data:`CRITERIA_TYPE_DOMAINS` table, so the generator stops producing what
    the delivery gate will reject. Raising rather than emitting is deliberate: the
    caller records the criterion in `_unmappedCriteria` with this reason and drops it,
    which leaves the rule honestly absent instead of present and vacuous.

    Silent on the two cases the mapping cannot settle, for the same reason the
    delivery gate is: a criteria type absent from the table, and a concept set whose
    items carry no readable `DOMAIN_ID`.

    :param criteria_key: the CIRCE criteria type the rule will be emitted under.
    :param mapped_criterion: the mapper's answer, in the seeded-concept-set shape.
    :param label: the seed the mapper was asked about, for the recorded reason.
    :raises CriterionRefused: when the set's domains and the table's are disjoint,
        carrying :data:`~src.utils.criterion_refusal.REFUSAL_DOMAIN_CONTRADICTION`.
        A bare ``ValueError`` here recorded ``refusalCode: None``, which every consumer
        reads as "nothing deliberately refused" -- i.e. as a FAILURE -- and this is the
        opposite: the mapping was looked at and rejected on purpose.
    """
    allowed = CRITERIA_TYPE_DOMAINS.get(criteria_key)
    if allowed is None:
        return
    domains = concept_set_domains(mapped_criterion)
    if not domains or domains & allowed:
        return
    raise CriterionRefused(
        f"criterion domain contradiction: {criteria_key} reads "
        f"{'/'.join(sorted(allowed))} but the concept set mapped for {label!r} "
        f"holds only {', '.join(sorted(domains))} concepts, so the rule would match "
        f"nothing",
        code=REFUSAL_DOMAIN_CONTRADICTION,
        detail=f"{criteria_key} vs {', '.join(sorted(domains))}",
    )


# --------------------------------------------------------------------------
# Value-condition attributes a criteria type can actually read
# --------------------------------------------------------------------------
#
# `build_measurement_value_filter` returns a flat Circe fragment, and all three
# callers merged it onto whatever criteria type the domain mapping had chosen:
#
#     criteria_attrs.update(build_measurement_value_filter(vc))
#
# Nothing asked whether that type's CDM table has the columns. Over the twelve
# files of `output/site_gap/2026-09-08/deliver_20260908/`, 10 criteria in 8 files
# carried a filter their table cannot read -- DrugExposure+ValueAsNumber x6,
# ConditionOccurrence+Unit+ValueAsNumber x2, ProcedureOccurrence+Unit+ValueAsNumber
# x2 -- alongside 108 that were read correctly. Circe silently ignores the
# attribute, so each of those 10 rules matched every occurrence of its concept set
# while reading as though it were filtered: "aspirin > 165 mg" excluded everyone on
# any aspirin at all.
#
# The table below was MEASURED, not derived from the CDM schema. Each cell is one
# expression POSTed twice to the live `WebAPI /cohortdefinition/sql` -- once with the
# attribute, once without -- with the attribute recorded as readable only when the
# rendered SQL differed. Two entries would have been wrong by reasoning alone:
# `Specimen` reads `Unit` but not `ValueAsNumber`, and `ProcedureOccurrence` reads
# `Quantity` while reading no other value attribute.
#
# Independent corroboration: across the 18 TROY v1.1 CIRCE files under `data/gold/`,
# a value attribute appears on `Measurement` and on no other criteria type.

#: The value-condition keys this gate is willing to judge. A key outside it is
#: passed over rather than guessed at, the same conservatism
#: :data:`CRITERIA_TYPE_DOMAINS` applies to an unmodelled criteria type.
#: `ValueAsString` is deliberately absent: the probe for it was rejected by WebAPI
#: with HTTP 400, so whether a type reads it was never established.
VALUE_CONDITION_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "Abnormal",
        "Qualifier",
        "Quantity",
        "RangeHigh",
        "RangeHighRatio",
        "RangeLow",
        "RangeLowRatio",
        "Unit",
        "ValueAsConcept",
        "ValueAsNumber",
    }
)

#: Criteria type -> the members of :data:`VALUE_CONDITION_ATTRIBUTES` whose presence
#: changes the SQL Circe renders for that type. A type absent from this map is not
#: checked rather than guessed at.
CRITERIA_TYPE_VALUE_ATTRIBUTES: dict[str, frozenset[str]] = {
    "Measurement": frozenset(
        {
            "Abnormal",
            "RangeHigh",
            "RangeHighRatio",
            "RangeLow",
            "RangeLowRatio",
            "Unit",
            "ValueAsConcept",
            "ValueAsNumber",
        }
    ),
    # OBSERVATION has no range_low/range_high, so the two ratio bounds render
    # identical SQL here and a "> 3x ULN" written on an Observation is lost.
    "Observation": frozenset({"Qualifier", "Unit", "ValueAsConcept", "ValueAsNumber"}),
    "Specimen": frozenset({"Quantity", "Unit"}),
    "DoseEra": frozenset({"Unit"}),
    "DrugExposure": frozenset({"Quantity"}),
    "ProcedureOccurrence": frozenset({"Quantity"}),
    "DeviceExposure": frozenset({"Quantity"}),
    "ConditionOccurrence": frozenset(),
    "ConditionEra": frozenset(),
    "DrugEra": frozenset(),
    "VisitOccurrence": frozenset(),
    "VisitDetail": frozenset(),
    "Death": frozenset(),
}


def unreadable_value_attributes(
    criteria_type: str, criteria_body: Mapping[str, Any]
) -> list[str]:
    """Value attributes on this criterion that its own CDM table cannot read.

    The one predicate behind every surface below, so the generation-time refusal,
    the delivery gate and the emission-time repair cannot drift apart.

    :param criteria_type: the CIRCE criteria type key, e.g. ``"DrugExposure"``.
    :param criteria_body: that key's payload -- the dict holding ``CodesetId``.
    :returns: sorted attribute names, empty when the type reads all of them, when
        it carries none, or when the type is absent from
        :data:`CRITERIA_TYPE_VALUE_ATTRIBUTES`.
    """
    readable = CRITERIA_TYPE_VALUE_ATTRIBUTES.get(criteria_type)
    if readable is None:
        return []
    return sorted(
        key
        for key in criteria_body
        if key in VALUE_CONDITION_ATTRIBUTES and key not in readable
    )


def refuse_unreadable_value_filter(
    criteria_key: str, value_fragment: Mapping[str, Any], label: str
) -> None:
    """Raise when a value filter is about to be merged onto a type that ignores it.

    The generation-time half of the gate, and deliberately the same shape as
    :func:`refuse_domain_contradiction`: raising rather than merging leaves the
    caller to record the criterion under its own refusal reason and drop it, so the
    claim is honestly absent instead of present and wrong.

    Emitting the criterion with the attribute *stripped* is not the alternative it
    looks like. Circe already ignores the attribute, so stripping selects exactly
    the same patients -- it only stops the file from advertising a filter it never
    applied, which leaves an over-broad rule in place and no record that it is one.

    :param criteria_key: the CIRCE criteria type the rule will be emitted under.
    :param value_fragment: what :func:`build_measurement_value_filter` returned.
    :param label: the criterion's seed text, for the recorded reason.
    :raises CriterionRefused: when the fragment holds an attribute the type cannot
        read, carrying
        :data:`~src.utils.criterion_refusal.REFUSAL_UNREADABLE_VALUE_FILTER`. Same
        reason as :func:`refuse_domain_contradiction`: a bare ``ValueError`` recorded
        ``refusalCode: None``, which reads as a failure rather than the deliberate
        verdict it is.
    """
    unreadable = unreadable_value_attributes(criteria_key, value_fragment)
    if not unreadable:
        return
    raise CriterionRefused(
        f"criterion value filter unreadable: {criteria_key} cannot read "
        f"{', '.join(unreadable)}, so the value condition written for {label!r} "
        f"would be dropped by Circe and the rule would match every occurrence "
        f"of its concept set",
        code=REFUSAL_UNREADABLE_VALUE_FILTER,
        detail=f"{criteria_key} cannot read {', '.join(unreadable)}",
    )


def unreadable_value_filter_criteria(expression: dict[str, Any]) -> list[str]:
    """Locators for criteria carrying a value filter their CDM table cannot read.

    The delivery-gate half, in the same locator format
    :func:`domain_mismatched_criteria` uses::

        "<where>: <CriteriaType> carries <attrs> over codeset <id>"

    Reports every section including ``PrimaryCriteria``, which
    :func:`drop_unreadable_value_criteria` deliberately does not repair.
    """
    findings: list[str] = []
    for where, entry in _criterion_locations(expression):
        body = entry.get("Criteria")
        body = body if isinstance(body, dict) else entry
        for criteria_type, payload in body.items():
            if not isinstance(payload, dict):
                continue
            unreadable = unreadable_value_attributes(criteria_type, payload)
            if unreadable:
                findings.append(
                    f"{where}: {criteria_type} carries {', '.join(unreadable)} "
                    f"over codeset {payload.get('CodesetId')}"
                )
    return findings


# --------------------------------------------------------------------------
# A bound the name asserts and the criterion does not carry
# --------------------------------------------------------------------------
#
# `unreadable_value_filter_criteria` above catches a filter PRESENT on a type that
# cannot read it. Nothing caught a filter that is simply ABSENT -- and a rule that
# lost its threshold is byte-indistinguishable from a rule that legitimately never
# had one, which is why this shipped.
#
# Measured, verbatim, from `output/site_gap/2026-09-08/deliver_20260908/`
# (`carolina_treatment.circe.json`), all three `Occurrence {Type: 0, Count: 0}`:
#
#     rule 30  ALT(36) AST(37) ALP(38)                         keys=['RangeHighRatio']
#     rule 33  T4(49) T3(50) TSH(51)                           keys=[]
#     rule 37  'Elevated ALT'(71) ... 'Coagulopathy...INR'(74) keys=[]
#
# Rule 30 is correct -- "3x ULN" survived as a RangeHighRatio. Rules 33 and 37 lost
# their bound, so rule 37 excludes any patient who has ever had an ALT, AST, bilirubin
# or INR drawn: routine panel labs, which in a T2DM cohort is effectively everyone.
# The gate reported the file as "78 mapped, 0 unmapped, 32 skipped": the bare members
# are counted as MAPPED and nothing anywhere flagged them.
#
# The predicate is structural on one side and a heuristic over English on the other,
# and it is worth being precise about which is which. That the criterion carries NO
# value attribute is structural and exact. Whether the name ASSERTS a bound is the
# heuristic, and it is the only guessed half.
#
# So the vocabulary below is grounded rather than imagined. Measured over the 12
# delivered files (136 Measurement criteria, 32 of them bare) and, independently, over
# the 18 hand-built TROY v1.1 files under `data/gold/` (85 Measurement criteria, 4 bare):
#
#     09-08 batch   26 of 32 bare criteria fire -- exactly the 26 known lost bounds
#                   (CAROLINA T4/T3/TSH 49-51, HbA1c/FPG/RPG 66-68,
#                   ALT/AST/bili/INR 71-74; EMPA-REG FPG/RPG/HbA1c 57-59, x2 arms)
#     gold          4 of 4 bare criteria fire, and all four are TRUE: ARISTOTLE's
#                   `Persistent, uncontrolled hypertension (systolic BP > 180 mm Hg,
#                   or diastolic BP > 100 mm Hg)` emits `{CodesetId: 98}` and
#                   `{CodesetId: 99}` with no bound at all. The hand-built corpus
#                   carries the same defect, and nobody was looking for it.
#
# 30 firings across two independent corpora, 30 true positives, 0 false. The 6 bare
# criteria that do NOT fire are right not to: "Asymptomatic cardiac ischemia",
# "ECG Ischemia" and "Positive biomarker" assert no numeric bound.
#
# Two terms were MEASURED AND REJECTED, and they are the reason this list is shorter
# than an intuitive one. `high` and `low` appear in Measurement names only as parts of
# an analyte's own name -- "Low-density lipoprotein (LDL) cholesterol",
# "High-density lipoprotein" -- and inside the composite rule "High risk of CV events",
# which asserts no lab bound. Matching them as bare words is precisely the
# false-positive shape this check must not have. `severe` is rejected for the same
# reason: in this corpus it qualifies a condition ("Severe renal insufficiency"), and
# every occurrence sits on a criterion that is correctly filtered already.

#: Words and symbols that assert a numeric bound on a measurement.
#:
#: Attested on real defects: ``elevated`` / ``elevation`` (20 of the 26),
#: ``impaired`` (8 of the 26), ``level`` (6 of the 26), ``uncontrolled`` and the
#: comparator symbols (the 4 gold rows), ``ULN`` / ``LLN`` (both corpora, on rules
#: whose bound survived).
#:
#: ``raised``, ``increased``, ``decreased``, ``reduced``, ``depressed`` and
#: ``abnormal`` are NOT attested in either corpus. They are here as the direct
#: synonyms and the symmetric counterparts of ``elevated``: a detector that fires on
#: a lost upper bound and stays silent on a lost lower one has a hole by construction,
#: not a conservative margin.
_BOUND_ASSERTION_RE = re.compile(
    r"\belevat(?:ed|ion|ions)\b"
    r"|\braised\b|\bincreased\b"
    r"|\bdecreased\b|\breduced\b|\bdepressed\b"
    r"|\babnormal\b|\bimpaired\b|\buncontrolled\b"
    r"|\blevels?\b"
    r"|\bULN\b|\bLLN\b"
    r"|[<>≤≥]",
    re.IGNORECASE,
)

#: The one criteria type this check judges. Every value attribute that can carry a
#: numeric bound with a direction -- ``RangeHigh``, ``RangeLow`` and their ratio forms
#: -- is readable ONLY by ``Measurement`` (see
#: :data:`CRITERIA_TYPE_VALUE_ATTRIBUTES`), so a lost bound on any other type is a
#: different defect with a different repair and is deliberately out of scope here
#: rather than guessed at.
_BOUND_BEARING_CRITERIA_TYPE = "Measurement"


def asserted_bound_missing_criteria(expression: dict[str, Any]) -> list[str]:
    """Locators for criteria whose own name asserts a bound they do not carry.

    In the same locator format :func:`unreadable_value_filter_criteria` uses::

        "<where>: Measurement over codeset <id> <name!r> carries no value condition
         while <what asserted the bound> asserts one (<matched term>)"

    A criterion qualifies when BOTH halves hold:

    * it carries no key from :data:`VALUE_CONDITION_ATTRIBUTES` -- structural and
      exact, so a criterion whose bound survived in any readable form is never
      flagged. This is what keeps CAROLINA's rule 30 (``RangeHighRatio``, "3x ULN")
      silent while its rule 33 and rule 37 siblings fire, even though rule 30's name
      ("ALT above 3x ULN + ...") matches the vocabulary just as loudly.
    * its concept-set name OR its rule name matches :data:`_BOUND_ASSERTION_RE`.

    Reading the CONCEPT-SET name and not only the rule name is load-bearing, not
    thoroughness: CAROLINA's liver panel sits under the rule name "Acute Liver
    Disease + ... + Impaired Hepatic Function", while for the thyroid panel the
    assertion is only in the rule name ("Thyroxine (T4) level") and the concept-set
    names are bare analytes ("Thyroxine (T4)"). Either side alone misses part of the
    26.

    Silent, like the two checks beside it, on what the file cannot settle: a criteria
    type other than ``Measurement``, and a ``CodesetId`` with no matching
    ``ConceptSets`` entry (the rule name is still read in that case, since it is
    present in the file either way).

    :param expression: a CIRCE cohort expression.
    :returns: one locator per offending criterion, empty when none.
    """
    findings: list[str] = []
    for where, entry in _criterion_locations(expression):
        body = entry.get("Criteria")
        body = body if isinstance(body, dict) else entry
        for criteria_type, payload in body.items():
            if criteria_type != _BOUND_BEARING_CRITERIA_TYPE or not isinstance(payload, dict):
                continue
            if "CodesetId" not in payload:
                continue
            if any(key in VALUE_CONDITION_ATTRIBUTES for key in payload):
                continue
            codeset_id = payload["CodesetId"]
            concept_set = _find_concept_set(expression, codeset_id)
            concept_set_name = (concept_set or {}).get("name") or ""
            # The concept set first: it names the analyte the bound belongs to, so
            # when both sides assert, quoting that one puts the reader on the right
            # sub-criterion instead of on a six-way concatenated rule name.
            for source, text in (
                ("its concept-set name", concept_set_name),
                ("its rule name", where),
            ):
                match = _BOUND_ASSERTION_RE.search(str(text))
                if match is None:
                    continue
                findings.append(
                    f"{where}: {criteria_type} over codeset {codeset_id} "
                    f"{concept_set_name!r} carries no value condition while {source} "
                    f"asserts one ({match.group(0)!r})"
                )
                break
    return findings


def unfiltered_measurement_absence_criteria(expression: dict[str, Any]) -> list[str]:
    """Locators for absence criteria over a lab that carry no result filter at all.

    ``Occurrence {Type: 0, Count: 0}`` on a ``Measurement`` with no value condition
    selects on whether the TEST WAS PERFORMED, not on what it found. That is a property
    of the emitted SQL rather than of any dataset: with no ``value_as_number`` predicate
    the join matches every ``MEASUREMENT`` row carrying one of the concepts, so "zero
    occurrences" means "never tested". The protocol PLATO's rule 18 came from says
    "Known clinically important thrombocytopenia" -- a RESULT below a threshold.

    The magnitude, for scale only and NOT measured here: the site-gap fixture run that
    motivated this check reports rule 18 removing 63.1% / 56.3% / 38.7% of each site's
    population. This module neither reproduces nor relies on that number -- every CDM on
    this host is synthetic (``CLAUDE.md``), so a patient count from one is not evidence
    about a site, and the check rests on the SQL property above instead.

    In the same locator format :func:`asserted_bound_missing_criteria` uses::

        "<where>: Measurement over codeset <id> <name!r> is an ABSENCE with no value
         condition, so it excludes every patient who has ever had <analytes> measured
         rather than those whose result crossed a bound"

    Entirely structural -- three exact conditions, no vocabulary and no English:

    * the criteria type is :data:`_BOUND_BEARING_CRITERIA_TYPE`. Measurement is the one
      CDM table whose rows carry a ``value_as_number``, so it is the only type where an
      absent value condition is a LOSS rather than the shape of the data. On a
      ``ConditionOccurrence`` or an ``Observation`` there was never a result to filter,
      which is also what keeps this check silent on the corpus's three "not pregnant /
      not nursing" exclusions -- they are emitted as ``Observation``.
    * the occurrence is :data:`_ABSENT_OCCURRENCE`. A PRESENCE criterion over an
      unfiltered lab is over-broad in the other direction (it keeps everyone who was
      tested) and is real and uncaught -- PLATO's ``'Biomarker'``, codeset 14 -- but it
      is a different consequence with a different repair, so it is out of scope rather
      than folded in.
    * the criterion carries no key from :data:`VALUE_CONDITION_ATTRIBUTES` -- the same
      predicate :func:`asserted_bound_missing_criteria` applies, so the two checks
      cannot drift apart about what "filtered" means.

    Why it is a separate check from the three beside it, rather than a widening of one.
    :func:`unreadable_value_filter_criteria` needs a filter the table cannot read and
    :func:`domain_mismatched_criteria` needs a concept set the table cannot join: here
    the filter is absent and the join is perfect.
    :func:`asserted_bound_missing_criteria` needs a NAME that asserts a bound and reads
    a BROKEN PROMISE; ``'Thrombocytopenia'`` promises nothing, because a diagnosis needs
    no threshold. That is precisely why PLATO shipped this from 2026-09-10 to
    2026-09-14 with all seven lints green on it.

    The two checks overlap on purpose where a name does assert (LEADER's
    ``'Elevated HbA1c'`` fires in both). They say different things: that one says the
    name promised a bound, this one says what the rule selects without it, and a reader
    needs the second sentence to know the size of the loss.

    What this check CANNOT separate, stated rather than papered over: a criterion whose
    subject really is the testing event ("never had an HbA1c measured") has exactly this
    structure and is correct. No such criterion exists in either corpus as a
    ``Measurement`` -- swept across every produced corpus and the 18 TROY v1.1 files,
    the shape occurs on nine concept sets and all nine name a clinical state or an
    explicitly bounded lab, gold's own ``'[TROY lab] Systolic blood pressure (SBP)'``
    under "systolic BP > 180 mm Hg" among them. If one ever appears it will FAIL a
    delivery, and that is the intended cost: the finding names the rule, the codeset and
    the member concepts, so the reading takes one line. See the module docstring of
    ``tests/test_unfiltered_measurement_absence_lint.py`` for the two discriminators
    that were measured over all 83 Measurement rows, which one works, and why it is
    deliberately not wired in.

    Silent, like the checks beside it, on what the file cannot settle: a criteria type
    other than ``Measurement``. A ``CodesetId`` with no matching ``ConceptSets`` entry
    is still REPORTED -- the missing concept set is a different defect, and dropping the
    finding into it would hide this one.

    :param expression: a CIRCE cohort expression.
    :returns: one locator per offending criterion, empty when none.
    """
    findings: list[str] = []
    for where, entry in _criterion_locations(expression):
        occurrence = entry.get("Occurrence") or {}
        if (occurrence.get("Type"), occurrence.get("Count")) != _ABSENT_OCCURRENCE:
            continue
        body = entry.get("Criteria")
        body = body if isinstance(body, dict) else entry
        for criteria_type, payload in body.items():
            if criteria_type != _BOUND_BEARING_CRITERIA_TYPE or not isinstance(payload, dict):
                continue
            if "CodesetId" not in payload:
                continue
            if any(key in VALUE_CONDITION_ATTRIBUTES for key in payload):
                continue
            codeset_id = payload["CodesetId"]
            concept_set = _find_concept_set(expression, codeset_id) or {}
            findings.append(
                f"{where}: {criteria_type} over codeset {codeset_id} "
                f"{concept_set.get('name') or ''!r} is an ABSENCE with no value "
                f"condition, so it excludes every patient who has ever had "
                f"{_analyte_summary(concept_set)} measured rather than those whose "
                f"result crossed a bound"
            )
    return findings


#: How many member concept names a finding quotes. The reader's whole question is
#: whether the concept set's NAME describes what its CONCEPTS measure, so quoting none
#: sends them back to the file; quoting all of them buries the answer in a set that can
#: run to hundreds of descendants.
_ANALYTE_SUMMARY_LIMIT = 3


def _analyte_summary(concept_set: Mapping[str, Any]) -> str:
    """The first few member concept names, for a finding a reader can act on."""
    items = (concept_set.get("expression") or {}).get("items") or []
    names = [
        name
        for item in items
        if isinstance(item, dict)
        and (name := ((item.get("concept") or {}).get("CONCEPT_NAME") or "").strip())
    ]
    if not names:
        return "its concept set"
    shown = ", ".join(repr(name) for name in names[:_ANALYTE_SUMMARY_LIMIT])
    remainder = len(names) - _ANALYTE_SUMMARY_LIMIT
    return f"{shown} (+{remainder} more)" if remainder > 0 else shown


#: OMOP concept ids whose quantity is dimensionless BY NATURE -- a quotient of two
#: quantities of the same dimension, or an index computed from one -- so a bare number
#: means one thing at every site and a unit filter on it would be WRONG rather than
#: merely absent. In the same recorded shape :data:`~src.services.value_constraint.
#: _UNIT_CONCEPTS` uses: ``concept_id -> (concept_name, why it carries no unit)``.
#:
#: Keyed on concept id, not on concept-set name. A concept-set name here is free text
#: the model wrote, and this one corpus supplies three spellings of one analyte
#: (``'Glycated hemoglobin'``, ``'Hemoglobin A1c'``, ``'Glycosylated haemoglobin'``)
#: and three of another (``'eGFR'``, ``'Estimated glomerular filtration rate'``,
#: ``'Glomerular Filtration Rate'``). A name-keyed allowlist needs every spelling, and
#: a new one defeats it. Concept ids are vocabulary-stable and are what Circe joins on.
#:
#: What that choice costs, stated rather than discovered later: a genuinely
#: dimensionless analyte NOT listed here fails the gate until someone adds it with a
#: reason. That is the correct direction to fail -- loudly, with a one-line fix -- but
#: it is a real false-failure cost, and it is paid by whoever adds the next trial.
#:
#: Derived from the corpus, not from a list of what seemed complete. Every Measurement
#: concept set carrying a value filter across the 12 delivered files and the 18 TROY
#: v1.1 files under ``data/gold/`` was enumerated; five had members whose LOINC names
#: read as a ratio or an index with no dimensioned LOINC property. Three of those five
#: were then REJECTED, which is why the scan produced the candidates and not the table:
#:
#: * ``3038553`` BMI ``[Ratio]`` -- LOINC calls it a ratio, but BMI is kg/m2, and the
#:   same set holds ``40762636`` BMI ``[Percentile]``. A bare ``>= 45`` spans a body
#:   mass and a percentile. This delivery's own CAROLINA arm attaches ``kg/m2`` to it.
#: * ``3020682`` Albumin/Creatinine ``[Ratio]`` -- reported as mg/g or mg/mmol, about
#:   8.8x apart, and gold's set mixes ``[Ratio]`` with ``[Mass Ratio]``.
#: * ``3004410`` HbA1c/Hemoglobin.total -- reported as % (DCCT) or mmol/mol (IFCC).
#:   It reads as dimensionless only in gold's smaller set; the delivery's set holds
#:   ``3034639 ... [Mass/volume]`` beside it.
#:
#: Gold is NOT the source of this table, and disagrees with it. Across all 18 TROY
#: v1.1 files exactly ONE Measurement value filter carries a ``Unit`` (CAROLINA's LDL,
#: 8840 mg/dL); the other 37 carry none, LEADER's own ``'[TROY lab] Glycosylated
#: hemoglobin'`` ``< 7`` and ``'[TROY lab] calcitonin'`` ``>= 50`` among them. Reading
#: "gold omits a unit here" as "the quantity has none" would allowlist nearly every
#: analyte in the corpus and delete the check. Gold carries the same defect; per
#: ``docs/agent-briefing-facts.md`` it is a reference and not an oracle.
DIMENSIONLESS_MEASUREMENT_CONCEPTS: dict[int, tuple[str, str]] = {
    3016205: (
        "Systolic blood pressure Posterior tibial artery/Brachial artery",
        "LOINC states the ankle-brachial index as the quotient of its two measurands; "
        "both sides are a systolic pressure in mmHg, so the unit cancels",
    ),
    46237026: (
        "Ankle-brachial index",
        "ankle systolic pressure divided by brachial systolic pressure, both mmHg, so "
        "the quotient is a bare ratio and '< 0.9' means the same thing at every site",
    ),
    46237027: (
        "Cardio-ankle vascular index Calculated",
        "CAVI is a stiffness index computed from a pressure ratio and a logarithm, so "
        "it is dimensionless by construction and no UCUM unit applies to it",
    ),
}


def _concept_set_is_dimensionless(concept_set: Mapping[str, Any]) -> bool:
    """True when every concept the set SELECTS is in the dimensionless allowlist.

    ALL members, not any. A set mixing a bare ratio with a dimensioned analyte has no
    single scale, so its bound is ambiguous again -- and a mapper widening a ratio set
    with a lab test is exactly how that happens.

    An empty set is NOT dimensionless. ``all()`` over an empty sequence is True, which
    would silently exempt every criterion whose concept set lost its members; that is a
    different defect and exempting on it would hide this one.

    ``isExcluded`` items are skipped: an exclusion removes concepts rather than adding
    them, so it cannot make the remainder dimensioned. No value-bearing Measurement set
    in either corpus uses one -- 0 of 99 -- so this branch is untested by the corpus and
    is the conservative reading rather than a measured one.

    The known limit, stated rather than papered over: every member here carries
    ``includeDescendants``, and this reads the SEED concepts written into the file, not
    the resolved descendant closure. A dimensioned descendant of a dimensionless seed
    would be exempted. Resolving the closure needs the vocabulary database, and this
    module's contract is pure functions over a CIRCE expression dict.
    """
    items = (concept_set.get("expression") or {}).get("items") or []
    included = [
        item
        for item in items
        if isinstance(item, dict) and not item.get("isExcluded")
    ]
    if not included:
        return False
    return all(
        (item.get("concept") or {}).get("CONCEPT_ID") in DIMENSIONLESS_MEASUREMENT_CONCEPTS
        for item in included
    )


def _render_numeric_bound(value: Mapping[str, Any]) -> str:
    """``"gte 7.0"`` / ``"bt 6.5..10.0"`` -- the bound as a reader would say it."""
    operator = value.get("Op")
    low = value.get("Value")
    extent = value.get("Extent")
    if extent is not None and operator in {"bt", "!bt"}:
        return f"{operator} {low}..{extent}"
    return f"{operator} {low}"


def unitless_measurement_bound_criteria(expression: dict[str, Any]) -> list[str]:
    """Locators for criteria bounding a lab numerically while naming no unit.

    The asymmetry this closes. ``src.services.value_constraint`` REFUSES a criterion
    whose unit string resolves to no UCUM concept
    (:data:`~src.utils.criterion_refusal.REFUSAL_UNSTATED_UNIT_BOUND`), and its own
    recorded reason says why: the bound "would be emitted as a bare number and compared
    against whatever scale the CDM stores". A criterion that stated no unit AT ALL
    produces that identical bare number and was not refused, so the safe case -- a unit
    was written, could not be read, and the criterion was dropped rather than shipped
    wrong -- was punished while the dangerous case shipped.

    In the same locator format :func:`unfiltered_measurement_absence_criteria` uses::

        "<where>: Measurement over codeset <id> <name!r> bounds ValueAsNumber <op>
         <value> with no Unit, so Circe compares the bare number against whatever
         scale the CDM stores for <analytes>"

    Measured on ``output/site_gap/2026-09-14/DELIVERY``: of 92 ``Measurement`` leaves,
    40 carry both ``ValueAsNumber`` and ``Unit``, 32 carry ``RangeHighRatio``, 10 carry
    no value condition, and 10 carry ``ValueAsNumber`` with no ``Unit``. Those 10 are
    five concept sets on both LEADER arms: ``'Ankle-brachial index'`` (allowlisted,
    below), ``'eGFR'``, ``'Glycated hemoglobin'``, ``'Hemoglobin A1c'`` and
    ``'Calcitonin'``.

    HbA1c is the concrete harm and shows the failure is INVERTED rather than empty:
    7.0% is 53 mmol/mol, so ``>= 7.0`` against a site storing IFCC units passes
    essentially every patient. The ambiguity is internal to the delivered file --
    codesets 17 and 18 each hold ``4197971 HbA1c measurement (DCCT aligned)`` (%) and
    ``44793001 Hb A1c ... IFCC`` (mmol/mol), so the set names both unit systems and the
    criterion picks neither. ``'Calcitonin'`` holds both ``[Mass/volume]`` and
    ``[Moles/volume]`` LOINC concepts for the same reason. The strongest corroboration
    is the batch's own consistency: the SAME pipeline attaches ``%`` to HbA1c on
    CARMELINA, CAROLINA and EMPA-REG, and ``mL/min/1.73m2`` to eGFR on CAROLINA and
    EMPA-REG. LEADER's are missing, not dimensionless.

    Three exact conditions, all structural -- no vocabulary, no database, no English:

    * the criteria type is :data:`_BOUND_BEARING_CRITERIA_TYPE`. ``Observation`` also
      reads ``ValueAsNumber`` and ``Unit`` per :data:`CRITERIA_TYPE_VALUE_ATTRIBUTES`,
      and the SAME defect exists there -- this check does not cover it, which is a
      scope boundary and not a measurement. Counted over the batch: 6 ``Observation``
      criteria carry ``ValueAsNumber`` and 4 of them carry no ``Unit`` -- CARMELINA
      codeset 32 ``'Life expectancy'`` ``lt 5.0`` and CAROLINA codeset 22
      ``'Systolic blood pressure'`` ``gt 140.0``, both arms each. The same asymmetry
      shows there too: CAROLINA's own codeset 44 ``'life expectancy less than 5
      years'`` carries ``Unit`` year, and ARISTOTLE's SBP carries ``mm[Hg]``. Widening
      this check to ``Observation`` would add a failure reason to four more files and
      is deliberately left as a separate decision rather than taken here.
      ``tests/test_unitless_measurement_bound_lint.py`` asserts that count on the real
      batch, so the boundary is recorded mechanically and a later widening starts from
      a measured number rather than a re-survey.
    * ``ValueAsNumber`` is present. A criterion with no value condition at all is
      :func:`unfiltered_measurement_absence_criteria`'s, with a different repair.
    * ``Unit`` is absent OR EMPTY. Truthiness rather than key presence, because
      ``Unit: []`` renders no unit predicate and ships the same bare number; keying on
      presence would make an empty list a silent exemption.

    ``RangeHighRatio`` leaves are never flagged, and structurally rather than by an
    exemption: a ratio bound is a multiple of the lab's own ``range_high`` so the units
    cancel, and all 32 such leaves in the batch carry no ``ValueAsNumber``, so the
    second condition already excludes them. No explicit skip is added, because a leaf
    carrying BOTH would still need a unit for its absolute half, and an exemption keyed
    on ``RangeHighRatio`` would wrongly pass it. ``tests/test_unitless_measurement_
    bound_lint.py`` asserts the disjointness on the real batch rather than assuming it.

    Ankle-brachial index is exempted by concept id via
    :data:`DIMENSIONLESS_MEASUREMENT_CONCEPTS` -- it is a quotient of two mmHg
    pressures, so a unit filter on it would be wrong rather than missing. See that
    table for how the allowlist was derived from the corpus, the three ratio-looking
    candidates that were rejected, and why gold is not its source.

    Silent, like the checks beside it, on what the file cannot settle: a criteria type
    other than ``Measurement``. A ``CodesetId`` with no matching ``ConceptSets`` entry
    is still REPORTED -- an unknown set cannot be shown to be dimensionless, and the
    missing concept set is a different defect that would hide this one.

    :param expression: a CIRCE cohort expression.
    :returns: one locator per offending criterion, empty when none.
    """
    findings: list[str] = []
    for where, entry in _criterion_locations(expression):
        body = entry.get("Criteria")
        body = body if isinstance(body, dict) else entry
        for criteria_type, payload in body.items():
            if criteria_type != _BOUND_BEARING_CRITERIA_TYPE or not isinstance(payload, dict):
                continue
            if "CodesetId" not in payload:
                continue
            value = payload.get("ValueAsNumber")
            if not isinstance(value, Mapping):
                continue
            if payload.get("Unit"):
                continue
            codeset_id = payload["CodesetId"]
            concept_set = _find_concept_set(expression, codeset_id)
            if concept_set is not None and _concept_set_is_dimensionless(concept_set):
                continue
            concept_set = concept_set or {}
            findings.append(
                f"{where}: {criteria_type} over codeset {codeset_id} "
                f"{concept_set.get('name') or ''!r} bounds ValueAsNumber "
                f"{_render_numeric_bound(value)} with no Unit, so Circe compares the "
                f"bare number against whatever scale the CDM stores for "
                f"{_analyte_summary(concept_set)} -- a site recording another unit for "
                f"the same analyte matches the wrong patients rather than none"
            )
    return findings


def _entry_is_unreadable(entry: dict[str, Any]) -> bool:
    body = entry.get("Criteria")
    body = body if isinstance(body, dict) else entry
    return any(
        isinstance(payload, dict) and unreadable_value_attributes(criteria_type, payload)
        for criteria_type, payload in body.items()
    )


def _entry_unreadable_details(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """``[{criteriaType, attributes, codesetId}]`` for one criterion entry.

    One element per criteria type in the entry that carries an attribute its own CDM
    table ignores. A list rather than a single dict because a CIRCE criterion entry is
    keyed by criteria type and nothing forbids two of them; none of the six delivered
    studies carries such an entry, and recording only the first would silently lose the
    rest if one ever appeared.
    """
    body = entry.get("Criteria")
    body = body if isinstance(body, dict) else entry
    return [
        {
            "criteriaType": criteria_type,
            "attributes": unreadable,
            # Lower-cased deliberately. `prune_unused_concept_sets` walks the whole
            # payload for the literal key `CodesetId` to decide which concept sets are
            # still referenced, so spelling it that way here would keep the dropped
            # criterion's concept set alive in the delivered file -- a record of a
            # removal that partly un-does the removal.
            "codesetId": payload.get("CodesetId"),
        }
        for criteria_type, payload in body.items()
        if isinstance(payload, dict)
        and (unreadable := unreadable_value_attributes(criteria_type, payload))
    ]


def _entry_unreadable_summary(entry: dict[str, Any]) -> str:
    return " / ".join(
        f"{detail['criteriaType']} carrying {', '.join(detail['attributes'])}"
        for detail in _entry_unreadable_details(entry)
    )


def _concept_set_members(concept_set: Mapping[str, Any]) -> frozenset[tuple[int, bool]]:
    """The ``(concept id, isExcluded)`` pairs a concept set carries -- its identity here.

    ``isExcluded`` is part of that identity because it is the axis a missing negation
    should have used: two sets over the same ids that disagree about it are genuinely
    different sets, and collapsing them would hide the one repair this defect has.
    ``includeDescendants`` is deliberately NOT part of it -- resolving what it expands to
    needs ``concept_ancestor``, and this module is I/O-free, so two sets differing only
    by it are compared on what the file can prove.

    An item with no integer ``CONCEPT_ID`` is skipped rather than reported: a malformed
    item is its own defect and ``verify_circe_delivery`` reads the set separately.
    """
    items = (concept_set.get("expression") or {}).get("items") or []
    return frozenset(
        (item["concept"]["CONCEPT_ID"], bool(item.get("isExcluded")))
        for item in items
        if isinstance(item, Mapping)
        and isinstance(item.get("concept"), Mapping)
        and isinstance(item["concept"].get("CONCEPT_ID"), int)
        and not isinstance(item["concept"]["CONCEPT_ID"], bool)
    )


def aliased_concept_sets(expression: dict[str, Any]) -> list[str]:
    """Locators for concept sets holding identical members under different names.

    Pure set comparison on the emitted JSON -- no vocabulary, no database, no English.
    Two names over one member set can only mean one of two things, and both are defects:
    a name says more than its members do, or one criterion was mapped twice.

    The motivating case, LEADER 2026-09-14, both arms::

        ConceptSet 12  'human NPH insulin'                     26 ids
        ConceptSet 54  'insulin other than human NPH insulin'  the SAME 26 ids
        ConceptSet 56  'insulin other than premixed insulin'   the SAME 26 ids

    The ``other than`` negation was never applied: the exclusion set IS the inclusion
    set, and ``InclusionRules[2]`` requires the patient to have codeset 12 while
    ``InclusionRules[24]`` requires zero exposures to codeset 54. Nothing in the file
    can make those two demands compatible, which is what makes this readable without a
    vocabulary. The qualifier is not lost on the way in -- the store's
    ``_criterionMappingMetadata`` records ``queryUsed`` verbatim as
    ``'insulin other than human NPH insulin'`` and the emitted NAME still carries it.
    Only its effect is absent.

    Three deliberate silences, each a shape the file settles on its own:

    * **identical names.** LEADER's codesets 10, 11 and 13 are the same 71 ids under the
      same name ``'oral anti-diabetic drugs'`` -- one seed mapped three times. Redundant,
      but no name contradicts its members, and the consequence is what
      :func:`contradictory_presence_absence_criteria` reads.
    * **a genuine subset.** A narrowing name that really did narrow ('long-acting insulin
      analogue' under 'insulin') produces FEWER members, so an equality test never sees
      it. That is the whole reason the comparison is equality rather than overlap.
    * **empty sets.** Two empty sets are equal on members and say nothing. An empty
      concept set is its own defect and the delivery gate already fails on one; reporting
      it here would bury that finding under a wrong headline.

    What it CANNOT separate, measured rather than assumed. A synonym pair mapped twice
    is structurally identical to a dropped negation, and no name test separates the two:
    substring containment was tried across every firing in both corpora and holds for
    the real defects AND for gold's ``'[TROY intervention] Warfarin'`` /
    ``'... Warfarin (ATC)'``, so it buys nothing. The measured cost, at ``953d6b2``:
    three groups across the twelve delivered files (LEADER's insulins, ARISTOTLE's
    ``'Aspirin and thienopyridine use'`` holding aspirin alone, EMPA-REG's two 'eGFR
    < 30' rules emitted under two names with different unit lists) -- all three point at
    something real -- and three more across the 18 hand-built TROY v1.1 files under
    ``data/gold/``, where they are authoring conventions. The gate never reads
    ``data/gold/``, so those cost no delivery.

    :param expression: a CIRCE cohort expression.
    :returns: one locator per group of aliased sets, empty when none.
    """
    by_members: dict[frozenset[tuple[int, bool]], list[dict[str, Any]]] = {}
    for concept_set in expression.get("ConceptSets") or []:
        if not isinstance(concept_set, Mapping):
            continue
        members = _concept_set_members(concept_set)
        if not members:
            continue
        by_members.setdefault(members, []).append(concept_set)

    findings: list[str] = []
    for members, group in by_members.items():
        names = {(concept_set.get("name") or "") for concept_set in group}
        if len(group) < 2 or len(names) < 2:
            continue
        quoted = ", ".join(
            f"{concept_set.get('id')} {(concept_set.get('name') or '')!r}"
            for concept_set in sorted(group, key=lambda c: str(c.get("id")))
        )
        findings.append(
            f"codesets {quoted} hold the IDENTICAL {len(members)} concept ids under "
            f"{len(names)} different names, so at least one name describes something "
            f"its members do not"
        )
    return findings


def _entry_interval(entry: dict[str, Any]) -> tuple[float, float] | None:
    """The entry's ``StartWindow`` as ``(start days, end days)`` relative to index.

    ``None`` when the offsets are not provable from the file -- no window, a missing or
    non-numeric ``Days``/``Coeff``, or a window rebased by ``UseIndexEnd`` /
    ``UseEventEnd`` onto an era end whose distance from index the file does not record.
    Callers treat every unprovable case as overlapping, so uncertainty never silences a
    check. Kept separate from :func:`_effective_end_days`, which reads only the END and
    whose exemption ``contradictory_absence_rules`` depends on being measured against a
    WebAPI experiment; widening that one to need both ends would change its verdicts.
    """
    window = entry.get("StartWindow")
    if not isinstance(window, Mapping):
        return None
    if window.get("UseIndexEnd") or window.get("UseEventEnd"):
        return None
    offsets: list[float] = []
    for boundary in ("Start", "End"):
        edge = window.get(boundary)
        if not isinstance(edge, Mapping):
            return None
        days, coeff = edge.get("Days"), edge.get("Coeff")
        if isinstance(days, bool) or isinstance(coeff, bool):
            return None
        if not isinstance(days, (int, float)) or not isinstance(coeff, (int, float)):
            return None
        offsets.append(days * coeff)
    return offsets[0], offsets[1]


def _intervals_overlap(
    left: tuple[float, float] | None, right: tuple[float, float] | None
) -> bool:
    """Whether two day-offset intervals share a day. Unprovable counts as overlapping."""
    if left is None or right is None:
        return True
    return max(left[0], right[0]) <= min(left[1], right[1])


def _unnarrowed_codeset(entry: dict[str, Any]) -> tuple[str, Any] | None:
    """``(criteria type, CodesetId)`` when the entry selects its WHOLE concept set.

    An entry carrying any attribute besides ``CodesetId`` -- a value bound, a unit, an
    era length, a correlated criterion -- selects a subset of its concept set. Applied to
    an ABSENCE that matters: "no HbA1c below 6" forbids only part of the set, so "an
    HbA1c of at least 7" can still hold and there is no contradiction to report.

    Deliberately asymmetric, and the asymmetry is the point. A narrowed PRESENCE is still
    contradicted by an unnarrowed absence -- "no HbA1c on record at all" kills "an HbA1c
    of at least 7" however the presence is qualified -- so
    :func:`contradictory_presence_absence_criteria` applies this guard to the absence side
    only and reads the presence with :func:`_leaf_codeset_id`. Measured on the twelve
    delivered files and the 18 gold files, the symmetric and asymmetric readings return
    the same four findings; the asymmetric one is used because it is the one that is
    right when they differ.

    Measured across the same 30 files: 377 of 555 absence criteria carry ``CodesetId``
    alone, so the guard costs about a third of the reachable absences and buys a shape
    that needs no judgement.
    """
    body = entry.get("Criteria")
    body = body if isinstance(body, Mapping) else entry
    for criteria_type, payload in body.items():
        if not isinstance(payload, Mapping) or "CodesetId" not in payload:
            continue
        if set(payload) != {"CodesetId"}:
            return None
        return criteria_type, payload["CodesetId"]
    return None


def contradictory_presence_absence_criteria(expression: dict[str, Any]) -> list[str]:
    """Locators for a mandatory presence and a mandatory absence over one concept set.

    CIRCE conjoins every ``InclusionRules`` entry, so the whole list is one implicit
    ``ALL``: a presence in rule 2 and an absence in rule 3 are as conjoined as two
    criteria inside a single rule, and the check reads both the same way. When the two
    reference the same ``CodesetId`` -- or two codesets whose members are byte-identical
    -- and their windows share a day, the conjunction is empty and the cohort is blocked.

    The motivating case, LEADER 2026-09-14, four findings per arm::

        InclusionRules[2]  G0 zero exposures to codeset 10  [-365,-1]  identical
        InclusionRules[2]  G1 >=1  exposure  to codeset 11  [-365, 0]  71 ids
        InclusionRules[3]     zero exposures to codeset 13  [-365,-1]  the same 71
        InclusionRules[24] G0 zero exposures to codeset 54  [ -90,-1]  identical
        InclusionRules[2]  G2 >=1  exposure  to codeset 12  [-365, 0]  26 ids

    The first pair is an OR emitted as ``Type: ALL`` -- three mutually exclusive
    enrolment alternatives conjoined -- and carries no exclusion-qualified name at all.
    The last pair is the dropped ``other than`` negation. Two defects, one signature,
    which is why this reads structure rather than names.

    Four deliberate silences, each of them a satisfiable shape:

    * **non-overlapping windows.** "No exposure in [-365,-91] and at least one in
      [-30,0]" is an ordinary washout-then-treatment pattern and is common.
    * **a presence under ``ANY``.** Alternatives survive a contradicted branch.
    * **a narrowed absence.** See :func:`_unnarrowed_codeset` -- an absence carrying a
      bound selects a subset, and the presence may live outside it.
    * **different concept sets.** Overlap short of equality is not provable here without
      resolving descendants, which needs the vocabulary this module does not touch.
      LEADER's codeset 29 ('Elevated HbA1c', 5 of 6 ids shared with codeset 17) is a
      real contradiction this check does NOT report; it is already reported by
      :func:`unfiltered_measurement_absence_criteria` and
      :func:`asserted_bound_missing_criteria`, and widening this one to overlap would
      double-report it while inviting false positives everywhere else.

    Measured at ``953d6b2``: four findings on each delivered LEADER arm, zero on the
    other ten delivered files, and zero on all 18 hand-built TROY v1.1 files under
    ``data/gold/``.

    :param expression: a CIRCE cohort expression.
    :returns: one locator per contradicting pair, empty when none.
    """
    presences: list[tuple[str, Any, dict[str, Any]]] = []
    absences: list[tuple[str, str, Any, dict[str, Any]]] = []
    for index, rule in enumerate(expression.get("InclusionRules") or []):
        where = f"InclusionRules[{index}] {(rule.get('name') or '')!r}"
        for entry in _conjoined_entries(rule.get("expression") or {}):
            occurrence = entry.get("Occurrence") or {}
            if (occurrence.get("Type"), occurrence.get("Count")) == _ABSENT_OCCURRENCE:
                leaf = _unnarrowed_codeset(entry)
                if leaf is not None:
                    absences.append((where, leaf[0], leaf[1], entry))
            elif (
                occurrence.get("Type") == 2
                and isinstance(occurrence.get("Count"), int)
                and not isinstance(occurrence.get("Count"), bool)
                and occurrence["Count"] >= 1
            ):
                codeset_id = _leaf_codeset_id(entry)
                if codeset_id is not None:
                    presences.append((where, codeset_id, entry))

    if not presences or not absences:
        return []

    members_by_codeset = {
        concept_set.get("id"): _concept_set_members(concept_set)
        for concept_set in expression.get("ConceptSets") or []
        if isinstance(concept_set, Mapping)
    }
    names_by_codeset = {
        concept_set.get("id"): concept_set.get("name") or ""
        for concept_set in expression.get("ConceptSets") or []
        if isinstance(concept_set, Mapping)
    }

    findings: list[str] = []
    for absent_where, absent_type, absent_id, absent_entry in absences:
        absent_members = members_by_codeset.get(absent_id)
        for present_where, present_id, present_entry in presences:
            if present_id != absent_id:
                present_members = members_by_codeset.get(present_id)
                if not absent_members or absent_members != present_members:
                    continue
            if not _intervals_overlap(
                _entry_interval(absent_entry), _entry_interval(present_entry)
            ):
                continue
            same = "the same" if present_id == absent_id else "an IDENTICAL"
            findings.append(
                f"{absent_where}: {absent_type} over codeset {absent_id} "
                f"{names_by_codeset.get(absent_id, '')!r} requires ZERO occurrences "
                f"while {present_where} requires at least one over {same} concept set, "
                f"codeset {present_id} {names_by_codeset.get(present_id, '')!r}, in an "
                f"overlapping window -- CIRCE conjoins every InclusionRules entry, so "
                f"no patient can satisfy both"
            )
    return findings


#: A connective that joins alternatives. ``and/or`` is matched by ``\bor\b`` -- the
#: slash is a non-word character, so the word boundary holds.
_DISJUNCTIVE_CONNECTIVE = re.compile(r"\bor\b|\beither\b", re.IGNORECASE)

#: "N of the following" -- a cardinality over a LIST, which is a different shape from a
#: flat disjunction and needs a nested Group with a Count rather than a type flip.
#:
#: The ``of`` is load-bearing and is required in every branch. Without it the pattern
#: matches "treated with one or more oral anti-diabetic drugs", where "one or more"
#: counts DRUGS rather than group members -- and that phrase sits in the middle of
#: LEADER's own line, so a looser guard silences the exact defect this reads for. That
#: is not hypothetical: the first draft of this pattern did exactly that and the check
#: reported nothing on the whole corpus.
_LIST_CARDINALITY = re.compile(
    r"at\s+least\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+of\b"
    r"|[\u2265>]=?\s*\d+\s+of\b"
    r"|\b(any\s+)?one\s+(\(or\s+more\)\s+)?of\s+the\s+following\b"
    r"|\bone\s+or\s+more\s+of\b"
    r"|\bany\s+one\s+of\b",
    re.IGNORECASE,
)


def states_flat_disjunction(protocol_line: str | None) -> bool:
    """Whether a protocol line joins its alternatives with a bare disjunction.

    "Flat" excludes the cardinality shape -- "Age >=60 y and >=1 of the following
    criteria" -- on purpose. There the conjunction is half right: the age bound IS
    conjoined with the list, and flipping the whole group to ``ANY`` would admit a
    patient on age alone. CIRCE can express it, as a nested Group carrying a Count, and
    until something builds that nesting the honest answer is to decline the line rather
    than half-fix it. Two such groups exist in the delivered corpus (LEADER ``38a60fc2``
    and ``1157e3c3``) and both are excluded by this branch rather than by luck.

    The line, not the label. The store writes a group's ``description`` from the IR
    ``name``, which a prior measurement found flips between runs on the same input, and
    its protocol line from the IR ``source_text``, copied verbatim from the document.
    The difference is measurable on this corpus rather than assumed: LEADER
    ``38a60fc2``'s description reads "Age >= 60 years AND at least one of: Prior MI,
    Prior stroke or TIA, Prior coronary, carotid or peripheral arterial
    revascularization", whose two "or"s sit INSIDE member names and read as a
    group-level disjunction to any text test, while its protocol line carries no bare
    disjunction at all.

    :param protocol_line: the protocol's own line, or None.
    :returns: True when the line states a disjunction between alternatives.
    """
    text = (protocol_line or "").strip()
    if not text:
        return False
    if _LIST_CARDINALITY.search(text):
        return False
    return bool(_DISJUNCTIVE_CONNECTIVE.search(text))


def _store_groups_by_id(study: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    """Store criteria bucketed by ``groupId``, both roles together."""
    eligibility = study.get("eligibility") or {}
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for role in ("inclusionCriteria", "exclusionCriteria"):
        for criterion in eligibility.get(role) or []:
            if not isinstance(criterion, Mapping):
                continue
            group_id = criterion.get("groupId")
            if group_id:
                groups.setdefault(group_id, []).append(criterion)
    return groups


def group_protocol_line(members: Sequence[Mapping[str, Any]], key: str) -> str:
    """The one protocol line that covers a store group, or ``""``.

    The group-label row first -- it is the row the extractor wrote the whole clause on.
    Failing that, a line shared by every member: where the members carry DIFFERENT
    lines there is no single sentence between them, so no disjunction between the
    members was stated anywhere and the group is left alone.
    """
    for member in members:
        if member.get("isGroupLabel") and (member.get(key) or "").strip():
            return str(member[key]).strip()
    lines = {
        str(member.get(key) or "").strip()
        for member in members
        if not member.get("isGroupLabel")
    }
    lines.discard("")
    return lines.pop() if len(lines) == 1 else ""


def conjoined_disjunction_rules(
    expression: dict[str, Any], study: Mapping[str, Any]
) -> list[str]:
    """Locators for a rule emitted as a conjunction over a stated disjunction.

    The 2026-09-11 conversion audit counts AND/OR inversion at 7 instances across 4
    trials, its largest logical-defect class. The clearest is LEADER store group
    ``4a712697``: ``groupType: "ALL"`` under a line reading "Anti-diabetic drug naive
    **or** treated with one or more oral anti-diabetic drugs **or** treated with human
    NPH insulin ...". It reaches the delivery as ``InclusionRules[2]``, which demands
    zero exposures to codeset 10 AND at least one to codeset 11 -- byte-identical sets
    -- so only a patient whose sole exposure falls on the index day can satisfy it.

    Three conditions, and all three are needed:

    * the emitted ``Type`` is ``ALL`` over two or more groups. One group is not a
      combination; there is no connective to get wrong.
    * the rule's criteria are not ALL absences. An ``ALL`` over ``ABSENCE`` is the De
      Morgan encoding of "exclude if ANY of these" -- the same reading
      :func:`~src.services.tte_service._effective_group_type` produces on the ``ANY``
      side -- so an exclusion group reading "Stroke or TIA" belongs as ``ALL``.
      Measured on the twelve delivered files: 181 emitted ``ALL`` rules are
      all-absence, and flagging them would invert 181 working exclusions.
    * the store group's protocol line states a flat disjunction
      (:func:`states_flat_disjunction`).

    The connective on its own is NOT the signal, which is why the polarity condition is
    not decoration. Swept across all six trials (82 groups): 17 declare ``ALL`` under a
    label stating "or", and only 2 of those 17 are defects; 31 of the 47 all-ABSENCE
    ``ALL`` groups sit under a line that states a flat disjunction, and every one of
    them is correct. A connective-only rule scores 2/33.

    The store is joined to the file through ``conceptSetId``: each store criterion
    records the codeset its mapping produced, and the audit established that mapping is
    1:1 in all six trials. A rule whose codesets reach two store groups, or none, is
    left alone -- nothing about its line has been established.

    No database, no vocabulary, no concept-set resolution.

    Measured at ``da1c10a`` on the twelve delivered files: one finding on each LEADER
    arm (``InclusionRules[2]``), zero on the other ten.

    :param expression: a CIRCE cohort expression.
    :param study: the store study the expression was built from.
    :returns: one locator per rule, empty when none.
    """
    # Imported here rather than at module scope on purpose: the key's home is
    # `src.api.models.tte`, which pulls pydantic and `src.utils.llm` and costs ~370ms
    # to import -- roughly ninety times this module's own import. Paying that on every
    # consumer of a pure lint module, to read one string, is the wrong trade; retyping
    # the literal instead would give the key a second home, which is the failure
    # `CRITERION_CONCEPT_SET_REFS_KEY` documents at length above.
    from src.api.models.tte import CRITERION_PROTOCOL_LINE_KEY

    groups_by_id = _store_groups_by_id(study)
    group_id_by_codeset: dict[Any, str] = {}
    for group_id, members in groups_by_id.items():
        for member in members:
            codeset_id = member.get("conceptSetId")
            if codeset_id is not None:
                group_id_by_codeset[codeset_id] = group_id

    findings: list[str] = []
    for index, rule in enumerate(expression.get("InclusionRules") or []):
        body = rule.get("expression") or {}
        if (body.get("Type") or "ALL").strip().upper() != "ALL":
            continue
        if len(body.get("Groups") or []) < 2:
            continue

        entries = _walk_criteria_entries(body)
        if not entries:
            continue
        occurrences = [
            (
                (entry.get("Occurrence") or {}).get("Type"),
                (entry.get("Occurrence") or {}).get("Count"),
            )
            for entry in entries
        ]
        if all(occurrence == _ABSENT_OCCURRENCE for occurrence in occurrences):
            continue

        group_ids = {
            group_id_by_codeset.get(_leaf_codeset_id(entry)) for entry in entries
        }
        group_ids.discard(None)
        if len(group_ids) != 1:
            continue
        group_id = group_ids.pop()

        line = group_protocol_line(
            groups_by_id[group_id], CRITERION_PROTOCOL_LINE_KEY
        )
        if not states_flat_disjunction(line):
            continue

        findings.append(
            f"InclusionRules[{index}] {(rule.get('name') or '')!r}: emitted "
            f"Type ALL over {len(body['Groups'])} groups while store group "
            f"{group_id} states a disjunction -- {line!r}. The members are not all "
            f"absences, so De Morgan does not make the conjunction correct; the "
            f"alternatives were conjoined and every one of them is now mandatory"
        )
    return findings


#: The key ``TTEService._build_emittable_expression`` writes the drop records under.
#: Spelled once and imported by every reader -- the delivery gate keys its rule-set
#: reconciliation on it, and a second copy of the string would make that reconciliation
#: silently find nothing (AGENTS.md, wire-format constants).
DROPPED_CRITERIA_KEY = "_droppedCriteria"

#: What became of the rule the dropped criterion sat in. The delivery gate replays
#: these against the store's rule multiset, so each value is a wire-format constant.
#: The rule left the file: its every criterion was unreadable, or the group it was in
#: emptied.
DROP_OUTCOME_RULE_REMOVED = "rule-removed"
#: The rule survived and its name was rewritten from the members that remain.
DROP_OUTCOME_RULE_RENAMED = "rule-renamed"
#: The rule survived under the name it already had -- the correspondence between name
#: segments and members was not provable, so :func:`_rename_after_drop` left it alone.
DROP_OUTCOME_RULE_KEPT = "rule-kept"

#: The key ``TTEService._build_seeded_target_circe`` writes the per-criterion
#: concept-set links under: ``{"inclusion:5": 2, "5": 2, ...}``, one role-keyed entry
#: per criterion whose mapping returned a result, written in the same loop that appends
#: the concept set and increments the codeset id.
#:
#: Spelled once here for the same reason :data:`DROPPED_CRITERIA_KEY` is, but the
#: consequence of a second copy is worse. This is the ONLY record in an emitted file
#: that says a PARTICULAR criterion produced something, so the delivery gate anchors
#: ``census.mapped`` to it: retype the string at either producer site and the gate finds
#: no map, takes its fail-open branch, and reports "no concept-set links recorded" --
#: the mapped check has silently stopped running while the delivery still ships. A
#: producer that then books a lost criterion as ``mapped`` meets no check at all.
#:
#: With the spelling owned here that shape is closed at the source: the producer writes
#: this name and the gate reads this name, and there is no literal left to mistype.
#: Renaming the CONSTANT breaks both importers loudly at import; changing its VALUE is
#: a wire-format change against every artifact already on disk, which no importer or
#: type checker can see. Both are covered by ``TestTheKeyTheLinkIsReadByHasOneHome`` in
#: ``tests/test_delivery_gate_anchors_the_census_to_the_store.py``.
CRITERION_CONCEPT_SET_REFS_KEY = "_criterionConceptSetRefs"


def _prune_group_expression(
    node: dict[str, Any], where: str, dropped: list[dict[str, Any]]
) -> None:
    """Drop unreadable criteria from one group expression, depth first.

    A nested group emptied by the pruning is removed with it: an ``ALL`` group with
    no criteria matches everybody, so leaving the husk behind would turn a dropped
    exclusion into an admitted-everyone rule.

    Does NOT descend into ``CorrelatedCriteria``. Emptying one would leave a nested
    correlation that constrains nothing, which is a different repair than dropping a
    sibling criterion, and no such node appears in any file delivered so far. It is a
    hole only in the repair -- :func:`unreadable_value_filter_criteria` still walks
    them, so such a criterion is reported rather than silently kept.

    :param node: a CIRCE group expression, modified in place.
    :param where: the enclosing rule name, for the recorded reason.
    :param dropped: appended to, one partial record per criterion actually removed.
        The caller fills in ``ruleIndex``/``ruleAfter``/``outcome``, which are not
        known until the whole rule has been walked.
    """
    kept_entries = []
    for entry in node.get("CriteriaList") or []:
        if isinstance(entry, dict) and _entry_is_unreadable(entry):
            dropped.append(
                {
                    # Seeded in the order a reader wants them, then completed by
                    # `drop_unreadable_value_criteria`; a record that reached a file
                    # still carrying `outcome: ""` would mean that pass never ran.
                    "ruleIndex": None,
                    "rule": where,
                    "ruleAfter": None,
                    "outcome": "",
                    "unreadable": _entry_unreadable_details(entry),
                    "summary": f"{where}: {_entry_unreadable_summary(entry)}",
                }
            )
            continue
        kept_entries.append(entry)
    if "CriteriaList" in node:
        node["CriteriaList"] = kept_entries

    kept_groups = []
    for group in node.get("Groups") or []:
        if not isinstance(group, dict):
            kept_groups.append(group)
            continue
        _prune_group_expression(group, where, dropped)
        if _group_is_empty(group):
            continue
        kept_groups.append(group)
    if "Groups" in node:
        node["Groups"] = kept_groups


def _group_is_empty(node: dict[str, Any]) -> bool:
    return not (
        node.get("CriteriaList")
        or node.get("DemographicCriteriaList")
        or node.get("Groups")
    )


def _rename_after_drop(name: str, kept: list[int], original_count: int) -> str:
    """Rebuild a group rule's name from the members that survived, when provable.

    A grouped rule's name is ``" + ".join(member descriptions)``, so a rule that
    loses a member keeps advertising it. Rewriting is only safe when the file itself
    proves the correspondence: the name must split into exactly one segment per
    original member, and must not be one of the names truncated to
    ``_MAX_RULE_NAME_LENGTH``. Anything else is left alone -- an over-broad name is a
    smaller error than a mangled one.
    """
    if not name or name.endswith("..."):
        return name
    segments = name.split(" + ")
    if len(segments) != original_count:
        return name
    return " + ".join(segments[index] for index in kept)


def drop_unreadable_value_criteria(expression: dict[str, Any]) -> list[dict[str, Any]]:
    """Remove criteria whose value filter their CDM table cannot read. Mutates.

    The emission-time half of the gate. Studies 1/8/9/10 carry a prebuilt
    ``structuredExpression`` that the arm builders deepcopy verbatim, so the
    generation-time refusal never runs on the delivery path and a fix there alone
    would need an LLM re-extraction to reach a delivered file. Applied where the
    expression is first assembled, a plain re-export is enough -- the same reasoning,
    and the same placement, as :func:`end_entry_colliding_washouts_before_index`.

    ``PrimaryCriteria`` is deliberately left alone: dropping the entry criterion
    would empty the cohort rather than repair it, so that case stays a finding for
    :func:`unreadable_value_filter_criteria` to report.

    :param expression: a CIRCE cohort expression, modified in place.
    :returns: one record per criterion actually removed, in removal order, each::

            {"ruleIndex": int,          # index in InclusionRules BEFORE the drop
             "rule": str,               # the rule's name before the drop
             "ruleAfter": str | None,   # after; None when the rule left the file
             "outcome": DROP_OUTCOME_*,
             "unreadable": [{"criteriaType", "attributes", "codesetId"}],
             "summary": str}            # the one-line human form

        The caller writes these into the emitted payload under
        :data:`DROPPED_CRITERIA_KEY`. Structured rather than a bare line because two
        readers replay them: the delivery gate reconciles the store's rule multiset
        against ``rule``/``ruleAfter``/``outcome`` before comparing, and it re-checks
        each ``unreadable`` entry against :func:`unreadable_value_attributes` so a
        record cannot explain away a removal it does not describe. A criterion this
        function cannot reach is absent from the list and stays a finding for
        :func:`unreadable_value_filter_criteria`.
    """
    dropped: list[dict[str, Any]] = []
    kept_rules: list[dict[str, Any]] = []

    for rule_index, rule in enumerate(expression.get("InclusionRules") or []):
        if not isinstance(rule, dict):
            kept_rules.append(rule)
            continue
        rule_expression = rule.get("expression")
        if not isinstance(rule_expression, dict):
            kept_rules.append(rule)
            continue

        name = rule.get("name", "")
        # Top-level members, in the order `_build_grouped_inclusion_rule` emits
        # them, so a surviving index maps onto a segment of the joined rule name.
        members = list(rule_expression.get("CriteriaList") or []) + list(
            rule_expression.get("Groups") or []
        )
        original_count = len(members) + len(
            rule_expression.get("DemographicCriteriaList") or []
        )

        before = len(dropped)
        _prune_group_expression(rule_expression, name, dropped)
        if len(dropped) == before:
            kept_rules.append(rule)
            continue

        survivors = list(rule_expression.get("CriteriaList") or []) + list(
            rule_expression.get("Groups") or []
        )
        kept_indices = [
            index
            for index, member in enumerate(members)
            if any(member is survivor for survivor in survivors)
        ]
        kept_indices += list(range(len(members), original_count))

        # Every criterion removed from THIS rule shares one outcome: whatever happened
        # to the rule they sat in. Filled in here rather than at removal time because
        # neither the survival nor the rewritten name is known until the walk is done.
        records = dropped[before:]
        if _group_is_empty(rule_expression):
            for record in records:
                record.update(
                    ruleIndex=rule_index, ruleAfter=None,
                    outcome=DROP_OUTCOME_RULE_REMOVED,
                )
            continue
        renamed = _rename_after_drop(name, kept_indices, original_count)
        rule["name"] = renamed
        for record in records:
            record.update(
                ruleIndex=rule_index,
                ruleAfter=renamed,
                outcome=(
                    DROP_OUTCOME_RULE_KEPT
                    if renamed == name
                    else DROP_OUTCOME_RULE_RENAMED
                ),
            )
        kept_rules.append(rule)

    if "InclusionRules" in expression:
        expression["InclusionRules"] = kept_rules
    return dropped


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


def _criterion_locations(expression: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """``(where, criterion entry)`` for every criterion in the expression.

    ``where`` is the rule name for an ``InclusionRules`` entry and the section name
    otherwise, so a finding can name the rule without the reader reopening the file.
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

    return locations


def criteria_types_by_codeset(expression: dict[str, Any]) -> dict[Any, set[str]]:
    """``CodesetId`` -> the CIRCE criteria types that read it, across the whole expression.

    A concept set may be read by more than one criterion, and a set read by two different
    CDM tables has no single domain. Callers that must decide what a set is *for* — not
    only whether it is wrong — read that here rather than re-deriving it, so the criteria
    walk and :data:`CRITERIA_TYPE_DOMAINS` stay the one authority on the question.

    :param expression: a CIRCE cohort expression.
    :returns: codeset id -> criteria type names; a set nothing references is absent, which
        is distinct from a set referenced by an unmodelled type.
    """
    by_codeset: dict[Any, set[str]] = {}
    for _where, entry in _criterion_locations(expression):
        for criteria_type, codeset_id in _criterion_references(entry):
            by_codeset.setdefault(codeset_id, set()).add(criteria_type)
    return by_codeset


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
    findings: list[str] = []
    for where, entry in _criterion_locations(expression):
        for criteria_type, codeset_id in _criterion_references(entry):
            allowed = CRITERIA_TYPE_DOMAINS.get(criteria_type)
            if allowed is None:
                continue
            concept_set = _find_concept_set(expression, codeset_id)
            if concept_set is None:
                continue
            domains = concept_set_domains(concept_set)
            if not domains or domains & allowed:
                continue
            findings.append(
                f"{where}: {criteria_type} over codeset {codeset_id} "
                f"{concept_set.get('name')!r} ({', '.join(sorted(domains))})"
            )
    return findings


def partially_readable_criteria(expression: dict[str, Any]) -> list[str]:
    """Criteria whose table reads SOME but not all of their concept set. A report.

    :func:`refuse_domain_contradiction` and :func:`domain_mismatched_criteria` fire
    only when EVERY concept is out of domain, so one in-domain concept carries a set
    whose rest are silently unreadable. Tightening that predicate was considered and
    measured, and rejected in both candidate forms:

    - A majority or ratio threshold separates this corpus cleanly -- of 552
      criterion -> concept-set references in ``tmp/tte_cold6_20260908``, 549 are
      fully readable, 3 read at most a third, and none sit between. But all three are
      partially working exclusions ("Pregnancy/Nursing" read as ``Observation`` over
      a set that is mostly Condition and Procedure), so refusing them deletes an
      exclusion that today applies to some patients. The real repair is a mapping
      change, not a gate change.
    - Skipping ``isExcluded`` items empties the domain set for an all-excluded set,
      and the gate returns early on an empty one, so that set would move from checked
      to silently passed. It is unmeasurable here besides: no concept set in the store
      carries a single excluded item.

    So the gate stays binary and this reports what it deliberately does not judge.
    Silent, like the gate, on an unmodelled criteria type, a dangling ``CodesetId``,
    a set with no readable ``DOMAIN_ID``, and a set nothing at all can be read from --
    that last one is the gate's own finding, and reporting it twice is noise.

    :param expression: a CIRCE cohort expression.
    :returns: ``"<where>: <CriteriaType> over codeset <id> <name!r> reads N of M
        concepts (<unreadable domains>)"``, one per partially readable reference.
    """
    findings: list[str] = []
    for where, entry in _criterion_locations(expression):
        for criteria_type, codeset_id in _criterion_references(entry):
            allowed = CRITERIA_TYPE_DOMAINS.get(criteria_type)
            if allowed is None:
                continue
            concept_set = _find_concept_set(expression, codeset_id)
            if concept_set is None:
                continue
            readable, unreadable = _split_items_by_readability(concept_set, allowed)
            if not readable or not unreadable:
                continue
            lost = sorted({domain for _item, domain in unreadable})
            findings.append(
                f"{where}: {criteria_type} over codeset {codeset_id} "
                f"{concept_set.get('name')!r} reads {len(readable)} of "
                f"{len(readable) + len(unreadable)} concepts "
                f"({len(unreadable)} unreadable: {', '.join(lost)})"
            )
    return findings


def _split_items_by_readability(
    concept_set: dict[str, Any], allowed: frozenset[str]
) -> tuple[list[Any], list[tuple[Any, str]]]:
    """Partition a set's items into those the table can read and those it cannot.

    Counts every item, excluded ones included, for the same reason
    :func:`concept_set_domains` does: an ``isExcluded`` item is still a claim about
    which table the set belongs to, and dropping them is what turns an all-excluded
    set into one with no readable domain at all.
    """
    readable: list[Any] = []
    unreadable: list[tuple[Any, str]] = []
    for item in (concept_set.get("expression") or {}).get("items") or []:
        raw = (item.get("concept") or {}).get("DOMAIN_ID")
        if not isinstance(raw, str):
            continue
        domains = {
            _DOMAIN_ABBREVIATIONS.get(part.strip(), part.strip())
            for part in raw.split("/")
            if part.strip()
        }
        if domains & allowed:
            readable.append(item)
        else:
            unreadable.append((item, raw))
    return readable, unreadable


# --------------------------------------------------------------------------
# a criterion against the protocol line it was extracted from
# --------------------------------------------------------------------------

#: A naming word shorter than this is not compared as a substring. Without the floor,
#: "ap" (alkaline phosphatase) matches "therapy" and every criterion looks grounded.
_SUBSTRING_FLOOR = 4

UNGROUNDED_SHAPE_UNNAMED = "line-names-nothing-it-claims"
UNGROUNDED_SHAPE_LINE_INSIDE_NAME = "line-inside-the-name"


def _line_names_the_criterion(claimed: set[str], line: set[str]) -> bool:
    """Does ``line`` name any of the words the criterion claims?

    Whole-word overlap first, then substring in either direction above
    :data:`_SUBSTRING_FLOOR`. The substring arm is not decoration: it is what keeps
    ``Hemodialysis`` off the report when its line says ``Dialysis required``, and
    ``Hyperosmolar Hyperglycemic State`` off it when the line says ``glycemic``. Both
    are readings of their line under any honest account of what "names" means, and both
    fail a whole-word test. It costs nothing on the fabrications: no word of
    ``Hypertension`` or ``Total Bilirubin`` is a substring of anything in their lines.
    """
    if claimed & line:
        return True
    for word in claimed:
        if len(word) < _SUBSTRING_FLOOR:
            continue
        for other in line:
            if len(other) < _SUBSTRING_FLOOR:
                continue
            if word in other or other in word:
                return True
    return False


def ungrounded_criteria(
    expression: Mapping[str, Any], study: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    """Emitted criteria whose own ``protocolLine`` does not support what they claim.

    Returns ``(records, summary)``. **Report only** -- no caller may turn a record here
    into a refusal, and the reason is measured rather than cautious: over the six trials
    of the 2026-09-14 delivery the check fires 21 times, and nine of those carry a defect
    finding in that delivery's own audit -- ARISTOTLE exclusion 24, CARMELINA exclusion
    5, EMPA-REG inclusions 8 through 12, PLATO inclusion 8 and LEADER exclusion 5. The
    other twelve are decompositions of an umbrella the line does name (``Acute coronary
    syndrome`` into STEMI / NSTEMI / unstable angina in two trials, ``End-stage liver
    disease`` into cirrhosis and advanced fibrosis), one line truncated mid-sentence by
    ``pdftotext`` (EMPA-REG exclusion 8, whose criterion is correct and whose LINE is the
    defect), and one lay paraphrase (PLATO exclusion 24: ``blood clotting agents`` for
    anticoagulants). Refusing at 9-in-21 deletes more correct criteria than it removes
    invented ones -- the trade
    :func:`~src.agents.planner.decomposer._grounded_span` already declines to make one
    stage earlier, for the same reason and in the same direction.

    Two shapes, both taken from what the corpus shows rather than from a threshold:

    ``line-names-nothing-it-claims``
        No naming word of the criterion -- ``sourceText``, ``description`` or
        ``conceptSetName``, pooled, because the line may use an abbreviation the
        expansion does not repeat and vice versa -- appears in its own ``protocolLine``.
        Pooling matters: ``Alanine aminotransferase`` under a line saying ``ALT`` is
        grounded through the description ``ALT > 2X ULN``, and pooling drops the fires
        from 41 to 20 without losing one known fabrication.

    ``line-inside-the-name``
        The line's naming words are a strict subset of the criterion's own
        ``description``, so the line contributed nothing the name did not already carry.
        One instance in the corpus: ARISTOTLE exclusion 24, ``protocolLine`` ``"Prior"``
        against the name ``"Prior ischemic stroke"`` -- the left half of a split across
        protocol exclusion 18 ``Recent ischemic stroke (within 7 days)``, emitted as an
        all-time exclusion that contradicts the trial's own inclusion 3(b).

    Length is deliberately absent from both. Over the 251 emitted criteria the six known
    fabrications carry 1, 3, 3, 3, 8 and 23 naming words; a cut at 3 words takes 35
    criteria and 31 of them are terse and correct.

    ``study`` supplies the criteria rows and ``expression`` only the emission link, so a
    criterion the file refused is not reported: eight non-emitted criteria fire over the
    same corpus -- group labels whose ``protocolLine`` is empty, and a list header
    ``>=2 of the following:`` -- and none of them reached a rule. A file carrying no
    ``_criterionConceptSetRefs`` yields no records and says so in ``summary``, because a
    check whose only output is silence cannot be told from one that never ran.

    A criterion carrying no ``protocolLine`` at all is counted in ``summary`` and never
    reported. Absent provenance is a gap in what can be judged, not evidence of a claim
    the line fails to support, and booking it as the latter would put every artifact
    exported before ``protocolLine`` existed at the top of the report.
    """
    refs = expression.get(CRITERION_CONCEPT_SET_REFS_KEY)
    if not isinstance(refs, Mapping):
        return [], (
            f"grounding not run: the file carries no {CRITERION_CONCEPT_SET_REFS_KEY}, "
            "so which criteria it emitted is unknown"
        )
    emitted = {str(key) for key in refs}

    # The store nests criteria under `eligibility`, the same place
    # `verify_circe_delivery.criteria_index` reads them from. Read anywhere else and
    # this returns "0 of 0" on every real artifact while a flattened test fixture keeps
    # it green -- which is how it behaved for one measured run before the gate was
    # pointed at the delivery and printed exactly that.
    eligibility = study.get("eligibility")
    if not isinstance(eligibility, Mapping):
        return [], (
            "grounding not run: the store study carries no `eligibility` block, so it "
            "holds no criteria rows to read a protocolLine from"
        )

    records: list[dict[str, Any]] = []
    considered = 0
    no_line = 0
    for role in ("inclusion", "exclusion"):
        rows = eligibility.get(f"{role}Criteria")
        if not isinstance(rows, Sequence):
            continue
        for criterion in rows:
            if not isinstance(criterion, Mapping):
                continue
            if f"{role}:{criterion.get('id')}" not in emitted:
                continue
            considered += 1
            line_text = criterion.get("protocolLine") or ""
            line = naming_words(line_text)
            if not line:
                no_line += 1
                continue
            description = naming_words(criterion.get("description"))
            claimed = (
                naming_words(criterion.get("sourceText"))
                | description
                | naming_words(criterion.get("conceptSetName"))
            )
            if claimed and not _line_names_the_criterion(claimed, line):
                shape = UNGROUNDED_SHAPE_UNNAMED
            elif line < description:
                shape = UNGROUNDED_SHAPE_LINE_INSIDE_NAME
            else:
                continue
            records.append({
                "role": role,
                "id": criterion.get("id"),
                "description": criterion.get("description") or "",
                "protocolLine": line_text,
                "shape": shape,
            })

    gap = ""
    if no_line:
        noun = "criterion" if no_line == 1 else "criteria"
        gap = f", {no_line} emitted {noun} carries no protocolLine and was not judged"
    summary = (
        f"{len(records)} of {considered} emitted criteria are not supported by their own "
        f"protocolLine (report only){gap}"
    )
    return records, summary
