"""Resolve the entry-anchor mode a delivery export/verify script runs under.

Motivation: on 2026-09-08 the sanctioned export was run without
``TTE_DRUG_ANCHORED_ENTRY`` in the environment. ``TTEService._drug_anchored_entry``
reads that variable directly, so every TREATMENT arm had its ``PrimaryCriteria``
swapped from the arm's own drug to a disease anchor, and the batch was rejected by
its own lint with seven violations -- six ``entry_mismatch`` (``ConditionOccurrence``
where the store carries ``DrugEra``) and, for PLATO, two ``missing_arm`` because the
swap could not find an anchor at all. Nothing about the command line said which mode
it was going to run in; the delivery's meaning depended on the caller remembering an
environment variable.

A treatment arm entering on a disease rather than on its own drug collects patients
who never took the drug. For a hospital/site delivery that is not a mode -- it is a
different, wrong, cohort. So the mode is not left to the caller:
:func:`resolve_drug_anchored_entry` SETS it, reports what it resolved, and refuses
only when the environment explicitly contradicts it.

This mirrors :mod:`src.utils.store_resolution` deliberately -- same assert-or-set
shape, same "no override flag" stance. There the caller passes ``--store`` and an
ambient ``TTE_STORE_PATH`` may agree or abort; here the script itself owns the
value and an ambient variable may agree or abort. In both cases every internal
reader that consults the environment ends up agreeing with the script, and a
disagreement stops the run instead of quietly changing what is delivered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: The environment variable ``TTEService._drug_anchored_entry`` reads.
DRUG_ANCHORED_ENTRY_ENV = "TTE_DRUG_ANCHORED_ENTRY"

#: The values ``TTEService._drug_anchored_entry`` accepts as true. Kept in step with
#: ``tte_service.py`` rather than re-deriving: a value this module considers enabling
#: that the service does not would pin a mode the service never runs in.
TRUTHY_VALUES = ("1", "true", "yes")

#: What the scripts pin the variable to when the caller left it unset.
DELIVERY_VALUE = "1"


class DeliveryModeConflictError(RuntimeError):
    """Raised when the environment explicitly disables drug-anchored entry."""

    def __init__(self, env_value: str) -> None:
        self.env_value = env_value
        message = (
            f"{DRUG_ANCHORED_ENTRY_ENV}={env_value!r} disables drug-anchored entry, which a "
            "delivery export must not do; refusing to guess which one was intended.\n"
            "  A treatment arm whose PrimaryCriteria is a disease anchor rather than its own\n"
            "  drug collects patients who never took the drug. That is what the 2026-09-08\n"
            "  export produced (6 entry_mismatch + 2 missing_arm violations).\n"
            f"  Set {DRUG_ANCHORED_ENTRY_ENV}={DELIVERY_VALUE} or unset it (these scripts set it\n"
            "  themselves). There is no override flag for this conflict."
        )
        super().__init__(message)


@dataclass(frozen=True)
class DeliveryMode:
    """The resolved entry-anchor mode, and where the value came from."""

    drug_anchored: bool
    env_value: str
    source: str

    def summary(self) -> str:
        """One line naming the mode, the variable, its value, and its origin."""
        anchor = "drug-anchored (treatment arms enter on their own drug)"
        return (
            f"entry anchor mode: {anchor} "
            f"[{DRUG_ANCHORED_ENTRY_ENV}={self.env_value}, {self.source}]"
        )


def resolve_drug_anchored_entry() -> DeliveryMode:
    """Pin drug-anchored entry for this process and report what was resolved.

    If ``TTE_DRUG_ANCHORED_ENTRY`` is unset or empty, sets it to ``"1"`` so every
    internal reader (``TTEService._drug_anchored_entry``) agrees with the script. If
    it is already set to a value the service reads as true, keeps it. If it is set to
    anything else, raises :class:`DeliveryModeConflictError` rather than overriding a
    value the caller stated on purpose.

    :returns: the resolved :class:`DeliveryMode`, whose ``summary()`` the caller is
        expected to print -- a mode that is set silently is the hazard this replaces.
    :raises DeliveryModeConflictError: when the environment explicitly disables it.
    """
    env_value = os.environ.get(DRUG_ANCHORED_ENTRY_ENV, "").strip()

    if not env_value:
        os.environ[DRUG_ANCHORED_ENTRY_ENV] = DELIVERY_VALUE
        return DeliveryMode(
            drug_anchored=True,
            env_value=DELIVERY_VALUE,
            source="set by this script; the environment did not carry it",
        )

    if env_value.lower() not in TRUTHY_VALUES:
        raise DeliveryModeConflictError(env_value)

    return DeliveryMode(
        drug_anchored=True,
        env_value=env_value,
        source="from the environment, agrees with this script",
    )
