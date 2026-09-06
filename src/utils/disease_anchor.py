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
   that would otherwise outscore, or stand in for, the real indication.
2. **Match** a candidate when one of its texts -- its concept-set name, or any member
   concept's ``CONCEPT_NAME`` -- carries exactly the registered condition's tokens.
   ``"Type 2 diabetes mellitus"`` and ``"Diabetes Mellitus, Type 2"`` reduce to the
   same four tokens, so word order and punctuation do not matter; ``"Type 1 diabetes
   mellitus"`` does not, because the discriminating token differs. Names are compared,
   never resolved -- no model, no network, same answer every time.
3. **Decide.** Exactly one matching candidate wins. No match at all, or two candidates
   matching, both raise: both are exactly the arbitrary pick this module exists to stop.
   The one exception is two candidates holding the *same concepts* under different
   codeset ids -- CAROLINA carries ``Type 2 diabetes`` twice, both ``[201826]``,
   ``includeDescendants`` -- where either choice builds the identical cohort, so
   document order decides nothing and the first is taken.
4. **No registered condition** is a missing input, not a licence to guess. With one
   candidate there is no choice to make and it is taken; with several, the pick
   would be arbitrary and it raises.

Why equality rather than a similarity threshold. The first version of this module
accepted the best partial overlap above zero, and studies 4/5/6 -- LEADER duplicates
that carry no type-2-diabetes rule at all -- promptly anchored on ``Symptomatic
coronary heart disease``, scoring 0.444 against ``"Diabetes Mellitus, Type 2"`` on the
strength of one member named ``Coronary artery disease due to type 2 diabetes
mellitus``. A comorbidity qualifier inside a concept name is not correspondence, and no
threshold separates it honestly: it is a coronary set that mentions diabetes. Requiring
the tokens to match exactly states the claim the anchor rests on -- this concept set
NAMES what the trial registered -- and turns every weaker resemblance into a refusal,
which is the outcome those three studies should have. The partial scores are still
computed, but only to name the closest miss in the refusal message.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

__all__ = [
    "DiseaseAnchorError",
    "AnchorCandidate",
    "anchor_candidates",
    "select_disease_anchor",
    "expected_anchor_concept_ids",
]

_TOKEN = re.compile(r"[a-z0-9]+")

# An entry criterion reads condition_occurrence, so only Condition-domain sets can
# anchor one. Kept as a constant so the walk below and any future caller agree.
_ENTRY_CRITERIA_KEY = "ConditionOccurrence"


class DiseaseAnchorError(ValueError):
    """No single Condition concept set answers to the trial's registered condition.

    A ``ValueError`` so it lands in the same handling as the generator's other
    refusals (``TTEService._refuse_domain_contradiction``): the arm surfaces as
    unbuildable and the export reports a missing arm, rather than shipping a
    plausible-looking cohort anchored on the wrong disease.
    """


class AnchorCandidate:
    """One Condition concept set a study's presence rules read.

    :ivar codeset_id: the ``CodesetId`` an entry criterion would carry.
    :ivar name: the concept set's name, for the refusal message.
    :ivar texts: every string the set offers for matching -- its own name and each
        member's ``CONCEPT_NAME``.
    :ivar fingerprint: the set's items reduced to what changes the cohort, so two
        codeset ids holding the same concepts can be recognised as the same set.
    """

    __slots__ = ("codeset_id", "name", "texts", "fingerprint")

    def __init__(
        self,
        codeset_id: int,
        name: str,
        texts: Sequence[str],
        fingerprint: frozenset[tuple[Any, ...]] = frozenset(),
    ) -> None:
        self.codeset_id = codeset_id
        self.name = name
        self.texts = list(texts)
        self.fingerprint = fingerprint

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"AnchorCandidate(codeset_id={self.codeset_id!r}, name={self.name!r})"


def _tokens(text: Any) -> frozenset[str]:
    """Lowercased alphanumeric runs of a string, as a set.

    ``"Diabetes Mellitus, Type 2"`` and ``"Type 2 diabetes mellitus"`` reduce to the
    same four tokens, which is the whole point: the registry's phrasing and the
    concept set's phrasing differ in word order and punctuation, not in content.
    """
    if not isinstance(text, str):
        return frozenset()
    return frozenset(_TOKEN.findall(text.lower()))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


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
        texts = [name] if isinstance(name, str) else []
        fingerprint: set[tuple[Any, ...]] = set()
        for item in (concept_set.get("expression") or {}).get("items") or []:
            concept = (item or {}).get("concept") or {}
            concept_name = concept.get("CONCEPT_NAME")
            if isinstance(concept_name, str):
                texts.append(concept_name)
            fingerprint.add(
                (
                    concept.get("CONCEPT_ID"),
                    bool((item or {}).get("includeDescendants")),
                    bool((item or {}).get("includeMapped")),
                    bool((item or {}).get("isExcluded")),
                )
            )
        candidates.append(
            AnchorCandidate(
                codeset_id,
                name if isinstance(name, str) else "",
                texts,
                frozenset(fingerprint),
            )
        )
    return candidates


