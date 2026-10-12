"""Choose a cohort's disease entry anchor from the trial's own registered condition.

Why this module exists
----------------------
A drug-anchored cohort whose comparator is a placebo arm cannot enter on the study
drug -- the arm's defining rule requires zero occurrences of it -- so the entry is
swapped to a ``ConditionOccurrence``. Something has to say *which* condition.

Two answers have already been tried and both were wrong in the same way: they
decided by identity rather than by clinical content. A table keyed on NCT id gave
three benchmark trials a tabled concept and an emptied rule set. Removing it left
"the first Condition concept set in document order", which is not a clinical fact
at all -- LEADER's first Condition rule is ``LV systolic or diastolic dysfunction``,
one of several alternative cardiovascular-risk qualifiers, so its comparator entered
on a fraction of the trial population while CARMELINA and EMPA-REG were correct only
because their diabetes rule happened to be written first.

The trial already publishes what it is about. ClinicalTrials.gov carries
``protocolSection.conditionsModule.conditions`` -- ``["Diabetes", "Diabetes Mellitus,
Type 2"]`` for LEADER (NCT01179048), ``["Atrial Fibrillation", "Atrial Flutter"]``
for ARISTOTLE (NCT00412984). That is data the trial states about itself, not a table
anyone here maintains, and it is what the anchor is chosen against.

The rule
--------
1. **Candidates** are the ``ConditionOccurrence`` concept sets the study's own
   ``InclusionRules`` read under a PRESENCE occurrence, in document order. An
   absence rule is never a candidate: a cohort cannot enter on a condition its own
   criteria exclude. This alone is load-bearing -- ARISTOTLE's ``AF/Flutter due to
   reversible causes`` and CAROLINA's ``Acute coronary syndrome`` are exclusions
   that would otherwise stand in for the real indication.
2. **Match** a candidate when one of its included members IS a concept the
   registered condition maps to. The registered strings go through the same Agent 2
   mapper the criteria do (``TTEService._registered_condition_concept_ids``); this
   module compares concept ids and reads no name (RFC-016 §4, C8). It used to compare
   the lowercase word sets of the registered string and of the set's and its members'
   names. Where ``"Diabetes Mellitus, Type 2"`` maps to 201826, LEADER's
   ``Type 2 diabetes`` set holds it and its ``Symptomatic coronary heart disease`` set
   -- whose member is 'Coronary artery disease due to type 2 diabetes mellitus', a
   different concept -- does not.
3. **Decide.** Exactly one matching candidate wins. No match at all, or two candidates
   matching with different concepts, both raise: both are exactly the arbitrary pick
   this module exists to stop. Two candidates holding the *same concepts* under
   different codeset ids -- CAROLINA carries ``Type 2 diabetes`` twice -- build the
   identical cohort, so the first is taken.
4. **No registered condition** is a missing input, not a licence to guess. With one
   candidate there is no choice to make and it is taken; with several, the pick
   would be arbitrary and it raises. A registered condition the mapper maps to nothing
   is not "no registered condition": it raises with the strings.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from typing import Any

#: The payload record of the anchor a disease entry was chosen from: the registered
#: condition strings, the concept ids the mapper gave them, and the chosen codeset. The
#: delivery gate re-derives the choice from the store expression with those ids.
DISEASE_ANCHOR_KEY = "_diseaseAnchor"

# An entry criterion reads condition_occurrence, so only Condition-domain sets can
# anchor one. Kept as a constant so the walk below and any future caller agree.
_ENTRY_CRITERIA_KEY = "ConditionOccurrence"


class DiseaseAnchorError(ValueError):
    """No single Condition concept set answers to the trial's registered condition.

    A ``ValueError`` so it lands in the same handling as the generator's other
    refusals (``circe_lint.refuse_domain_contradiction``): the arm surfaces as
    unbuildable and the export reports a missing arm, rather than shipping a
    plausible-looking cohort anchored on the wrong disease.
    """


@dataclass(frozen=True)
class AnchorCandidate:
    """One Condition concept set a study's presence rules read.

    :ivar codeset_id: the ``CodesetId`` an entry criterion would carry.
    :ivar name: the concept set's name, for the refusal message only.
    :ivar members: the set's included concept ids.
    :ivar fingerprint: the set's items reduced to what changes the cohort, so two
        codeset ids holding the same concepts can be recognised as the same set.
    """

    codeset_id: int
    name: str
    members: frozenset[int] = field(default_factory=frozenset)
    fingerprint: frozenset[tuple[Any, ...]] = field(default_factory=frozenset)


def _is_presence(criterion: dict[str, Any]) -> bool:
    """False only for an explicit "exactly zero occurrences" criterion."""
    occurrence = criterion.get("Occurrence") or {}
    return not (occurrence.get("Type") == 0 and occurrence.get("Count") == 0)


def _walk_criteria(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Every criterion under a rule expression, descending into nested groups."""
    for criterion in node.get("CriteriaList") or []:
        if isinstance(criterion, dict):
            yield criterion
    for group in node.get("Groups") or []:
        if isinstance(group, dict):
            yield from _walk_criteria(group)


