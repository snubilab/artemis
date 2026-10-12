"""Export-time repair: drop a member that is not what its concept set's other members measure.

The defect this repairs is the one ``src.utils.circe_lint.confusable_concept_sets``
refuses a delivery for: a concept set measuring one analyte holds a concept measuring
another. Measured instance, ``output/site_gap/2026-09-18_verify3/DELIVERY/
empa-reg_treatment.circe.json``::

    codeset 3   'Glycosylated haemoglobin (HbA1c)', 6 seeds, ZERO isExcluded,
                one of them 3005446 'Hemoglobin A1/Hemoglobin.total in Blood'
    rule #4     'HbA1c for patients on background therapy (>=7.0% and <=10%) + ...'
                Measurement codeset 3, bt 7.0..10.0, Unit [8554] percent

The hospital's Atlas inclusion report measured rule #4 at 0 people, and the unit filter
is why: ``presence_unit_repair`` classifies codeset 3 as ``unlisted`` because of that one
member and therefore declines to drop the ``Unit``. So one confusable member held a
hospital cohort at zero.

WHY THIS REPAIRS AT EXPORT TIME, reversing what the confusable table argued until
2026-09-18. The old position was that removing a member changes which patients the
cohort SELECTS -- a mapping correction, not an export-time repair. The rewritten comment
block on that table records the reversal and the reasoning; the short form is that
LEAVING the member in also decides the clinical question, and the measurement above says
it decides it worse, while re-extracting to fix one concept set re-rolls a third of the
criteria (see ``feedback: prompt edits re-roll a third of criteria``).

WHAT IT WILL NOT DO. Five conditions must hold together, and the FOURTH is the safety
one -- the whole basis for the reversal:

1. the held member's LOINC ``Has component`` is shared by no other LOINC member of the
   set, while at least one other member has one -- the other members measure something
   else. Read off the vocabulary, never off the set's NAME (RFC-016 §4, A28);
2. the held member is in ``CONFUSABLE_MEMBERS``. 3035009, LDL ``[Units/volume]`` by
   Electrophoresis, is LDL and is deliberately not in the table, so nothing here ever
   removes it;
3. at least one included member remains after the removal. An empty concept set is not a
   narrower cohort -- Circe compiles it to a criterion nothing can satisfy, or to one
   everything does, depending on the domain, and neither is the repair's intent;
4. EVERY criterion anywhere in the expression that reads the codeset is either a presence
   criterion -- ``Occurrence {Type: 2, Count: >= 1}`` reached only through ALL/ANY/
   AT_LEAST groups -- or a CONVERTED value-range absence (below). Removing a member
   SHRINKS the set, so under presence the cohort can only select FEWER patients, the same
   "can only miss patients" direction the unit allowlist requires. Under an arbitrary
   ABSENCE criterion a smaller set makes the absence EASIER to satisfy and the direction
   flips to "can wrongly include patients", so a plain absence still declines;
5. the concept set carries no ``isExcluded`` item. An exclusion SUBTRACTS, so removing a
   member from the included side changes what the subtraction lands on -- the same
   grounds ``entry_exclusion_repair`` declines an entry set carrying one, where a flat
   mirror cannot express the subtraction it would need to.

THE CONVERTED-ABSENCE READER, and why its direction differs from a plain absence's.
``src.utils.circe_lint.convert_value_range_inclusions`` restates "at least 1 ANALYTE result
in [lo, hi]" as "no ANALYTE result below lo, none above hi", unitless, and records it under
``VALUE_RANGE_CONVERSIONS_KEY``. A reader counts as converted only when all of these hold:
it is a mandatory absence reached through ``ALL`` groups of an InclusionRule
(:attr:`~src.utils.presence_unit_allowlist.CodesetReader.is_absence`), on ``Measurement``,
with no ``Unit``, its ``ValueAsNumber`` is one of the bounds a ``converted`` record for the
same codeset lists under ``absences``. Measured instance: the 2026-10-08 dry rebuild,
EMPA-REG codesets 3 and 4, "no HbA1c < 7.0, no HbA1c > 10.0", still holding HbA1 total.

Removing the confusable member from such a set does narrow what the absence forbids, so a
patient whose ONLY out-of-range result is the confusable now passes. That is correct here
because of what the conversion already decided: a patient with no result for the analyte
in the window passes the converted rule. Removing the member makes a patient measured only
by the confusable into exactly such a patient. The repair adds no patient class that the
conversion did not already admit. Keeping the member does something different: it applies
the analyte's bound to another quantity. HbA1 includes A1a and A1b and reads higher than
HbA1c, so "HbA1 > 10" excludes patients whose HbA1c may be in range.

The residual risk is stated rather than claimed away. The confusable can imply the
analyte's side of a bound: HbA1 < 7 implies HbA1c < 7. A patient with only such a result
would be excluded by the protocol's intent and is now admitted, as an unmeasured patient
is. That risk is the conversion's own risk for missing results, which it accepted when it
dropped the presence. Removal does not create it.

When the same removal would NOT be correct, and so still declines:

* a plain absence that no conversion record covers. Its provenance is unknown. The
  protocol may exclude on the confusable itself, or on a class the name only abbreviates,
  and nothing in the expression shows that "no result" was already accepted as a pass;
* an absence carrying a ``Unit``, or a bound the record does not list. The conversion
  emits neither, so the reader is not the converted criterion, whatever its codeset;
* an absence under a non-``ALL`` group, or a correlated criterion. There the direction of
  "fewer forbidden events" depends on the surrounding shape, which this module does not
  model.

Conditions 1 and 2 are precisely the lint's own predicate, and it lives in
:func:`~src.utils.circe_lint.iter_confusable_members` so that the gate and the repair
cannot drift apart -- the same arrangement ``entry_exclusion_repair`` and
``scripts/verify_entry_exclusion_conflict.py`` already share their traversal through.

No database: conditions 2-5 are read off the expression, condition 1 off the LOINC
components the caller passes in. Nothing else in the payload is touched, and a set the repair declines still fires the
lint, so the delivery gate keeps refusing exactly the cases removal was not safe for.
"""
from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from src.utils.circe_lint import (
    CONFUSABLE_MEMBERS,
    VALUE_RANGE_CONVERSIONS_KEY,
    iter_confusable_members,
)
from src.utils.presence_unit_allowlist import CodesetReader, iter_codeset_readers


