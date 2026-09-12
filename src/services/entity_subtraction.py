"""Turn a criterion's entity exception into concept-set subtractions.

The two halves meet here, the same shape as :mod:`route_subtraction`:

- :mod:`entity_exception` reads what the criterion asked to leave out, off the text.
- the mapper says which concepts that entity is.

This decides what the concept set carries as ``isExcluded``. Pure: no LLM, no
embedding, no database. Given a base item list and the excepted concepts, it
returns the repaired items.

Two guards, and the first one is why this module exists rather than a one-liner
--------------------------------------------------------------------------------
**A base identical to the excepted set is refused.** That is the shape the
2026-09-14 delivery actually shipped: LEADER codeset 54 'insulin other than
human NPH insulin' holds the same 26 ids as codeset 12 'human NPH insulin', so
subtracting the excepted set from it leaves nothing. Emitting a concept set whose
every member is ``isExcluded`` resolves to the empty set -- a different wrong
answer, not a repair, and one that would silently turn an over-broad ABSENCE rule
into a no-op rule. Refusing keeps the existing over-inclusion, which stays
visible to `tests/test_concept_set_negation_lints.py`.

**An excepted concept the base does not literally carry is appended, not
dropped.** Circe resolves an exclusion as an anti-join over the *resolved*
closure, so an excepted ancestor removes leaves whether or not it is itself a
literal member. Gold relies on exactly this -- its `[CKim] systemic
glucocorticoid` set carries 136 excluded `Clinical Drug Form` items with
``includeDescendants``, covering thousands of leaves -- and
:func:`route_subtraction.compute_route_subtraction` appends on the same basis.

Residual risk, stated rather than mitigated
-------------------------------------------
An appended excepted concept that is an ancestor of the whole base wipes the set
without any literal item flipping, so the degenerate guard above cannot see it.
Detecting that needs `concept_ancestor`, which this layer deliberately does not
reach. The caller supplies excepted concepts that came from mapping the excepted
*phrase*, the same discipline `route_subtraction` relies on when it only ever
subtracts forms it fetched from inside the base's own closure. ``appended`` is
returned so a caller with a vocabulary can check them.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExceptedConcept:
    """One concept the criterion asked to leave out.

    :param concept_id: the OMOP concept id.
    :param concept_name: the concept's name, for the appended item and for logging.
    """

    concept_id: int
    concept_name: str = ""


@dataclass(frozen=True)
class EntitySubtraction:
    """What the concept set becomes, and what could not be applied.

    :param items: the repaired items. On a refusal these are the originals,
        unchanged.
    :param excluded_in_place: base members flipped to ``isExcluded``.
    :param appended: excepted concepts added as new ``isExcluded`` items because
        the base did not literally carry them.
    :param refused: why nothing was applied; empty when it was.
    """

    items: list[dict] = field(default_factory=list)
    excluded_in_place: list[int] = field(default_factory=list)
    appended: list[int] = field(default_factory=list)
    refused: str = ""


def _concept_id(item: dict) -> int | None:
    return (item.get("concept") or {}).get("CONCEPT_ID")


def apply_entity_subtraction(
    items: list[dict],
    excepted: list[ExceptedConcept],
) -> EntitySubtraction:
    """Mark the excepted entity's concepts ``isExcluded`` on a concept set.

    :param items: the base concept set's Atlas-JSON expression items. Not
        mutated; the result carries a copy.
    :param excepted: the concepts the excepted phrase mapped to.
    :returns: the repaired items, or the originals with ``refused`` set.
    """
    if not items or not excepted:
        return EntitySubtraction(items=items)

    excepted_ids = {e.concept_id for e in excepted if e.concept_id is not None}
    if not excepted_ids:
        return EntitySubtraction(items=items)

    included_ids = {
        cid for item in items
        if not item.get("isExcluded") and (cid := _concept_id(item)) is not None
    }

    # The inversion signature. Subtracting here leaves no included member at all.
    if included_ids and included_ids <= excepted_ids:
        return EntitySubtraction(
            items=items,
            refused=(
                f"every one of the {len(included_ids)} included members is in the "
                f"excepted set, so the base was mapped to its own exception; "
                f"subtracting would empty the concept set"
            ),
        )

    repaired = deepcopy(items)
    excluded_in_place: list[int] = []
    for item in repaired:
        cid = _concept_id(item)
        if cid in excepted_ids and not item.get("isExcluded"):
            item["isExcluded"] = True
            excluded_in_place.append(cid)

    carried = {cid for item in repaired if (cid := _concept_id(item)) is not None}
    appended: list[int] = []
    for concept in excepted:
        if concept.concept_id in carried or concept.concept_id is None:
            continue
        carried.add(concept.concept_id)
        appended.append(concept.concept_id)
        repaired.append({
            "concept": {
                "CONCEPT_ID": concept.concept_id,
                "CONCEPT_NAME": concept.concept_name,
            },
            "isExcluded": True,
            "includeDescendants": True,
            "includeMapped": False,
        })

    return EntitySubtraction(
        items=repaired,
        excluded_in_place=excluded_in_place,
        appended=appended,
    )


@dataclass(frozen=True)
class ExceptionResolution:
    """The outcome of mapping an exception's two halves separately.

    :param mapping: the repaired base mapping, in the shape
        ``_recommend_seeded_concept_set`` returns. None when the exception was
        not applied and the caller must fall back to its existing behaviour.
    :param subtraction: what was applied, None on a fallback.
    :param fallback_reason: why nothing was applied; empty when something was.
    """

    mapping: dict | None = None
    subtraction: EntitySubtraction | None = None
    fallback_reason: str = ""


def _included_concepts(mapping: dict) -> list[ExceptedConcept]:
    items = ((mapping or {}).get("expression") or {}).get("items") or []
    out = []
    for item in items:
        if item.get("isExcluded"):
            continue
        concept = item.get("concept") or {}
        cid = concept.get("CONCEPT_ID")
        if cid is not None:
            out.append(ExceptedConcept(cid, concept.get("CONCEPT_NAME") or ""))
    return out


def resolve_entity_exception(exception, map_phrase) -> ExceptionResolution:
    """Map an exception's base and excepted phrases separately, then subtract.

    Two mapper calls instead of one. The single call is the defect: handed the
    whole string "insulin other than human NPH insulin", the mapper returns the
    NPH set, because the tail dominates the embedding.

    Every failure falls back rather than half-applying. A base that will not map,
    an excepted phrase that will not map, or a subtraction the guards refuse all
    leave the caller's existing behaviour in place -- the same rule
    :mod:`route_subtraction` states for undecidable forms. A partial subtraction
    would be a claim the pipeline cannot support, not a repair.

    :param exception: from :func:`entity_exception.detect_entity_exception`.
    :param map_phrase: maps one phrase to a mapping dict carrying
        ``expression.items``. May raise; a raise is a fallback, not an error.
    :returns: the repaired mapping, or the reason nothing was applied.
    """
    try:
        base = map_phrase(exception.base)
    except Exception as exc:
        return ExceptionResolution(
            fallback_reason=f"base phrase {exception.base!r} did not map: {exc}")

    base_items = ((base or {}).get("expression") or {}).get("items") or []
    if not base_items:
        return ExceptionResolution(
            fallback_reason=f"base phrase {exception.base!r} mapped to no concepts")

    excepted: list[ExceptedConcept] = []
    for phrase in exception.excepted:
        try:
            mapped = map_phrase(phrase)
        except Exception as exc:
            return ExceptionResolution(
                fallback_reason=f"excepted phrase {phrase!r} did not map: {exc}")
        concepts = _included_concepts(mapped)
        if not concepts:
            return ExceptionResolution(
                fallback_reason=f"excepted phrase {phrase!r} mapped to no concepts")
        excepted.extend(concepts)

    subtraction = apply_entity_subtraction(base_items, excepted)
    if subtraction.refused:
        return ExceptionResolution(fallback_reason=subtraction.refused)

    repaired = dict(base)
    repaired["expression"] = dict(base.get("expression") or {})
    repaired["expression"]["items"] = subtraction.items
    repaired["name"] = exception.text
    return ExceptionResolution(mapping=repaired, subtraction=subtraction)
