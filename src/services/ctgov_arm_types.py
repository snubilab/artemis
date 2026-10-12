"""Whether a trial's comparator arm delivers a drug, from ClinicalTrials.gov arm-group types.

RFC-016 §4 (A22). The export decides between an active-comparator cohort (built on the
comparator drug) and a placebo-comparator one (no drug to build on). That used to be read
off the arm NAME -- a "placebo" substring, "sugar pill", "sham". The registry states it as
data: ``protocolSection.armsInterventionsModule.armGroups[].type`` is one of the
``ArmGroupType`` values below, a machine enum rather than prose.

Only the local registry cache (``data/nct_cache/<NCT>.json``, written by
``src.agents.agent1.nct_fetcher``) is read. A trial missing from it is undecidable, and
:func:`comparator_is_placebo` says so with None rather than guessing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from enum import Enum
from pathlib import Path

#: The registry cache ``nct_fetcher`` writes. Read at call time, so tests can point it away.
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "nct_cache"


class ArmGroupType(str, Enum):
    """ClinicalTrials.gov API v2 ``ArmGroupType``."""

    EXPERIMENTAL = "EXPERIMENTAL"
    ACTIVE_COMPARATOR = "ACTIVE_COMPARATOR"
    PLACEBO_COMPARATOR = "PLACEBO_COMPARATOR"
    SHAM_COMPARATOR = "SHAM_COMPARATOR"
    NO_INTERVENTION = "NO_INTERVENTION"
    OTHER = "OTHER"


#: Comparator arms that deliver no drug, so no real-world cohort can be built on them.
NO_DRUG_COMPARATORS = frozenset(
    {ArmGroupType.PLACEBO_COMPARATOR, ArmGroupType.SHAM_COMPARATOR, ArmGroupType.NO_INTERVENTION}
)
#: Comparator arms that deliver a drug.
DRUG_COMPARATORS = frozenset({ArmGroupType.ACTIVE_COMPARATOR})


def load_cached_arm_group_types(
    nct_id: str | None, cache_dir: Path | None = None
) -> list[str] | None:
    """The ``armGroups[].type`` values of a trial's cached registry record.

    :param nct_id: the trial's NCT id.
    :param cache_dir: the registry cache; :data:`DEFAULT_CACHE_DIR` when omitted.
    :returns: one entry per arm group, in registry order, or None when the trial has no
        cached record (or no NCT id). Never fetches.
    """
    if not nct_id:
        return None
    path = Path(cache_dir or DEFAULT_CACHE_DIR) / f"{nct_id.strip().upper()}.json"
    if not path.is_file():
        logging.warning("[TTE] no cached ClinicalTrials.gov record for %s at %s", nct_id, path)
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    arms = (record.get("protocolSection") or {}).get("armsInterventionsModule") or {}
    return [group.get("type") for group in arms.get("armGroups") or []]


def comparator_is_placebo(arm_group_types: Iterable[str | None] | None) -> bool | None:
    """True when every comparator arm the registry lists delivers no drug.

    :param arm_group_types: from :func:`load_cached_arm_group_types`.
    :returns: True for placebo / sham / no-intervention comparators only, False for active
        comparators only, None when the record is missing, carries a type this enum does not
        know, lists no comparator arm, or mixes the two (which arm the store means is then
        not decidable from the registry).
    """
    if arm_group_types is None:
        return None
    comparators: set[ArmGroupType] = set()
    for value in arm_group_types:
        try:
            arm_type = ArmGroupType(value)
        except ValueError:
            return None
        if arm_type in NO_DRUG_COMPARATORS or arm_type in DRUG_COMPARATORS:
            comparators.add(arm_type)
    if not comparators:
        return None
    if comparators <= NO_DRUG_COMPARATORS:
        return True
    if comparators <= DRUG_COMPARATORS:
        return False
    return None
