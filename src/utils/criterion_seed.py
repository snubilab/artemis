"""The one place a criterion's mapper seed is chosen.

The seed is the annotation's verified ``base_span`` (a stated exception's base set), else
the criterion's own ``entity_text`` (stored as ``sourceText``), else -- when extraction
left that mandatory field empty, or the row was never extracted -- its ``description``,
exactly as written. A seed taken from the description is recorded: on the row
(``seededOnDescription`` / ``mapperSeed``, written by ``TTEService._build_seeded_target_circe``)
and in the artifact under :data:`MISSING_ENTITY_CRITERIA_KEY`, which the delivery gate
reports as a WARN.

What RFC-016 step 2 removed (inventory A10) is the cutting: ``strip_window_expressed_temporal``
took "within 3 years" / "prior to randomisation" out of the description with a word table
so the intent router would accept it -- reading natural language to change what the mapper
is asked. Nothing is cut now, here or anywhere else; the router's own word list that made
the cutting necessary (``nlu_router.detect_temporal_negation``) was deleted in ``266971e``
(RFC-016 §5 A15).

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
    is the seed), else the criterion's own ``entity_text`` (``sourceText``), else its
    ``description`` as written (see :func:`seeded_on_description`).

    :param criterion: a store eligibility-criterion dict.
    :returns: the seed text, whitespace-collapsed; ``""`` when the criterion names
        nothing at all (the caller refuses that, and should).
    """
    from src.services.criterion_annotation import stated_base

    return stated_base(criterion) or criterion_own_seed(criterion)


def criterion_own_seed(criterion: Mapping[str, Any]) -> str:
    """The seed ``criterion`` would get with no stated exception: its ``entity_text``
    (``sourceText``), else its ``description``, whitespace-collapsed.

    What a base span seeded in its place is checked against (``TTEService``: the base span's
    set is kept only when its closure shares a concept with this seed's).

    :param criterion: a store eligibility-criterion dict.
    """
    return " ".join(
        ((criterion.get("sourceText") or criterion.get("description") or "").strip()).split()
    )


def seeded_on_description(criterion: Mapping[str, Any]) -> bool:
    """Whether :func:`criterion_mapper_seed` takes this criterion's ``description``.

    True when the criterion carries no entity text of its own
    (:func:`criterion_entity_text_missing`), no verified ``base_span`` stands in for it,
    and a description exists to fall back to.

    :param criterion: a store eligibility-criterion dict.
    """
    from src.services.criterion_annotation import stated_base

    return (
        criterion_entity_text_missing(criterion)
        and not stated_base(criterion)
        and bool((criterion.get("description") or "").strip())
    )


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
    ``sub_criteria`` (``8bbd50d``). When it is empty, :func:`criterion_mapper_seed`
    falls back to ``description`` -- a phrase written for a human ("Drug naive",
    "Stable Background Medication (8 weeks prior to screening)") -- as written. This
    function is the one place that fact is decided, so the record, the re-coded refusal,
    and the seed itself cannot disagree about which rows it covers.

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

    Whitespace counts as empty, because :func:`criterion_mapper_seed` strips before it
    chooses -- a ``sourceText`` of ``"   "`` seeds the mapper on the description exactly
    as an empty one does, and a predicate that disagreed would write a record
    contradicting the seed it describes.

    :param criterion: a store eligibility-criterion dict.
    :returns: ``True`` when the mapper will be seeded on something other than this
        criterion's own entity text.
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
        "seededOnDescription": seeded_on_description(criterion),
        "outcome": "mapped" if mapped else "unmapped",
    }