def _score(candidate: AnchorCandidate, registered: Sequence[frozenset[str]]) -> tuple[float, str]:
    """Best (similarity, matched text) for one candidate against the registered set.

    Diagnostic only -- the decision below turns on ``_names_registered_condition``.
    A similarity is what lets the refusal message say what came closest, which is the
    difference between "this store needs a diabetes rule" and "no idea why it refused".
    """
    best = 0.0
    matched = ""
    for text in candidate.texts:
        text_tokens = _tokens(text)
        for condition_tokens in registered:
            value = _jaccard(text_tokens, condition_tokens)
            if value > best:
                best, matched = value, text
    return best, matched


def _names_registered_condition(
    candidate: AnchorCandidate, registered: Sequence[frozenset[str]]
) -> str | None:
    """The candidate's own text that carries exactly a registered condition's tokens.

    Returns None when nothing the candidate is called reduces to what the trial
    registered. Partial overlap is deliberately not a match -- see the module docstring
    for the LEADER-duplicate case that forced this.
    """
    for text in candidate.texts:
        if _tokens(text) in registered:
            return text
    return None


def select_disease_anchor(
    expression: dict[str, Any],
    registered_conditions: Sequence[str] | None,
) -> int:
    """The ``CodesetId`` a disease entry should anchor on.

    :param expression: the study's CIRCE expression, before the entry swap.
    :param registered_conditions: ``trialMetadata.conditions`` -- the strings
        ClinicalTrials.gov carries under
        ``protocolSection.conditionsModule.conditions``.
    :returns: the winning concept set's ``CodesetId``.
    :raises DiseaseAnchorError: when no candidate exists, when the registered
        condition matches none of them, when two match it equally well, or when the
        trial registers no condition and more than one candidate competes.
    """
    candidates = anchor_candidates(expression)
    if not candidates:
        raise DiseaseAnchorError(
            "cannot anchor the entry on a disease: the study's inclusion rules read no "
            "Condition concept set under a presence occurrence"
        )

    registered = [_tokens(condition) for condition in registered_conditions or []]
    registered = [tokens for tokens in registered if tokens]

    if not registered:
        if len(candidates) == 1:
            return candidates[0].codeset_id
        raise DiseaseAnchorError(
            "cannot choose a disease anchor: the study carries no registered condition "
            "(trialMetadata.conditions) and "
            f"{len(candidates)} Condition rules compete -- "
            + ", ".join(f"{c.name!r} (codeset {c.codeset_id})" for c in candidates)
            + ". Backfill the store with scripts/backfill_registered_conditions.py"
        )

    registered_set = set(registered)
    matched = [
        (candidate, _names_registered_condition(candidate, registered_set))
        for candidate in candidates
    ]
    winners = [(candidate, text) for candidate, text in matched if text is not None]
    listed = ", ".join(repr(c) for c in registered_conditions or [])

    if not winners:
        near = sorted(
            ((*_score(candidate, registered), candidate) for candidate in candidates),
            key=lambda row: row[0],
            reverse=True,
        )[:3]
        raise DiseaseAnchorError(
            f"no Condition rule names the trial's registered condition ({listed}); "
            "closest were "
            + ", ".join(
                f"{candidate.name!r} (codeset {candidate.codeset_id}, "
                f"{score:.3f} via {text!r})"
                for score, text, candidate in near
            )
        )
    if len(winners) > 1 and len({candidate.fingerprint for candidate, _ in winners}) > 1:
        raise DiseaseAnchorError(
            f"two or more Condition rules name the trial's registered condition ({listed}) "
            "and they hold different concepts, so the entry would be an arbitrary pick: "
            + ", ".join(
                f"{candidate.name!r} (codeset {candidate.codeset_id}, via {text!r})"
                for candidate, text in winners
            )
        )
    return winners[0][0].codeset_id


def expected_anchor_concept_ids(
    expression: dict[str, Any],
    registered_conditions: Sequence[str] | None,
) -> set[int]:
    """The OMOP concept ids a disease-anchored entry built from ``expression`` must carry.

    The generator and the delivery gate answer "which condition anchors this cohort"
    from this one function, so they cannot drift apart -- the gate previously accepted
    ANY ``ConditionOccurrence`` entry on a comparator, which is how LEADER's
    ``LV systolic or diastolic dysfunction`` entry passed it.

    :param expression: the STORE study's CIRCE expression (not the emitted file's --
        codeset ids are renumbered by pruning, concept ids are not).
    :param registered_conditions: ``trialMetadata.conditions``.
    :returns: the winning concept set's ``CONCEPT_ID`` values.
    :raises DiseaseAnchorError: on the same terms as :func:`select_disease_anchor`.
    """
    codeset_id = select_disease_anchor(expression, registered_conditions)
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
