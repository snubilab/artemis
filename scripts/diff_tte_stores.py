#!/usr/bin/env python3
"""Per-study movement between two TTE stores, criterion by criterion.

Keys a criterion by (kind, description) -- the id is re-assigned on every
re-ingest, so an id-keyed diff reports every row as changed. Where a description
repeats within one kind, the rows are matched in order.

TWO WAYS THIS TOOL CAN SILENTLY UNDER-REPORT, AND WHAT STOPS THEM
-----------------------------------------------------------------
It prints "NO MOVEMENT" per study, so a blind spot reads as a clean result. Both
known blind spots are now closed:

  * A field the diff does not compare is invisible. The first version compared
    eight fields and ignored seven, so a change to `sourceText`, `protocolLine`
    or `protocolSpan` reported as NO MOVEMENT. Every field is now either compared
    or explicitly listed as identity-only, and any field belonging to neither --
    a field added to the store schema after this was written -- is reported
    loudly rather than dropped.
  * A study the diff does not visit is invisible. The first version defaulted to
    a hardcoded six study ids while the store held ten, so four studies were
    never compared and never mentioned. The default is now every id present in
    either store, and ids missing from one side are named.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

#: Compared field by field. A difference here is real movement.
FIELDS = ("domain", "valueConstraint", "conceptSetName", "logicType",
          "groupType", "isGroupLabel", "mappable", "window",
          "sourceText", "protocolLine", "protocolSpan")

#: Deliberately NOT compared: re-assigned on every ingest, or the match key itself.
#: Listed rather than merely omitted so the guard below can tell "ignored on
#: purpose" apart from "nobody has looked at this field".
#: ``parentGroupId`` sits here with ``groupId`` for the same reason: it holds a uuid
#: minted fresh on every ingest, so comparing it would report movement on every run.
#: What it means -- whether a group is nested -- is observable through the compared
#: ``groupType`` and ``isGroupLabel`` of the rows around it.
IDENTITY_ONLY = ("id", "conceptSetId", "groupId", "parentGroupId", "description")


def load(path):
    with open(path) as fh:
        d = json.load(fh)
    studies = d["studies"] if isinstance(d, dict) and "studies" in d else d
    if isinstance(studies, dict):
        studies = list(studies.values())
    return {int(s["id"]): s for s in studies if s.get("id") is not None}


def unknown_fields(*stores) -> set[str]:
    """Fields present in the data that are neither compared nor identity-only.

    A field that turns up here is a blind spot: the diff would ignore it silently.
    """
    seen: set[str] = set()
    for store in stores:
        for study in store.values():
            el = study.get("eligibility") or {}
            for kind in ("inclusionCriteria", "exclusionCriteria"):
                for c in el.get(kind) or []:
                    seen.update(c.keys())
    return seen - set(FIELDS) - set(IDENTITY_ONLY)


def rows(study):
    el = study.get("eligibility") or {}
    out = []
    for kind in ("inclusionCriteria", "exclusionCriteria"):
        for c in el.get(kind) or []:
            out.append((kind[:3], str(c.get("description")), c))
    return out


def index(rs):
    ix = defaultdict(list)
    for kind, desc, c in rs:
        ix[(kind, desc)].append(c)
    return ix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--studies", default=None,
                    help="comma-separated study ids (default: every id in either store)")
    a = ap.parse_args()
    old, new = load(a.old), load(a.new)

    if a.studies:
        ids = [int(x) for x in a.studies.split(",")]
    else:
        ids = sorted(set(old) | set(new))
    print(f"comparing {len(ids)} stud{'y' if len(ids) == 1 else 'ies'}: "
          f"{','.join(map(str, ids))}")

    blind = unknown_fields(old, new)
    if blind:
        print(f"!! {len(blind)} criterion field(s) are NEITHER compared NOR listed as "
              f"identity-only: {sorted(blind)}")
        print("!! a change to any of them would report as NO MOVEMENT. Add them to "
              "FIELDS or to IDENTITY_ONLY.")

    moved = 0
    for sid in ids:
        o, n = old.get(sid), new.get(sid)
        if not o or not n:
            side = "new" if o else "old"
            print(f"\nstudy {sid}: present only in the {('old' if o else 'new')} store "
                  f"(missing from the {side} store) -- not compared")
            moved += 1
            continue
        ro, rn = rows(o), rows(n)
        io_, in_ = index(ro), index(rn)
        name = str(n.get("name"))[:40]
        oc = sum(1 for k, _, _ in ro if k == "inc"), sum(1 for k, _, _ in ro if k == "exc")
        nc = sum(1 for k, _, _ in rn if k == "inc"), sum(1 for k, _, _ in rn if k == "exc")
        print(f"\n=== study {sid}  {name}")
        print(f"    criteria  old inc/exc {oc[0]}/{oc[1]} (={sum(oc)})   "
              f"new inc/exc {nc[0]}/{nc[1]} (={sum(nc)})")
        gone = sorted(set(io_) - set(in_))
        added = sorted(set(in_) - set(io_))
        changed = []
        for k in sorted(set(io_) & set(in_)):
            for co, cn in zip(io_[k], in_[k]):
                diffs = {f: (co.get(f), cn.get(f)) for f in FIELDS if co.get(f) != cn.get(f)}
                if diffs:
                    changed.append((k, diffs))
            if len(io_[k]) != len(in_[k]):
                changed.append((k, {"_multiplicity": (len(io_[k]), len(in_[k]))}))
        if not gone and not added and not changed:
            print("    NO MOVEMENT")
            continue
        moved += 1
        for k in gone:
            print(f"    - REMOVED  [{k[0]}] {k[1][:90]}")
        for k in added:
            print(f"    + ADDED    [{k[0]}] {k[1][:90]}")
        for k, diffs in changed:
            print(f"    ~ CHANGED  [{k[0]}] {k[1][:80]}")
            for f, (a_, b_) in diffs.items():
                print(f"         {f}: {json.dumps(a_)[:150]}  ->  {json.dumps(b_)[:150]}")

    print(f"\n{moved} of {len(ids)} studies moved; {len(ids) - moved} unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
