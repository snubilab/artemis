"""The one place a criterion's mapper seed is chosen.

The seed is the criterion's own ``entity_text`` (stored as ``sourceText``), or -- when the
annotation step quoted a verified ``base_span`` for a stated exception -- that fragment.
An extracted criterion (one that carries the ``protocolLine`` it came from) gets nothing
else: no fallback to its human-facing ``description``, and no cutting of time phrases out
of any text. A row that was never extracted -- typed in the UI, or built by the
natural-language draft path -- has no ``entity_text`` and no line; its ``description`` is
the entity as entered, and is the seed as written.

Both of those are removed in RFC-016 step 2 (inventory A10). The fallback handed the mapper
a sentence written for a reader, and ``strip_window_expressed_temporal`` then cut "within 3
years" / "prior to randomisation" out of it with a word table so the intent router would
accept it -- reading natural language to change what the mapper is asked. A criterion whose
mandatory ``entity_text`` is empty is now refused as ``missing-entity-text`` before mapping
(``TTEService._build_seeded_eligibility_rule``) and recorded under
:data:`MISSING_ENTITY_CRITERIA_KEY`. An ``entity_text`` that itself carries a time phrase
is mapped as extracted; the remedy for that is extraction, not a text rule here.

Both call sites in ``tte_service`` -- the ChromaDB batch pre-fetch and
``_build_seeded_eligibility_rule`` -- must read the seed from here, or the candidates
pre-fetched under one string are handed to a mapper that asked for another.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def criterion_mapper_seed(criterion: Mapping[str, Any]) -> str:
    """The text the concept mapper should be asked to resolve for ``criterion``.

    The annotation's verified ``base_span`` first (RFC-016 addendum: a seed that carries
    a whole exception clause is mapped tail-first, so the fragment naming the base set
    is the seed), else the criterion's own ``entity_text`` (``sourceText``). A criterion
    with neither and no ``protocolLine`` was never extracted, and its ``description`` is
    its entity as entered.

    :param criterion: a store eligibility-criterion dict.
    :returns: the seed text, whitespace-collapsed; ``""`` when an extracted criterion has
        no entity text -- the caller refuses that as ``missing-entity-text``, and should.
    """
    from src.services.criterion_annotation import stated_base

    base = stated_base(criterion)
    if base:
        return base
    entity = " ".join((criterion.get("sourceText") or "").split())
    if entity or (criterion.get("protocolLine") or "").strip():
        return entity
    return " ".join((criterion.get("description") or "").split())


#: Where the record below is written in a study's ``structuredExpression``, and read from
#: the delivered payload by ``scripts/verify_circe_delivery.py``. Same present-and-empty
#: contract as ``_defaultedWindowCriteria``: an ABSENT key means the artifact predates
#: the record, while a key present and empty is the positive claim that every criterion
#: reaching the mapper carried its own ``entity_text``. Only one of those two can be made
#: by an absent key, and it is the wrong one.
MISSING_ENTITY_CRITERIA_KEY = "_missingEntityCriteria"


def criterion_entity_text_missing(criterion: Mapping[str, Any]) -> bool:
    """Did the extraction leave this criterion's MANDATORY ``entity_text`` empty?

    ``entity_text`` is the only text the concept mapper is ever given, which is why
    ``agent1/prompts.NCT_SYSTEM_PROMPT`` makes it mandatory on every criterion with no
    ``sub_criteria`` (``8bbd50d``). When it is empty there is nothing to seed the mapper
    with (:func:`criterion_mapper_seed` returns ``""``) and the criterion is refused as
    ``missing-entity-text``. This function is the one place that fact is decided, so the
    record, the refusal, and the seed itself cannot disagree about which rows it covers.

    Reads the store column ``sourceText``, which carries the IR's ``entity_text``:
    ``_criterion_dict_from_ir_item`` assigns ``source_text = entity_text``, while the
    IR's own ``source_text`` -- the verbatim protocol line -- reaches the store as
    ``protocolLine``. The two names look alike and are not the same field.

    A GROUP LABEL is excluded, and that exclusion is the mandate's own: null is correct
    "ONLY on a parent row that has [sub_criteria]". A label never reaches the mapper
    (:attr:`~src.api.models.tte.EligibilityCriterion.mappable` is False for one), so it
    has no seed to substitute and firing here would report correct extraction as a
    defect. Measured on ``output/site_gap/2026-09-10/store_grounded/studies.json``,
    six delivered trials: 30 of the 117 rows with an empty ``sourceText`` are group
    labels, and three of the five rows that opened this investigation are among them.

    Whitespace counts as empty, because :func:`criterion_mapper_seed` collapses
    whitespace -- a ``sourceText`` of ``"   "`` yields no seed exactly as an empty one
    does, and a predicate that disagreed would write a record contradicting the seed.

    :param criterion: a store eligibility-criterion dict.
    :returns: ``True`` when this criterion carries no entity text of its own.
    """
    if criterion.get("isGroupLabel"):
        return False
    return not (criterion.get("sourceText") or "").strip()


def missing_entity_record(
    criterion: Mapping[str, Any], *, role: str, mapped: bool
) -> dict[str, Any]:
    """One row of :data:`MISSING_ENTITY_CRITERIA_KEY`.

    Written for every criterion that reached the mapper on a substituted seed, whether
    or not the substitution cost anything. The survivors are the reason the record
    exists at all: on the 2026-09-10 grounded store 62 of the 70 substituted seeds
    MAPPED, each of them on a human-facing label ("CV risk factor A", "Positive
    biomarker", "Life expectancy"), and the only trace anywhere was a ``queryUsed``
    buried in mapping metadata. The 8 that did not map are already visible in
    ``_unmappedCriteria``; these are not.

    ``seed`` is recorded rather than re-derived by a consumer, so what the mapper was
    actually asked is on file even after the seed rules change.

    :param criterion: a store eligibility-criterion dict.
    :param role: ``"inclusion"`` or ``"exclusion"``, matching the sibling records.
    :param mapped: whether the criterion became a rule.
    """
    return {
        "criterionId": str(criterion.get("id", "")),
        "role": role,
        "label": (criterion.get("description") or "").strip(),
        "domain": (criterion.get("domain") or "").strip() or None,
        "seed": criterion_mapper_seed(criterion),
        "outcome": "mapped" if mapped else "unmapped",
    }
