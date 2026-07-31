#!/usr/bin/env python3
"""Re-ingest ARISTOTLE and PLATO from their protocol PDFs, then report what landed.

Both studies were built from ClinicalTrials.gov eligibility summaries of 421 and
523 characters, which carry no laboratory thresholds, so both emit zero
RangeHighRatio against a gold that expects 3 and 4. The documents that do carry
them are now in ``data/papers`` and ``parser.py`` auto-discovers that directory.

This runs the three stages the API would:

    run_generate_from_nct(force_refresh=True)   fetch NCT + enrich from local PDFs
    apply_artifact(["eligibility"])             draft is isolated until applied
    process_eligibility()                       criteria -> concepts + valueConstraint

``force_refresh`` matters: ``run_generate_from_nct`` returns a cached artifact when
one exists for the same generator version, and every one of these studies already
has a ``generate_from_nct`` artifact from the CT.gov-only run. Without it the PDFs
would never be read and the run would report success having changed nothing.

Writes to whatever ``TTE_STORE_PATH`` points at -- the caller is expected to point
it at a copy, because this mutates study records and the canonical store has to
keep meaning "as ingested from CT.gov" for the before/after to stay readable.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, "/app")

from src.services.tte_service import TTEService  # noqa: E402
from src.services.tte_store import TTEStore  # noqa: E402

TARGETS = [(3, "NCT00412984", "ARISTOTLE", 3), (2, "NCT00391872", "PLATO", 4)]
RATIO_TEXT = re.compile(r"(?i)\bULN\b|upper limit of normal")


def criteria_of(study: dict) -> list[dict]:
    el = study.get("eligibility") or {}
    return [*(el.get("inclusionCriteria") or []), *(el.get("exclusionCriteria") or [])]


def report(label: str, study: dict) -> tuple[int, int]:
    """Print the criteria whose constraint reaches the builder as a ratio.

    Counts what ``build_measurement_value_filter`` actually emits, not what the
    description says. The first version of this grepped descriptions for "ULN" and
    reported PLATO as a failure: ``process_eligibility`` had renamed the criterion
    to "Troponin/CK-MB elevation" while leaving
    ``unitText: "upper limit of normal"`` intact, so the constraint was correct and
    the instrument could not see it. That false failure also set a non-zero exit
    and suppressed the arms benchmark that would have caught it.

    :param label: "before" or "after".
    :param study: the study record to inspect.
    :returns: (criteria count, ratio-emitting constraint count).
    """
    from src.services.value_constraint import build_measurement_value_filter

    rows = criteria_of(study)
    ratio = []
    for c in rows:
        fragment = build_measurement_value_filter(c.get("valueConstraint"))
        if "RangeHighRatio" in fragment or "RangeLowRatio" in fragment:
            ratio.append((c, fragment))

    print(f"  [{label}] criteria={len(rows)}  ratio-emitting={len(ratio)}")
    for c, fragment in ratio:
        print(f"      · {' '.join((c.get('description') or '').split())[:100]}")
        print(f"        unitText={(c.get('valueConstraint') or {}).get('unitText')!r} -> {fragment}")

    # Named for a bound but carrying nothing is the interesting failure, so say it.
    dropped = [
        c for c in rows
        if RATIO_TEXT.search(c.get("description") or "") and not c.get("valueConstraint")
    ]
    for c in dropped:
        print(f"      ! no valueConstraint: {' '.join((c.get('description') or '').split())[:100]}")

    return len(rows), len(ratio)


def main() -> int:
    store = TTEStore(os.environ["TTE_STORE_PATH"])
    service = TTEService(store)
    failures = 0

    for study_id, nct_id, name, gold in TARGETS:
        print(f"\n=== {name} (study {study_id}, {nct_id}) — gold RangeHighRatio {gold} ===",
              flush=True)
        report("before", store.get_study(study_id))

        resp = service.run_generate_from_nct(study_id, nct_id, force_refresh=True)
        print(f"  generate_from_nct: status={resp.status} artifact={resp.artifactId}", flush=True)
        paper = (resp.meta or {}).get("paperStatus") or {}
        print(f"    paperStatus.source={paper.get('source')} "
              f"papers={[p.get('name') for p in paper.get('papers_found') or []]} "
              f"supplement={paper.get('supplement_available')}", flush=True)
        if resp.status != "completed" or not resp.artifactId:
            print(f"  FAILED: {resp.summary}")
            failures += 1
            continue

        version = int(store.get_study(study_id).get("version") or 1)
        applied = service.apply_artifact(resp.artifactId, ["eligibility"], version)
        print(f"  apply_artifact: {applied}", flush=True)

        service.process_eligibility(study_id)
        total, hits = report("after", store.get_study(study_id))
        if hits == 0:
            print(f"  WARNING: {name} still has no ULN-bearing criterion — the PDF text "
                  f"reached extraction in a dry run, so look at process_eligibility, not the PDF")
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