@dataclass(frozen=True)
class ConfusableMemberRepair:
    codeset_id: int
    codeset_name: str
    removed_concept_ids: list[int]
    reasons: list[str]


def _converted_absence_bounds(base: dict[str, Any]) -> dict[int, list[dict]]:
    """Codeset id -> the absence bounds its ``converted`` value-range records emitted."""
    bounds: dict[int, list[dict]] = {}
    for record in base.get(VALUE_RANGE_CONVERSIONS_KEY) or []:
        if not isinstance(record, dict) or record.get("status") != "converted":
            continue
        try:
            codeset_id = int(record.get("codesetId"))
        except (TypeError, ValueError):
            continue
        bounds.setdefault(codeset_id, []).extend(record.get("absences") or [])
    return bounds


def _why_not_converted(reader: CodesetReader, bounds: dict[int, list[dict]]) -> str | None:
    """None when ``reader`` is a converted value-range absence; else why it is not."""
    if not reader.is_absence:
        return reader.why_not
    payload = reader.payload or {}
    if reader.locator.rsplit("/", 1)[-1] != "Measurement":
        return "an absence on a domain a value-range conversion never emits"
    if reader.codeset_id not in bounds:
        return "an absence no value-range conversion record covers"
    if payload.get("Unit"):
        return "an absence carrying a Unit, which a value-range conversion never emits"
    if payload.get("ValueAsNumber") not in bounds[reader.codeset_id]:
        return (
            f"an absence bounding {payload.get('ValueAsNumber')}, which is not a bound "
            f"the codeset's value-range conversion record emitted"
        )
    return None


