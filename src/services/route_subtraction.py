"""Turn a criterion's route qualifier into concept-set subtractions.

The two halves meet here:

- :mod:`route_qualifier` reads what the criterion asked for out of its prose.
- :mod:`dose_form_route` reads what each product is out of OMOP.

This decides which ingredient-by-dose-form concepts a concept set should carry
as ``isExcluded``. That is the axis gold uses: its `[CKim] systemic
glucocorticoid` set holds 136 excluded items, all `Clinical Drug Form` with
``includeDescendants: true``, so a few dozen subtractions cover thousands of
leaves. Measured on CAROLINA's corticosteroid criterion this module produces
139 against gold's 136.

The other obvious axis does not work. OMOP's `Dose Form Group` concepts are
ancestors, so subtracting six of them would express the whole non-systemic set
in six items -- but measured, that removes 1,958 of CAROLINA's 14,331 concepts
where 3,518 are local. 1,627 escape, including 621 `Topical Ointment`. The
groups are not a complete cover of their own routes.

Undecidable forms are never subtracted. Leaving one in preserves the current
over-inclusion; excluding it on a guess creates a new wrong exclusion, which is
the failure this module exists to prevent.

See omx_wiki/route-of-administration-overreach.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.services.dose_form_route import _SYSTEMIC_BY_ROUTE, classify_dose_form
from src.services.route_qualifier import RouteQualifier

_SYSTEMIC_ROUTES = frozenset(r for r, systemic in _SYSTEMIC_BY_ROUTE.items() if systemic)


@dataclass(frozen=True)
class DrugForm:
    """One ingredient-by-dose-form concept, e.g. `prednisolone Topical Cream`.

    :param concept_id: the OMOP concept id, normally class `Clinical Drug Form`.
    :param concept_name: the concept's name, for logging and for the excluded item.
    :param dose_form: the linked Dose Form's name, via `RxNorm has dose form`.
    """

    concept_id: int
    concept_name: str
    dose_form: str


@dataclass(frozen=True)
class RouteSubtraction:
    """What to subtract from a concept set, and what could not be judged.

    :param keep_routes: the routes the criterion asked for, None when it asked
        for nothing and no subtraction applies.
    :param excluded: forms to mark isExcluded.
    :param undecidable: forms whose route could not be read; left included.
    """

    keep_routes: frozenset[str] | None = None
    excluded: list[DrugForm] = field(default_factory=list)
    undecidable: list[DrugForm] = field(default_factory=list)


def routes_to_keep(qualifier: RouteQualifier) -> set[str] | None:
    """Which routes a criterion's qualifier asks to keep.

    A named route wins over the systemic intent, because naming one is the more
    specific statement: "systemic oral corticosteroids" asks for oral. A bare
    "systemic" keeps every systemic route. Nothing stated means no subtraction,
    which is distinct from an empty set.

    :param qualifier: output of :func:`route_qualifier.detect_route_qualifiers`.
    :returns: routes to keep, or None when the criterion states no route.
    """
    if qualifier.qualifiers:
        return set(qualifier.qualifiers)
    if qualifier.systemic_intent is True:
        return set(_SYSTEMIC_ROUTES)
    if qualifier.systemic_intent is False:
        return set(_SYSTEMIC_BY_ROUTE) - set(_SYSTEMIC_ROUTES)
    return None


def compute_route_subtraction(
    forms: list[DrugForm],
    keep_routes: set[str] | frozenset[str] | None,
) -> RouteSubtraction:
    """Split a concept set's drug forms into keep, subtract and cannot-say.

    A form is subtracted when its route is known and none of its routes was
    asked for. A form whose dose form the dictionary cannot place -- because the
    name states no route, because systemic-ness depends on the drug rather than
    the form, or because the vocabulary gained a form the dictionary has not
    seen -- is reported and left included.

    :param forms: ingredient-by-dose-form concepts under the concept set.
    :param keep_routes: from :func:`routes_to_keep`; None subtracts nothing.
    :returns: the subtraction to apply.
    """
    if not keep_routes:
        return RouteSubtraction(keep_routes=None)

    keep = frozenset(keep_routes)
    excluded: list[DrugForm] = []
    undecidable: list[DrugForm] = []

    for form in forms:
        classified = classify_dose_form(form.dose_form)
        if classified.systemic is None or not classified.routes:
            undecidable.append(form)
            continue
        if not (set(classified.routes) & keep):
            excluded.append(form)

    return RouteSubtraction(keep_routes=keep, excluded=excluded, undecidable=undecidable)
