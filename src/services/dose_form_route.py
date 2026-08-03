"""Route of administration for OMOP Dose Form concepts.

An eligibility criterion says "systemic corticosteroids". A concept set built
from the RxNorm Ingredient plus `includeDescendants` says "prednisolone, in any
form", which is 14,331 concepts of which 3,875 are creams, eye drops and
inhalers. Route is not recoverable from the drug's name, but OMOP carries it
structurally: every drug product links to a Dose Form via
`RxNorm has dose form`, and there are only ~780 dose forms in the whole
vocabulary.

This module classifies a dose form's name. Two steps, deliberately separate:

1. ``routes`` — factual. Which administration routes the name states.
2. ``systemic`` — a clinical judgement mapped from the routes, and ``None``
   when the name states no route at all.

``systemic`` is never guessed. A form whose name carries no route (``Powder``,
``Solution``, ``Gel``) returns ``None`` so a caller has to decide what to do
about it. Defaulting those to oral is the same silent-substitution shape as the
bug this module exists to prevent.

See omx_wiki/route-of-administration-overreach.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Ordered only for readability; every pattern is tested against the whole name.
_ROUTE_PATTERNS: list[tuple[str, str]] = [
    ("inhalation", r"inhal|nebuli|respirat|intratracheal|endotracheopulmonary|pulmonary|"
                   r"metered dose|vapou?r|\bgas\b|smoking|impregnated cigarette"),
    ("nasal", r"\bnasal\b|\bnose\b|intranasal"),
    ("ophthalmic", r"ophthalm|\beye\b|ocular|intravitreal|conjunctiv|contact lens"),
    ("otic", r"\botic\b|\bear\b|auricular|intratympanic"),
    ("oromucosal", r"oromucos|oropharyngeal|mouthwash|toothpaste|gingival|periodontal|dental|"
                   r"\bbuccal\b|lozenge|troche|pastille|oral rinse|gargle|chewing gum|\bmucosal\b"),
    ("sublingual", r"sublingual"),
    ("topical", r"topical|cutaneous|\bcream\b|ointment|\blotion\b|shampoo|\bsoap\b|"
                r"medicated (?:pad|tape|swab|cottonball|gauzeball|gu?aze|nail polish)|"
                r"poultice|collodion|dressing|\bbath\b|\bplaster\b|tissue adhesive|"
                r"wound cone|liquid cleanser|shower powder|\bsponge\b"),
    ("transdermal", r"transdermal|iontophoresis"),
    ("vaginal", r"vaginal|pessary|intrauterine|endocervical|\btampon\b|\bring\b"),
    ("rectal", r"rectal|suppositor|enema"),
    ("urethral", r"urethral|pyelocalyceal|intravesical|bladder"),
    ("injection", r"inject|infusion|intravenous|intramuscul|subcutan|prefilled syringe|"
                  r"\bimplant\b|intraperitoneal|intrathecal|intra-?articular|intralesional|"
                  r"intradermal|cartridge|cardioplegia|parenteral"),
    ("dialysis", r"dialysis|h(?:a)?emofiltration|h(?:a)?emodiafiltration|extracorporeal"),
    ("irrigation", r"irrigat|\bdouche\b"),
    ("oral", r"\boral\b|enteral|intestinal|chewable|swallow|\bpill\b|effervescent|"
             r"gastro-?resistant|prolonged-release|modified-release|disintegrat|"
             r"\bcapsule\b|\btablet\b|caplet|cachet|elixir|\bsyrup\b|\bwafer\b|pudding|"
             r"\bbeads\b|\bgranules?\b|\bpillule\b|\bgum\b"),
]

# Whether a route delivers drug to the systemic circulation at a dose that makes
# "is the patient on <drug>" true for an eligibility criterion.
#
# Transdermal is systemic and topical is not, which is the distinction a patch
# turns on. Inhalation is listed non-systemic on the strength of CAROLINA's own
# wording -- "inhaled use of steroids (e.g. for asthma/COPD) is no exclusion
# criterion, as this does not cause systemic steroid action". That is a
# corticosteroid-specific statement; an inhaled anaesthetic is systemic. Callers
# needing drug-class-specific behaviour should override rather than edit this.
_SYSTEMIC_BY_ROUTE: dict[str, bool] = {
    "oral": True,
    "injection": True,
    "rectal": True,
    "sublingual": True,
    "transdermal": True,
    "dialysis": True,
    "inhalation": False,
    "nasal": False,
    "ophthalmic": False,
    "otic": False,
    "oromucosal": False,
    "topical": False,
    "vaginal": False,
    "urethral": False,
    "irrigation": False,
}

_COMPILED = [(route, re.compile(pattern, re.IGNORECASE)) for route, pattern in _ROUTE_PATTERNS]


@dataclass(frozen=True)
class DoseFormRoute:
    """What a dose form's name says about how the drug is administered.

    :param name: the dose form concept name as it appears in OMOP.
    :param routes: every route the name states, in no particular order.
    :param systemic: True/False when at least one route is known, else None.
    """

    name: str
    routes: list[str] = field(default_factory=list)
    systemic: bool | None = None


def classify_dose_form(name: str) -> DoseFormRoute:
    """Read the administration route(s) out of a dose form's name.

    A name may state several routes ("Ear and eye and nose drops"); all are
    kept. The form counts as systemic if any of its routes is systemic, so a
    form usable both orally and rectally is systemic on both counts, and a
    transdermal patch is systemic despite also matching "topical".

    :param name: dose form concept name, e.g. "Delayed Release Oral Tablet".
    :returns: the routes found and the systemic judgement, ``None`` if no route
        is stated.
    """
    if not name:
        return DoseFormRoute(name=name or "", routes=[], systemic=None)

    routes = [route for route, pattern in _COMPILED if pattern.search(name)]
    if not routes:
        return DoseFormRoute(name=name, routes=[], systemic=None)

    known = [_SYSTEMIC_BY_ROUTE[r] for r in routes if r in _SYSTEMIC_BY_ROUTE]
    systemic = any(known) if known else None
    return DoseFormRoute(name=name, routes=routes, systemic=systemic)
