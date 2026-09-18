"""Export-time repair: drop a member that is not the analyte its concept set names.

The defect this repairs is the one ``src.utils.circe_lint.confusable_concept_sets``
refuses a delivery for: a concept set whose NAME states one analyte holds a concept
measuring another. Measured instance, ``output/site_gap/2026-09-18_verify3/DELIVERY/
empa-reg_treatment.circe.json``::

    codeset 3   'Glycosylated haemoglobin (HbA1c)', 6 seeds, ZERO isExcluded,
                one of them 3005446 'Hemoglobin A1/Hemoglobin.total in Blood'
    rule #4     'HbA1c for patients on background therapy (>=7.0% and <=10%) + ...'
                Measurement codeset 3, bt 7.0..10.0, Unit [8554] percent

The hospital's Atlas inclusion report measured rule #4 at 0 people, and the unit filter
is why: ``presence_unit_repair`` classifies codeset 3 as ``unlisted`` because of that one
member and therefore declines to drop the ``Unit``. So one confusable member held a
hospital cohort at zero.

WHY THIS REPAIRS AT EXPORT TIME, reversing what ``CONFUSABLE_ANALYTES`` argued until
2026-09-18. The old position was that removing a member changes which patients the
cohort SELECTS -- a mapping correction, not an export-time repair. The rewritten comment
block on that table records the reversal and the reasoning; the short form is that
LEAVING the member in also decides the clinical question, and the measurement above says
it decides it worse, while re-extracting to fix one concept set re-rolls a third of the
criteria (see ``feedback: prompt edits re-roll a third of criteria``).

WHAT IT WILL NOT DO. Five conditions must hold together, and the FOURTH is the safety
one -- the whole basis for the reversal:

1. the concept set's NAME states the analyte and not the other thing;
2. the held member is in that analyte's ``confusables`` mapping. 3035009, LDL
   ``[Units/volume]`` by Electrophoresis, is LDL and is deliberately not in the table,
   so nothing here ever removes it;
3. at least one included member remains after the removal. An empty concept set is not a
   narrower cohort -- Circe compiles it to a criterion nothing can satisfy, or to one
   everything does, depending on the domain, and neither is the repair's intent;
4. EVERY criterion anywhere in the expression that reads the codeset is a presence
   criterion -- ``Occurrence {Type: 2, Count: >= 1}`` reached only through ALL/ANY/
   AT_LEAST groups. Removing a member SHRINKS the set, so under presence the cohort can
   only select FEWER patients, the same "can only miss patients" direction the unit
   allowlist requires. Under an ABSENCE criterion a smaller set makes the absence EASIER
   to satisfy and the direction flips to "can wrongly include patients";
5. the concept set carries no ``isExcluded`` item. An exclusion SUBTRACTS, so removing a
   member from the included side changes what the subtraction lands on -- the same
   grounds ``entry_exclusion_repair`` declines an entry set carrying one, where a flat
   mirror cannot express the subtraction it would need to.

Conditions 1 and 2 are precisely the lint's own predicate, and it lives in
:func:`~src.utils.circe_lint.iter_confusable_members` so that the gate and the repair
cannot drift apart -- the same arrangement ``entry_exclusion_repair`` and
``scripts/verify_entry_exclusion_conflict.py`` already share their traversal through.

No vocabulary and no database: every condition is readable from the expression itself.
Nothing else in the payload is touched, and a set the repair declines still fires the
lint, so the delivery gate keeps refusing exactly the cases removal was not safe for.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.utils.circe_lint import iter_confusable_members
from src.utils.presence_unit_allowlist import iter_codeset_readers


@dataclass(frozen=True)
class ConfusableMemberRepair:
    codeset_id: int
    codeset_name: str
    analyte: str
    removed_concept_ids: list[int]
    reasons: list[str]


def repair_confusable_members(base: dict[str, Any]) -> list[ConfusableMemberRepair]:
    """Remove confusable members where conditions 1-5 hold. Mutates ``base`` in place.

    :param base: a CIRCE cohort expression.
    :returns: one record per repaired concept set; empty when nothing qualified.
    """
    readers_by_codeset: dict[int, list] = {}
    for reader in iter_codeset_readers(base):
        readers_by_codeset.setdefault(reader.codeset_id, []).append(reader)

    applied: list[ConfusableMemberRepair] = []

    for concept_set, entry, held in list(iter_confusable_members(base)):
        codeset_id = concept_set.get("id")
        name = str(concept_set.get("name") or "")
        items = (concept_set.get("expression") or {}).get("items") or []

        # condition 5 -- an exclusion inverts the direction, so decline before anything
        # else touches the included side.
        if any(item.get("isExcluded") for item in items):
            logging.warning(
                "[TTE] confusable-member repair declines codeset %s %r (%s): the set "
                "carries an isExcluded item, and an exclusion SUBTRACTS -- removing %s "
                "from the included side changes what that subtraction lands on, so the "
                "'can only miss patients' direction is no longer provable",
                codeset_id, name, entry.analyte, list(held),
            )
            continue

        # condition 3 -- an empty concept set is not a narrower cohort.
        remaining = [
            item for item in items
            if (item.get("concept") or {}).get("CONCEPT_ID") not in set(held)
        ]
        if not remaining:
            logging.warning(
                "[TTE] confusable-member repair declines codeset %s %r (%s): removing "
                "%s would leave the set empty -- no included member would remain, and an "
                "empty concept set is not a narrower cohort",
                codeset_id, name, entry.analyte, list(held),
            )
            continue

        # condition 4 -- the safety condition.
        readers = readers_by_codeset.get(int(codeset_id), []) if codeset_id is not None else []
        if not readers:
            logging.warning(
                "[TTE] confusable-member repair declines codeset %s %r (%s): no "
                "criterion in the expression reads it, so removing %s would change "
                "nothing that can be verified",
                codeset_id, name, entry.analyte, list(held),
            )
            continue
        blocking = [reader for reader in readers if not reader.is_presence]
        if blocking:
            logging.warning(
                "[TTE] confusable-member repair declines codeset %s %r (%s): %d of %d "
                "reader(s) are not provably a presence criterion -- %s (%s). Removing "
                "%s from a set an ABSENCE criterion reads makes that absence EASIER to "
                "satisfy, so the direction flips from 'can only miss patients' to 'can "
                "wrongly include patients'",
                codeset_id, name, entry.analyte, len(blocking), len(readers),
                "; ".join(reader.locator for reader in blocking),
                blocking[0].why_not, list(held),
            )
            continue

        concept_set["expression"]["items"] = remaining
        reasons = [
            f"{cid} {entry.confusables[cid][0]!r} -- {entry.confusables[cid][1]}"
            for cid in held
        ]
        applied.append(
            ConfusableMemberRepair(
                codeset_id=int(codeset_id),
                codeset_name=name,
                analyte=entry.analyte,
                removed_concept_ids=list(held),
                reasons=reasons,
            )
        )
        logging.warning(
            "[TTE] confusable-member repair: codeset %s %r names %s -- %s removed, %d "
            "included member(s) remain, read only by presence criteria (%s). %s",
            codeset_id, name, entry.analyte, list(held), len(remaining),
            "; ".join(reader.locator for reader in readers), "; ".join(reasons),
        )
    return applied
