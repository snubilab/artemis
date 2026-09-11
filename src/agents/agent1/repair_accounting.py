"""The ledger every post-parse repair writes to, and the gate that reads it.

A repair in :mod:`src.agents.agent1.parser` rewrites the flat rule list: it merges
two halves of a band into one criterion, drops a restatement, or moves a run of
top-level rules under a synthesised group. Each of those changes what the store
will hold, and until this module existed the only trace of any of them was a
``logger.info`` line -- which reaches no store, no gate, and no reader of a
delivery.

That is the failure this module exists to make impossible. ``_repair_band_tiers``
dropped CAROLINA's third HbA1c tier and logged the protocol line it took with it;
the store carried no record of either, so a criterion that had been present became
absent with nothing naming it. The delivery gate could not catch it, because its
census is computed against the post-repair store and a criterion that never
reaches the store is invisible to it.

Two things are recorded, and they are not the same thing:

``departure``
    The criterion is not in the rule tree any more. Either it was folded into a
    survivor (a band's two halves become one ``bt`` criterion) or it was dropped
    outright (a restatement). Every departure MUST be recorded; that is what
    :func:`assert_repairs_accounted` enforces.

``demotion``
    The criterion is still in the tree, but it is no longer a TOP-LEVEL rule --
    a repair moved it under a synthesised group. This is not a departure and the
    gate does not require it, but it is recorded because it is not
    consequence-free: :meth:`~src.agents.planner.decomposer.CriteriaPlanner._decompose_criterion`
    returns early on a criterion that already carries ``sub_criteria`` and
    ``_process_cohort`` iterates top-level rules only, so a demoted rule's
    protocol line stops being decomposed. That is how CAROLINA's six drug-therapy
    criteria stopped being produced: nothing dropped them, the line they were
    decomposed FROM stopped being visited.
"""
from __future__ import annotations

from typing import Any, Iterable

#: The one spelling of the key, for every producer and every reader of it. The store
#: writer (`TTEService._study_from_ir`), the apply-path carry-forward
#: (`TTEService._merge_eligibility_section`) and the delivery gate
#: (`scripts/verify_circe_delivery.py`) all import it from here, so a rename cannot
#: leave one of the three writing or reading a key the others do not.
REPAIR_ACCOUNTING_KEY = "_repairAccounting"

#: The three dispositions :class:`RepairLedger` writes, and the only three a reader may
#: recognise. A reader that meets a fourth must FAIL rather than pass it unread: the
#: ledger is a reconciliation, and an unreadable record is an unreconciled criterion.
DISPOSITION_DEPARTURE = "departure"
DISPOSITION_DEMOTION = "demotion"
DISPOSITION_REWRITE = "rewrite"
KNOWN_DISPOSITIONS = frozenset(
    {DISPOSITION_DEPARTURE, DISPOSITION_DEMOTION, DISPOSITION_REWRITE}
)


class UnaccountedDepartureError(RuntimeError):
    """A criterion left the rule tree and no repair recorded taking it."""


def iter_nodes(rules: Iterable[Any]) -> list[Any]:
    """Every criterion in the tree, parents before children, in order."""
    out: list[Any] = []
    for rule in rules or ():
        out.append(rule)
        sub = getattr(rule, "sub_criteria", None)
        if sub:
            out.extend(iter_nodes(sub))
    return out


def _describe(criterion: Any) -> dict[str, Any]:
    """The identifying fields of a criterion, for a record a human can act on."""
    vc = getattr(criterion, "value_constraint", None)
    constraint = None
    if vc is not None:
        constraint = {
            "op": getattr(vc, "op", None),
            "value": getattr(vc, "value", None),
            "valueHigh": getattr(vc, "value_high", None),
            "unitText": getattr(vc, "unit_text", None),
        }
    return {
        "name": getattr(criterion, "name", None),
        "domain": getattr(criterion, "domain", None),
        "entityText": getattr(criterion, "entity_text", None),
        "logicType": getattr(criterion, "logic_type", None),
        "valueConstraint": constraint,
        # The protocol line is the part that matters most in a record of a loss:
        # it is the only field that says what the cohort no longer asks about.
        "sourceText": getattr(criterion, "source_text", None),
    }


