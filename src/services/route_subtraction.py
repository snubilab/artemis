"""Turn the route a criterion's protocol line states into concept-set subtractions.

The two halves meet here, and neither reads text:

- the route the criterion asks for is the annotation step's ``route`` field, quoted from the
  protocol line (``criterion_annotation.stated_route``);
- the route each drug product has is OMOP's: a Clinical Drug Form links to its Dose Form via
  ``RxNorm has dose form``, and the Dose Form to a SNOMED / OMOP Extension route concept via
  ``Has route of admin``. ``concept_ancestor`` above that route is part of the answer -- the
  vocabulary files Transdermal under Topical, Nasal under Respiratory tract, and Buccal and
  Sublingual under Oromucosal -- so a form is kept when its route, or a route above it, is
  one the criterion asked for.

This decides which ingredient-by-dose-form concepts a concept set should carry as
``isExcluded``. That is the axis gold uses: its `[CKim] systemic glucocorticoid` set holds
136 excluded items, all `Clinical Drug Form` with ``includeDescendants: true``, so a few
dozen subtractions cover thousands of leaves.

Measured on synthea23m (2026-10-12): 196 of the 218 valid RxNorm / RxNorm Extension dose
forms carry exactly one ``Has route of admin`` target, covering 99.80% of product links. The
22 that carry none (``Pack``, ``Toothpaste``, ``Solution``, ``Spray``...) are undecidable and
never subtracted: leaving one in preserves the existing over-inclusion; excluding it on a
guess creates a new wrong exclusion, which is the failure this module exists to prevent.

OMOP's ``Dose Form Group`` concepts are not the axis: subtracting them removed 1,958 of
CAROLINA's 14,331 corticosteroid concepts where 3,518 are local -- the groups are not a
complete cover of their own routes.

See omx_wiki/route-of-administration-overreach.md.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum


class AdministrationRoute(str, Enum):
    """The routes of administration OMOP attaches to RxNorm dose forms.

    One member per ``Has route of admin`` target of a valid RxNorm / RxNorm Extension Dose
    Form: 13 concepts, domain ``Route`` (SNOMED, plus OMOP Extension for Injectable and
    Implant). Measured on synthea23m (2026-10-12): 196 of 218 dose forms carry exactly one,
    covering 1,792,946 of 1,796,618 product links (99.80%). The values are what the
    annotation step offers the model (``criterion_annotation``, field ``route``);
    ``tests/fixtures/rxnorm_dose_form_routes.json`` holds the capture this list is checked
    against.
    """

    ORAL = "oral"
    INJECTABLE = "injectable"
    TOPICAL = "topical"
    TRANSDERMAL = "transdermal"
    RESPIRATORY_TRACT = "respiratory_tract"
    NASAL = "nasal"
    OPHTHALMIC = "ophthalmic"
    OTIC = "otic"
    RECTAL = "rectal"
    VAGINAL = "vaginal"
    BUCCAL = "buccal"
    SUBLINGUAL = "sublingual"
    IMPLANT = "implant"

    @property
    def concept_id(self) -> int:
        """The OMOP route concept this value stands for."""
        return _ROUTE_CONCEPT_IDS[self]


_ROUTE_CONCEPT_IDS: dict[AdministrationRoute, int] = {
    AdministrationRoute.ORAL: 4132161,
    AdministrationRoute.INJECTABLE: 706184,
    AdministrationRoute.TOPICAL: 4263689,
    AdministrationRoute.TRANSDERMAL: 4262099,
    AdministrationRoute.RESPIRATORY_TRACT: 40486069,
    AdministrationRoute.NASAL: 4262914,
    AdministrationRoute.OPHTHALMIC: 4184451,
    AdministrationRoute.OTIC: 4023156,
    AdministrationRoute.RECTAL: 4290759,
    AdministrationRoute.VAGINAL: 4057765,
    AdministrationRoute.BUCCAL: 4181897,
    AdministrationRoute.SUBLINGUAL: 4292110,
    AdministrationRoute.IMPLANT: 706185,
}


@dataclass(frozen=True)
class DrugForm:
    """One ingredient-by-dose-form concept, e.g. `prednisolone Topical Cream`.

    :param concept_id: the OMOP concept id, normally class `Clinical Drug Form`.
    :param concept_name: the concept's name, for logging and for the excluded item.
    :param dose_form: the linked Dose Form's name, for logging only -- never classified.
    :param route_ids: the ``Has route of admin`` route of that Dose Form and every
        ``concept_ancestor`` of it; empty when the vocabulary gives the form no route.
    """

    concept_id: int
    concept_name: str
    dose_form: str
    route_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class RouteSubtraction:
    """What to subtract from a concept set, and what could not be judged.

    :param keep_routes: the routes the criterion asked for, None when it asked
        for nothing and no subtraction applies.
    :param excluded: forms to mark isExcluded.
    :param undecidable: forms the vocabulary gives no route; left included.
    """

    keep_routes: frozenset[AdministrationRoute] | None = None
    excluded: list[DrugForm] = field(default_factory=list)
    undecidable: list[DrugForm] = field(default_factory=list)


def compute_route_subtraction(
    forms: list[DrugForm],
    keep_routes: Iterable[AdministrationRoute] | None,
) -> RouteSubtraction:
    """Split a concept set's drug forms into keep, subtract and cannot-say.

    A form is kept when its route, or a route the vocabulary files it under, is one asked
    for; subtracted when it has a route and none of those is; undecidable -- reported and
    left included -- when the vocabulary gives its dose form no route.

    :param forms: ingredient-by-dose-form concepts under the concept set.
    :param keep_routes: the stated routes; None or empty subtracts nothing.
    :returns: the subtraction to apply.
    """
    keep = frozenset(keep_routes or ())
    if not keep:
        return RouteSubtraction(keep_routes=None)
    keep_ids = {route.concept_id for route in keep}
    excluded: list[DrugForm] = []
    undecidable: list[DrugForm] = []
    for form in forms:
        if not form.route_ids:
            undecidable.append(form)
        elif not (form.route_ids & keep_ids):
            excluded.append(form)
    return RouteSubtraction(keep_routes=keep, excluded=excluded, undecidable=undecidable)
