"""Route qualifiers stated in eligibility-criteria prose.

Two halves make route filtering work, and this is the second:

- ``dose_form_route`` answers *what route is this product*, read off OMOP.
- this module answers *what route did the criterion ask for*, read off the text.

The lexicon covers every route ``dose_form_route`` can classify, not only the
ones our sample uses. Measured over the six studies' 473 criteria, only
``systemic`` (7) and ``oral`` (2) actually occur; ``inhaled``, ``topical`` and
``ophthalmic`` never do. Fitting the detector to that would encode a sample of
six cardiovascular and diabetes trials as if it were the domain. A dermatology
or respiratory protocol inverts those frequencies, and a criterion the detector
cannot name is a criterion the pipeline silently gets wrong.

``systemic`` is not a route. It is an intent that *selects* routes, so it is
reported separately -- a criterion saying "systemic corticosteroids" is not
saying "oral corticosteroids".

See omx_wiki/route-of-administration-overreach.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Prose forms for each route. Keys must cover dose_form_route._SYSTEMIC_BY_ROUTE;
# test_every_route_the_dose_form_dictionary_knows_has_a_prose_form enforces it.
#
# Abbreviations are matched only in lower case or when followed by a dosing word,
# because "section IV" and "PO Box" are not routes.
_ROUTE_LEXICON: dict[str, str] = {
    "oral": r"\boral(?:ly)?\b|\bper\s+os\b|\bby\s+mouth\b|\bswallow\w*\b|"
            r"\bp\.?o\.?\b(?=\s+(?:once|twice|daily|bid|tid|qd|q\d))",
    "injection": r"\binject\w*\b|\bintravenous(?:ly)?\b|\bintramuscular(?:ly)?\b|"
                 r"\bsubcutaneous(?:ly)?\b|\bparenteral(?:ly)?\b|\binfusion\b|"
                 r"\bintrathecal\b|\bintra-?articular\b|\bintralesional\b|\bdepot\b|"
                 r"\bi\.?v\.?\b(?=\s+(?:for|infusion|bolus|administ|therapy|once|twice|daily))|"
                 r"\bi\.?m\.?\b(?=\s+(?:depot|inject|administ|once|twice|daily))|"
                 r"\bs\.?c\.?\b(?=\s+(?:inject|administ|once|twice|daily))",
    "inhalation": r"\binhal\w*\b|\bnebuli[sz]\w*\b|\baerosol\w*\b|\bpuffs?\b|"
                  r"\bintratracheal\b|\bpulmonary\s+(?:administ|deliver)\w*\b|"
                  r"\bmetered[- ]dose\b|\bMDI\b|\bDPI\b",
    "nasal": r"\bnasal(?:ly)?\b|\bintranasal(?:ly)?\b|\bnose\s+drops?\b",
    "ophthalmic": r"\bophthalmic\b|\beye\s+drops?\b|\beye\s+ointment\b|\bocular\b|"
                  r"\bintravitreal\b|\bconjunctival\b",
    "otic": r"\botic\b|\bear\s+drops?\b|\baural\b|\bauricular\b|\bintratympanic\b",
    "oromucosal": r"\bbuccal(?:ly)?\b|\bmouthwash\b|\bgargle\b|\blozenges?\b|\btroche\b|"
                  r"\boropharyngeal\b|\bgingival\b|\bperiodontal\b|\btoothpaste\b|"
                  r"\boral\s+rinse\b|\bdental\s+(?:gel|paste|application)\b",
    "sublingual": r"\bsublingual(?:ly)?\b|\bunder\s+the\s+tongue\b",
    "topical": r"\btopical(?:ly)?\b|\bcutaneous(?:ly)?\b|\bdermal(?:ly)?\b|"
               r"\bapplied\s+to\s+the\s+skin\b|\bskin\s+application\b|\bshampoo\b|"
               r"\b(?:cream|ointment|lotion)s?\b",
    "transdermal": r"\btransdermal(?:ly)?\b|\bpatch(?:es)?\b|\biontophoresis\b",
    "vaginal": r"\bvaginal(?:ly)?\b|\bintravaginal(?:ly)?\b|\bpessar(?:y|ies)\b|"
               r"\bintrauterine\b",
    "rectal": r"\brectal(?:ly)?\b|\bsuppositor(?:y|ies)\b|\benema\b|\bper\s+rectum\b",
    "urethral": r"\burethral(?:ly)?\b|\bintravesical(?:ly)?\b|\bbladder\s+instillation\b|"
                r"\bpyelocalyceal\b",
    "irrigation": r"\birrigation\b|\blavage\b|\bdouche\b",
    "dialysis": r"\bdialysis\b|\bh(?:a)?emodialysis\b|\bperitoneal\s+dialysis\b|"
                r"\bh(?:a)?emofiltration\b",
}

# "systemic" means route only next to a drug. Everywhere else in a protocol it
# means "affecting the whole body", and these are established terms rather than a
# long tail: measured over the six studies, 3 of 7 "systemic" hits were
# `systemic embolus` and `systemic infection` in Condition criteria. Reading
# those as a route qualifier would attach a dose-form filter to a stroke
# criterion.
_SYSTEMIC_NOT_A_ROUTE = (
    r"embol\w*|infection|sepsis|inflammat\w*|lupus|scleros\w*|sclerosis|vasculit\w*|"
    r"amyloidos\w*|mastocytos\w*|circulation|vascular\s+resistance|arterial|venous|"
    r"hypertension|hypotension|illness|disease|disorder|toxicity|reaction|"
    r"review|examination|symptoms?"
)

# Intent qualifiers. These select routes rather than naming one.
_SYSTEMIC_INTENT = rf"\bsystemic(?:ally)?\b(?!\s+(?:{_SYSTEMIC_NOT_A_ROUTE}))"
_LOCAL_INTENT = r"\blocal(?:ly)?\s+(?:acting|applied|administered)\b|\blocal\s+(?:use|therapy)\b|" \
                r"\btopical\s+use\s+only\b"

_COMPILED_ROUTES = [(route, re.compile(pattern, re.IGNORECASE))
                    for route, pattern in _ROUTE_LEXICON.items()]
_COMPILED_SYSTEMIC = re.compile(_SYSTEMIC_INTENT, re.IGNORECASE)
_COMPILED_LOCAL = re.compile(_LOCAL_INTENT, re.IGNORECASE)


@dataclass(frozen=True)
class RouteQualifier:
    """What a criterion's text says about administration route.

    :param text: the criterion text that was scanned.
    :param qualifiers: routes the text names, in no particular order.
    :param systemic_intent: True when the text says "systemic", False when it
        says locally acting, None when it says neither.
    """

    text: str
    qualifiers: list[str] = field(default_factory=list)
    systemic_intent: bool | None = None


def covered_routes() -> set[str]:
    """Routes this module can recognise in prose.

    :returns: the lexicon's route keys, for comparison against the dose-form
        dictionary's routes.
    """
    return set(_ROUTE_LEXICON)


def detect_route_qualifiers(text: str) -> RouteQualifier:
    """Find every route qualifier stated in a criterion.

    All routes are reported, not the first match, because a criterion may name
    several ("oral or intravenous anticoagulation").

    :param text: criterion description and/or source text.
    :returns: the routes named and the systemic/local intent.
    """
    if not text:
        return RouteQualifier(text=text or "", qualifiers=[], systemic_intent=None)

    qualifiers = [route for route, pattern in _COMPILED_ROUTES if pattern.search(text)]

    systemic_intent: bool | None = None
    if _COMPILED_SYSTEMIC.search(text):
        systemic_intent = True
    elif _COMPILED_LOCAL.search(text):
        systemic_intent = False

    return RouteQualifier(text=text, qualifiers=qualifiers, systemic_intent=systemic_intent)
