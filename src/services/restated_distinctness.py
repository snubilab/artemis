"""The record contract of the retired IR-level restated-distinctness collapse (SPEC-INFRA-004).

Until 2026-10-14 the seeded build dropped, before mapping, every criterion whose
``(domain, sourceText, window, valueConstraint, logicType)`` equalled an earlier row's in the
same place in the rule tree (``analyze_restated_groups``). ``sourceText`` is entity text, so two
rows were declared one fact because their words were equal -- a text rule. Measured by offline
build replays of the 2026-10-12 P3 dry arms and the prompt_f2 candidate, it dropped 25 / 18 / 25
rows. Of the arm drops, 19 of 43 quote a different span or line than their survivor, and 7 were
asked of the mapper differently from their survivor (another base span, a stated exception the
survivor lacks), so the survivor's concept set stood in for a set the row would not have had:
LEADER inclusion #40 ("age min. 60 years") under #34 ("age min. 50 years"), CARMELINA exclusion
#31/#32 whose annotation excepts the investigational products #29/#30 do not.

Nothing identifies a restatement before mapping without reading text: the store carries no
line index or lineage field. What a restatement shares after mapping is what its rule selects,
and that is decided structurally where it already was: :mod:`src.services.restated_rules`
removes an inclusion rule whose conjuncts -- with each ``CodesetId`` read as the concept ids and
flags of its set, never names -- equal or are implied by another rule's. Every other row is
built and recorded on its own fields; members that emit the identical criterion inside one
ALL/ANY group are kept, which changes nothing a cohort selects.

What remains here is what files built before the change still need: the skip reason those
files carry and the key the delivery gate re-judges their collapse records with
(``scripts/verify_circe_delivery.py``, condition 4 of the restatement permit).
"""
from __future__ import annotations

import json
from typing import Any

#: The ``_skippedCriteria`` reason the retired collapse recorded on each dropped criterion.
COLLAPSE_REASON = "restated-distinctness-duplicate"


def _canonical(value: Any) -> str:
    """Return a form of `value` that compares equal exactly when `value` does."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)


def distinctness_key(criterion: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """The key the retired collapse compared rows under, for re-judging its old records.

    Args:
        criterion: A top-level IR criterion. Absent keys read as empty/null.

    Returns:
        ``(domain, sourceText, canonical window, canonical valueConstraint, logicType)``.
    """
    return (
        (criterion.get("domain") or "").strip(),
        criterion.get("sourceText") or "",
        _canonical(criterion.get("window")),
        _canonical(criterion.get("valueConstraint")),
        criterion.get("logicType") or "",
    )