class RepairLedger:
    """What each repair did, and to which criterion.

    Holds the criterion OBJECT alongside its serialisable record, because the gate
    matches departures by object identity: two rules in one trial can carry the
    same name, domain and bound (CAROLINA emits ``Age >= 70 years`` twice), so a
    field-tuple key would let a real departure be signed off by its twin.
    """

    def __init__(self) -> None:
        self._entries: list[tuple[Any, dict[str, Any]]] = []

    def __len__(self) -> int:
        return len(self._entries)

    def _add(self, criterion: Any, record: dict[str, Any]) -> None:
        self._entries.append((criterion, record))

    def departed(self, criterion: Any, *, action: str, reason: str,
                 survivor: Any = None) -> None:
        """Record a criterion that is no longer in the tree.

        :param action: the repair's own name for what it did, e.g.
            ``merged-into-band`` or ``dropped-as-restatement``.
        :param reason: why, in a sentence a reader of a delivery can act on.
        :param survivor: the criterion that carries this one's meaning now, when
            one does. ``None`` means nothing does -- an outright drop.
        """
        record = {
            "disposition": "departure",
            "action": action,
            "reason": reason,
            "criterion": _describe(criterion),
            "survivor": _describe(survivor) if survivor is not None else None,
        }
        self._add(criterion, record)

    def demoted(self, criterion: Any, *, action: str, group_name: str,
                reason: str) -> None:
        """Record a criterion a repair moved from top level into a group."""
        record = {
            "disposition": "demotion",
            "action": action,
            "groupName": group_name,
            "reason": reason,
            "criterion": _describe(criterion),
        }
        self._add(criterion, record)

    def rewritten(self, criterion: Any, *, action: str, reason: str,
                  before: dict[str, Any], after: dict[str, Any]) -> None:
        """Record a criterion a repair kept but whose meaning it changed.

        Not a departure and not a demotion: the criterion is where it was. It is
        recorded because moving a boundary changes who enters the cohort, and a
        change of that kind with no record is the same defect as a silent drop
        wearing a different shape.
        """
        record = {
            "disposition": "rewrite",
            "action": action,
            "reason": reason,
            "before": before,
            "after": after,
            "criterion": _describe(criterion),
        }
        self._add(criterion, record)

    def accounted_ids(self) -> set[int]:
        """The criteria whose absence from the tree a repair has explained.

        Demotions are deliberately NOT in here. A demoted criterion is still in the
        tree, so it never shows up as a departure anyway -- but the ledger
        accumulates across repair steps, and counting a demotion as an explanation
        would let "a later repair moved this into a group" sign off "a still later
        repair deleted it". Only a record that says the criterion is gone may
        satisfy the gate that asks where it went.
        """
        return {
            id(criterion)
            for criterion, record in self._entries
            if record["disposition"] != "demotion"
        }

    def records(self) -> list[dict[str, Any]]:
        return [record for _, record in self._entries]


def assert_repairs_accounted(before: Iterable[Any], after: Iterable[Any],
                             ledger: RepairLedger, *, role: str) -> None:
    """Every criterion present before the repairs is present after, or recorded.

    This is the gate. It runs on every parse, not only in tests: a repair added
    later that removes a criterion without recording it fails here, at the point
    the removal happens, rather than in a delivery three stages downstream where
    the only remaining evidence is an absence.

    :raises UnaccountedDepartureError: naming every unaccounted criterion, with
        its protocol line, so the message identifies what was lost rather than
        only how many.
    """
    after_ids = {id(node) for node in iter_nodes(after)}
    accounted = ledger.accounted_ids()
    missing = [
        node for node in iter_nodes(before)
        if id(node) not in after_ids and id(node) not in accounted
    ]
    if not missing:
        return
    lines = "\n".join(
        f"  - [{getattr(node, 'domain', '?')}] {getattr(node, 'name', '?')!r}"
        f" (protocol line: {(getattr(node, 'source_text', None) or '')[:120]!r})"
        for node in missing
    )
    raise UnaccountedDepartureError(
        f"{len(missing)} {role} criterion/criteria left the rule tree during "
        f"post-parse repair and no repair recorded taking them. A recorded "
        f"refusal is acceptable; a silent disappearance is not -- the store's "
        f"census is computed after the repairs run, so a criterion that never "
        f"reaches it cannot be missed by any downstream check.\n{lines}"
    )
