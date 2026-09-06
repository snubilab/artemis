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

import logging
import os
import re
import sys

sys.path.insert(0, "/app")

from src.services.tte_service import TTEService  # noqa: E402
from src.services.tte_store import TTEStore  # noqa: E402

_ALL_TARGETS = [
    (3, "NCT00412984", "ARISTOTLE", 3),
    (2, "NCT00391872", "PLATO", 4),
    (10, "NCT01243424", "CAROLINA", 3),
    (8, "NCT01131676", "EMPA-REG", 3),
    (9, "NCT01897532", "CARMELINA", 3),
    # LEADER expects zero: its appendix's three ULN mentions are lipase result
    # figures, not eligibility criteria, and the gold carries none either. It is
    # here so "all six studies, one code path" is literally true.
    (1, "NCT01179048", "LEADER", 0),
]

# REINGEST_STUDIES exists so a smoke run can reach the failure regime on one study
# instead of paying for both. ARISTOTLE alone is the interesting case: it is where
# the LLM dropped the constraint.
_WANTED = {int(x) for x in (os.environ.get("REINGEST_STUDIES") or "").split(",") if x.strip()}
TARGETS = [t for t in _ALL_TARGETS if not _WANTED or t[0] in _WANTED]
if _WANTED:
    # A study id with no entry here used to yield an empty TARGETS, a loop that ran
    # zero times, and exit 0 -- a run reporting success having done nothing. The
    # log was zero lines and only a gate caught it.
    _unknown = _WANTED - {t[0] for t in _ALL_TARGETS}
    if _unknown:
        raise SystemExit(
            f"REINGEST_STUDIES names {sorted(_unknown)}, which have no entry in "
            f"_ALL_TARGETS {sorted(t[0] for t in _ALL_TARGETS)}. Refusing to run "
            f"and report success for studies that were never processed."
        )
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


LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"
HANDLER_NAME = "reingest"


def configure_logging() -> None:
    """Route the pipeline's own INFO records to stderr.

    ``_invoke_and_extract`` logs the prompt/completion split on every LLM call so a
    shrinking token budget is visible before it runs out. Nothing here configured
    logging, so the effective level was WARNING with no handler and every one of those
    records was discarded -- while ``logger.error`` still reached stderr through
    ``logging.lastResort``. The failure was visible and the warning that precedes it
    was not, which is the wrong half to lose.

    Scoped to the ``src`` logger rather than the root: raising the root to INFO also
    turns on httpx, urllib3 and neo4j, and this log is already hard enough to read.
    Idempotent, because ``main()`` may run more than once in a process and a second
    handler would print every count twice.
    """
    pipeline = logging.getLogger("src")
    if any(h.get_name() == HANDLER_NAME for h in pipeline.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    pipeline.addHandler(handler)
    pipeline.setLevel(logging.INFO)


def main() -> int:
    configure_logging()
    store = TTEStore(os.environ["TTE_STORE_PATH"])
    service = TTEService(store)
    failures = 0

    for study_id, nct_id, name, gold in TARGETS:
        print(f"\n=== {name} (study {study_id}, {nct_id}) — gold RangeHighRatio {gold} ===",
              flush=True)
        try:
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

            # process_eligibility produces an artifact and does NOT write through. Skipping
            # this apply left the study with new criteria, no conceptSetId on any of them
            # and structuredExpression=None, which then failed generate_seeded_cohorts with
            # "Eligibility must be processed before generating treatment cohorts" -- an
            # error naming the step that had just run. Applying it takes ARISTOTLE from
            # 0 to 39 mapped criteria and 40 Circe concept sets.
            processed = service.process_eligibility(study_id)
            if processed.artifactId:
                version = int(store.get_study(study_id).get("version") or 1)
                service.apply_artifact(processed.artifactId, ["eligibility"], version)
                print(f"  process_eligibility applied: {processed.artifactId}", flush=True)
            else:
                print(f"  WARNING: process_eligibility returned no artifact ({processed.status})")
                failures += 1

            total, hits = report("after", store.get_study(study_id))
            # Guarded on gold: LEADER legitimately expects zero, and counting that as a
            # failure would set a non-zero exit and suppress the verification that runs
            # after this script -- the same false-failure shape the report() docstring
            # describes.
            if gold > 0 and hits == 0:
                print(f"  WARNING: {name} still has no ULN-bearing criterion — the PDF text "
                      f"reached extraction in a dry run, so look at process_eligibility, not the PDF")
                failures += 1
            elif gold == 0 and hits > 0:
                print(f"  WARNING: {name} expected no ratio constraint but produced {hits}")
                failures += 1
        except Exception as exc:
            # One study's draft can be legitimately refused (e.g. _reject_criteria_loss
            # catching a truncated LLM response that would have emptied a populated
            # study) or fail for any other reason. That is real signal, not a reason to
            # lose the other five studies -- a batch tool that dies on the first
            # exception is why a 9-hour run reported nothing for the studies after it.
            print(f"  FAILED: {name} raised {type(exc).__name__}: {exc}", flush=True)
            failures += 1
            continue

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