def anchor_candidates(expression: dict[str, Any]) -> list[AnchorCandidate]:
    """Condition concept sets the study's presence rules read, in document order.

    A set read by both a presence and an absence rule is a candidate -- the presence
    reading is what an entry would express. A set read only by absence rules is not.

    :param expression: a CIRCE cohort expression dict.
    :returns: one candidate per distinct codeset id, first-seen order preserved.
    """
    concept_sets: dict[Any, dict[str, Any]] = {}
    for concept_set in expression.get("ConceptSets") or []:
        if isinstance(concept_set, dict):
            concept_sets[concept_set.get("id")] = concept_set

    ordered_ids: list[int] = []
    presence_ids: set[int] = set()
    for rule in expression.get("InclusionRules") or []:
        for criterion in _walk_criteria((rule or {}).get("expression") or {}):
            body = (criterion.get("Criteria") or {}).get(_ENTRY_CRITERIA_KEY)
            if not isinstance(body, dict):
                continue
            codeset_id = body.get("CodesetId", 0)
            if not codeset_id:
                continue
            if codeset_id not in ordered_ids:
                ordered_ids.append(codeset_id)
            if _is_presence(criterion):
                presence_ids.add(codeset_id)

    candidates: list[AnchorCandidate] = []
    for codeset_id in ordered_ids:
        if codeset_id not in presence_ids:
            continue
        concept_set = concept_sets.get(codeset_id) or {}
        name = concept_set.get("name")
        members: set[int] = set()
        fingerprint: set[tuple[Any, ...]] = set()
        for item in (concept_set.get("expression") or {}).get("items") or []:
            concept = (item or {}).get("concept") or {}
            concept_id = concept.get("CONCEPT_ID")
            if concept_id is not None and not (item or {}).get("isExcluded"):
                members.add(int(concept_id))
            fingerprint.add(
                (
                    concept_id,
                    bool((item or {}).get("includeDescendants")),
                    bool((item or {}).get("includeMapped")),
                    bool((item or {}).get("isExcluded")),
                )
            )
        candidates.append(
            AnchorCandidate(
                codeset_id,
                name if isinstance(name, str) else "",
                frozenset(members),
                frozenset(fingerprint),
            )
        )
    return candidates


def select_disease_anchor(
    expression: dict[str, Any],
    registered_concept_ids: Collection[int] | None,
) -> int:
    """The ``CodesetId`` a disease entry should anchor on.

    :param expression: the study's CIRCE expression, before the entry swap.
    :param registered_concept_ids: the concept ids the trial's registered conditions
        (``trialMetadata.conditions``) map to through the Agent 2 mapper; None when the
        trial registers no condition.
    :returns: the winning concept set's ``CodesetId``.
    :raises DiseaseAnchorError: when no candidate exists, when the registered condition
        matches none of them, when two holding different concepts match it, or when the
        trial registers no condition and more than one candidate competes.
    """
    candidates = anchor_candidates(expression)
    if not candidates:
        raise DiseaseAnchorError(
            "cannot anchor the entry on a disease: the study's inclusion rules read no "
            "Condition concept set under a presence occurrence"
        )

    if registered_concept_ids is None:
        if len(candidates) == 1:
            return candidates[0].codeset_id
        raise DiseaseAnchorError(
            "cannot choose a disease anchor: the study carries no registered condition "
            "(trialMetadata.conditions) and "
            f"{len(candidates)} Condition rules compete -- "
            + ", ".join(f"{c.name!r} (codeset {c.codeset_id})" for c in candidates)
            + ". Backfill the store with scripts/backfill_registered_conditions.py"
        )

    registered = {int(cid) for cid in registered_concept_ids}
    winners = [candidate for candidate in candidates if candidate.members & registered]
    listed = ", ".join(str(cid) for cid in sorted(registered)) or "none"

    if not winners:
        raise DiseaseAnchorError(
            f"no Condition rule holds a concept the trial's registered condition maps to "
            f"({listed}); the candidates hold "
            + ", ".join(
                f"{candidate.name!r} (codeset {candidate.codeset_id}, "
                f"{sorted(candidate.members)[:5]})"
                for candidate in candidates
            )
        )
    if len(winners) > 1 and len({candidate.fingerprint for candidate in winners}) > 1:
        raise DiseaseAnchorError(
            f"two or more Condition rules hold a concept the trial's registered condition "
            f"maps to ({listed}) and they hold different concepts, so the entry would be an "
            "arbitrary pick: "
            + ", ".join(f"{c.name!r} (codeset {c.codeset_id})" for c in winners)
        )
    return winners[0].codeset_id


def expected_anchor_concept_ids(
    expression: dict[str, Any],
    registered_concept_ids: Collection[int] | None,
) -> set[int]:
    """The OMOP concept ids a disease-anchored entry built from ``expression`` must carry.

    The generator and the delivery gate answer "which condition anchors this cohort"
    from this one function, so they cannot drift apart -- the gate previously accepted
    ANY ``ConditionOccurrence`` entry on a comparator, which is how LEADER's
    ``LV systolic or diastolic dysfunction`` entry passed it.

    :param expression: the STORE study's CIRCE expression (not the emitted file's --
        codeset ids are renumbered by pruning, concept ids are not).
    :param registered_concept_ids: as :func:`select_disease_anchor` takes them; the gate
        reads them from the file's :data:`DISEASE_ANCHOR_KEY` record.
    :returns: the winning concept set's ``CONCEPT_ID`` values.
    :raises DiseaseAnchorError: on the same terms as :func:`select_disease_anchor`.
    """
    codeset_id = select_disease_anchor(expression, registered_concept_ids)
    for concept_set in expression.get("ConceptSets") or []:
        if isinstance(concept_set, dict) and concept_set.get("id") == codeset_id:
            return {
                int(concept_id)
                for concept_id in (
                    ((item or {}).get("concept") or {}).get("CONCEPT_ID")
                    for item in (concept_set.get("expression") or {}).get("items") or []
                )
                if concept_id is not None
            }
    raise DiseaseAnchorError(
        f"the chosen disease anchor (codeset {codeset_id}) has no ConceptSets entry"
    )