def repair_confusable_members(
    base: dict[str, Any], components: Mapping[int, Collection[int]]
) -> list[ConfusableMemberRepair]:
    """Remove confusable members where conditions 1-5 hold. Mutates ``base`` in place.

    :param base: a CIRCE cohort expression.
    :param components: LOINC concept id -> its ``Has component`` concept ids, for at least
        ``circe_lint.confusable_member_ids(base)`` (condition 1 reads them; the set's name
        is not read).
    :returns: one record per repaired concept set; empty when nothing qualified.
    """
    readers_by_codeset: dict[int, list] = {}
    for reader in iter_codeset_readers(base):
        readers_by_codeset.setdefault(reader.codeset_id, []).append(reader)
    converted_bounds = _converted_absence_bounds(base)

    applied: list[ConfusableMemberRepair] = []

    for concept_set, held in list(iter_confusable_members(base, components)):
        codeset_id = concept_set.get("id")
        name = str(concept_set.get("name") or "")
        items = (concept_set.get("expression") or {}).get("items") or []

        # condition 5 -- an exclusion inverts the direction, so decline before anything
        # else touches the included side.
        if any(item.get("isExcluded") for item in items):
            logging.warning(
                "[TTE] confusable-member repair declines codeset %s %r: the set "
                "carries an isExcluded item, and an exclusion SUBTRACTS -- removing %s "
                "from the included side changes what that subtraction lands on, so the "
                "'can only miss patients' direction is no longer provable",
                codeset_id, name, list(held),
            )
            continue

        # condition 3 -- an empty concept set is not a narrower cohort.
        remaining = [
            item for item in items
            if (item.get("concept") or {}).get("CONCEPT_ID") not in set(held)
        ]
        if not remaining:
            logging.warning(
                "[TTE] confusable-member repair declines codeset %s %r: removing "
                "%s would leave the set empty -- no included member would remain, and an "
                "empty concept set is not a narrower cohort",
                codeset_id, name, list(held),
            )
            continue

        # condition 4 -- the safety condition.
        readers = readers_by_codeset.get(int(codeset_id), []) if codeset_id is not None else []
        if not readers:
            logging.warning(
                "[TTE] confusable-member repair declines codeset %s %r: no "
                "criterion in the expression reads it, so removing %s would change "
                "nothing that can be verified",
                codeset_id, name, list(held),
            )
            continue
        blocking = [
            (reader, why)
            for reader in readers
            if not reader.is_presence
            and (why := _why_not_converted(reader, converted_bounds)) is not None
        ]
        if blocking:
            logging.warning(
                "[TTE] confusable-member repair declines codeset %s %r: %d of %d "
                "reader(s) are not provably a presence criterion or a converted "
                "value-range absence -- %s. Removing %s from a set an ABSENCE criterion "
                "reads makes that absence EASIER to satisfy, so the direction flips from "
                "'can only miss patients' to 'can wrongly include patients'",
                codeset_id, name, len(blocking), len(readers),
                "; ".join(f"{reader.locator} ({why})" for reader, why in blocking),
                list(held),
            )
            continue

        concept_set["expression"]["items"] = remaining
        reasons = [f"{cid} -- {CONFUSABLE_MEMBERS[cid]}" for cid in held]
        applied.append(
            ConfusableMemberRepair(
                codeset_id=int(codeset_id),
                codeset_name=name,
                removed_concept_ids=list(held),
                reasons=reasons,
            )
        )
        logging.warning(
            "[TTE] confusable-member repair: codeset %s %r holds a member no other "
            "member's LOINC component matches -- %s removed, %d "
            "included member(s) remain, read only by presence criteria or converted "
            "value-range absences (%s). %s",
            codeset_id, name, list(held), len(remaining),
            "; ".join(
                f"{reader.locator} [{'presence' if reader.is_presence else 'converted absence'}]"
                for reader in readers
            ),
            "; ".join(reasons),
        )
    return applied
