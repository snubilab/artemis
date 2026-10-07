"""A criterion stating that background drug therapy is STABLE is not a drug-presence rule.

CARMELINA inclusion 7 reads "Stable antidiabetic background medication (unchanged daily
dose) for at least 8 weeks prior to randomization". It conditions whatever therapy a
patient is already on and requires none: the same protocol admits drug-naive patients
(inclusion 2-6). CAROLINA states it twice -- inclusion 37 with its member 38, and 41 --
and admits treatment-naive patients in inclusion 5-8. All three were delivered as
`DrugExposure` at-least-1 rules over -56..0, which reads "must be on an antidiabetic
drug": at Ajou the CARMELINA comparator fell 38,664 -> 1,257 at that one rule in the
2026-09-23 send. Neither TROY v1.1 gold carries a background-medication rule; both only
exclude the forbidden drugs.

OMOP CDM has no "unchanged dose" construct -- `drug_exposure` records exposures, not a
dose held constant over a window -- so the criterion has no faithful expression, and the
one approximation available demands what the protocol does not. It is not emitted, and is
recorded in `_skippedCriteria` under :data:`DOSE_STABILITY_REASON`.

:func:`dose_stability_criterion_ids` is the one home of that decision:
`TTEService._build_seeded_target_circe` skips by it, and `scripts/verify_circe_delivery.py`
re-judges every skip recorded under the reason by it, so the reason cannot carry an
arbitrary criterion out of the cohort.

Three conditions, all required, read over ``description`` + ``sourceText``:

1. a stability term -- ``stable``, ``unchanged``, ``stabilised``/``stabilized``,
   ``no (dose) change``;
2. the Drug domain -- for a group label, every member's domain, because the members are
   what would emit. "Stable angina" and "stable coronary artery disease" are Condition
   rows and never fire;
3. a therapy term -- background, therapy, medication, treatment, dose, regimen. Without
   it "Nitrates for stable angina" (Drug) would fire, where "stable" belongs to the
   disease and the drug presence IS the criterion.

A group label that fires carries its members with it: they are the presence rule the
label describes, and emitting them alone would emit exactly what this removes. CAROLINA
38 ("Anti-diabetic medication", no stability term of its own) goes out with 37.

Inclusion only. An exclusion is never a presence requirement, and the forbidden-drug
exclusions both protocols state stay exactly as they are.

Measured on `output/site_gap/2026-09-22_verify5/store/studies.json` (10 studies, both
roles): selects CARMELINA (study 9) inclusion 7 and CAROLINA (study 10) inclusion 37, 38
and 41, and nothing else.

Known limit: the therapy term also matches "stable dose of <one named drug>", where a
protocol may genuinely require that drug (an add-on-to-metformin design) and the
representable half of the criterion would be lost. No inclusion in the protocol corpus
under `data/papers/` is worded that way; EMPA-REG's "stable glucose-lowering therapy" is
the same shape as CARMELINA's and is meant to fire.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

#: Recorded on each skipped criterion via `_record_skip`, and permitted -- after
#: re-judgement -- by the delivery gate's `ALLOWED_SKIP_REASONS`.
DOSE_STABILITY_REASON = "dose-stability-not-representable"

#: Travels with each record, so a reader of the delivered file sees why without this module.
DOSE_STABILITY_EXPLANATION = (
    "States that background drug therapy was held at an unchanged dose. OMOP CDM records "
    "drug exposures, not a dose held constant over time, so the condition is not "
    "expressible; emitted as a drug-presence rule it would require therapy and drop the "
    "drug-naive patients the protocol admits."
)

_DRUG = "Drug"
_STABILITY = re.compile(r"\b(stable|unchanged|stabili[sz]ed|no (?:dose )?change)\b", re.IGNORECASE)
_THERAPY = re.compile(
    r"\b(background|therap(?:y|ies)|medications?|treatments?|dos(?:e|es|age|ing)|regimens?)\b",
    re.IGNORECASE,
)


def _states_dose_stability(criterion: dict[str, Any]) -> bool:
    text = " ".join(str(criterion.get(key) or "") for key in ("description", "sourceText"))
    return bool(_STABILITY.search(text) and _THERAPY.search(text))


def _is_drug(criterion: dict[str, Any]) -> bool:
    return (criterion.get("domain") or "").strip() == _DRUG


def dose_stability_criterion_ids(inclusion_criteria: Iterable[dict[str, Any]]) -> set[str]:
    """The inclusion criteria that state dose stability of background drug therapy.

    :param inclusion_criteria: one study's inclusion rows, as the store carries them.
    :returns: their ids, stringified the way `_record_skip` writes ``criterionId``; a
        firing group label contributes its members' ids as well as its own.
    """
    rows = [criterion for criterion in inclusion_criteria if isinstance(criterion, dict)]
    members: dict[str, list[dict[str, Any]]] = {}
    for criterion in rows:
        if criterion.get("groupId") and not criterion.get("isGroupLabel"):
            members.setdefault(str(criterion["groupId"]), []).append(criterion)

    selected: set[str] = set()
    for criterion in rows:
        if not _states_dose_stability(criterion):
            continue
        if criterion.get("isGroupLabel"):
            group = members.get(str(criterion.get("groupId"))) if criterion.get("groupId") else None
            # No members, or any non-drug member: nothing shows the label describes drug
            # therapy alone, and dropping the group would drop that member too.
            if group and all(_is_drug(member) for member in group):
                selected.add(str(criterion.get("id", "")))
                selected.update(str(member.get("id", "")) for member in group)
        elif _is_drug(criterion):
            selected.add(str(criterion.get("id", "")))
    return selected
