#!/usr/bin/env python3
"""SPEC-INFRA-003 REQ-006 / AC-008: measure agent1's emission stability across N runs.

Agent1's decomposition is not deterministic. An earlier regeneration of CARMELINA from
the same protocol text produced 2 top-level criteria for exclusion #10 where the current
reference store holds 3 (`spec.md` §2.4). That is the only pre-fix evidence on record --
two runs, observed in passing, never reproduced. AC-008 asks for N >= 5 runs on identical
input, the emitted count recorded per run for each `spec.md` §2.1 sentence, and the
pre-fix and post-fix distributions reported side by side.

This driver supplies the runs. The counting, the distributions, and the verdicts live in
``src/services/emission_stability.py`` and are unit-tested there; everything here is the
I/O around them.

**How a run is executed.** Each run copies the base store, points ``TTE_STORE_PATH`` at
the copy, and invokes ``scripts/reingest_protocol_pdfs.py`` as a subprocess. That script
is the established entry point for exactly this pipeline sequence -- ``force_refresh``
generate, apply, ``process_eligibility``, apply -- and re-implementing the sequence here
would leave two copies to drift apart. It is invoked rather than imported because its
module body parses ``REINGEST_STUDIES`` and can raise at import time, and because a
subprocess per run keeps one run's in-process state from reaching the next.

**The base store is copied, never written.** ``reingest_protocol_pdfs`` mutates whatever
``TTE_STORE_PATH`` names, and its own docstring expects the caller to point it at a copy.
Runs sharing one store would each read the previous run's output, which is neither
identical input nor an independent draw.

**A failed run is not a run that emitted nothing.** A non-zero reingest exit, a missing
study record, or a study whose eligibility never processed aborts the measurement.
Recording zero would make the report read VANISHED for that sentence -- a stable,
deterministic-looking regression produced by a pipeline that silently did not run.

Usage (inside the ``artemis-api`` container, where the vLLM backend is reachable)::

    TTE_STORE_PATH=/app/tmp/tte_six_20260823_patternG_v2/studies.json \\
      python scripts/measure_emission_stability.py \\
        --runs 5 --out /app/output/stability/pre-fix --side pre

    # after M4's prompt change, rendered against the baseline above:
    TTE_STORE_PATH=... python scripts/measure_emission_stability.py \\
      --runs 5 --out /app/output/stability/post-fix \\
      --baseline /app/output/stability/pre-fix/measurement.json

``--out`` must name a bind-mounted path if the results are wanted on the host: a
container path with no mount accepts the write, prints the path, and leaves nothing
behind.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.services.emission_stability import (  # noqa: E402
    MINIMUM_RUNS,
    SPEC_2_1_WATCHES,
    RunCriteria,
    SentenceWatch,
    criteria_from_study_record,
    measure_emission_stability,
    render_comparison,
    report_from_dict,
    report_to_dict,
)

_REINGEST = _REPO_ROOT / "scripts" / "reingest_protocol_pdfs.py"


def _watched_study_ids(watches: tuple[SentenceWatch, ...]) -> list[int]:
    """Return the studies the watches cover, in ascending order.

    Derived from the watches rather than hardcoded: the reingest entry point refuses a
    study id it has no target for, and a list that drifted from the watches would either
    reingest studies nothing measures or measure a study nothing reingested.

    Args:
        watches: The sentences being measured.

    Returns:
        Distinct study ids, sorted.
    """
    return sorted({watch.study_id for watch in watches})


def _load_run(store_path: Path, study_ids: list[int]) -> RunCriteria:
    """Read one run's emitted criteria back out of its store copy.

    Args:
        store_path: The run's ``studies.json``.
        study_ids: The studies to read.

    Returns:
        study id -> role -> that role's top-level criteria.

    Raises:
        LookupError: When the store holds no record for a watched study.
        ValueError: When a watched study's eligibility was never processed.
    """
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    records = {
        int(study["id"]): study
        for study in (payload.get("studies") or [])
        if study.get("id") is not None
    }

    run: dict[int, dict[str, list]] = {}
    for study_id in study_ids:
        if study_id not in records:
            raise LookupError(
                f"{store_path} holds no record for study {study_id}; the run did not "
                f"produce the study being measured"
            )
        run[study_id] = criteria_from_study_record(records[study_id])
    return run


def _make_run_once(*, base_store: Path, out_dir: Path, study_ids: list[int]):
    """Build the ``run_once`` the measurement injects.

    Args:
        base_store: The store to copy for each run. Never written to.
        out_dir: Where per-run store copies and reingest logs are kept.
        study_ids: The studies to reingest and read back.

    Returns:
        A callable taking the zero-based run index and returning that run's criteria.
    """
    def run_once(index: int) -> RunCriteria:
        run_dir = out_dir / f"run-{index}"
        run_dir.mkdir(parents=True, exist_ok=True)
        store_copy = run_dir / "studies.json"
        shutil.copyfile(base_store, store_copy)

        env = {
            **os.environ,
            "TTE_STORE_PATH": str(store_copy),
            "REINGEST_STUDIES": ",".join(str(i) for i in study_ids),
        }
        log_path = run_dir / "reingest.log"
        print(f"  run {index}: reingest studies {study_ids} -> {store_copy}", flush=True)
        completed = subprocess.run(
            [sys.executable, str(_REINGEST)],
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"run {index}: reingest exited {completed.returncode}; see {log_path}. "
                f"Aborting rather than recording an emitted count for a run that failed."
            )

        return _load_run(store_copy, study_ids)

    return run_once


def main(argv: list[str] | None = None) -> int:
    """Run the measurement and write the report.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        0 when the measurement completed, 2 when the base store is unusable. An
        UNSTABLE verdict is a result rather than an error -- M3 expects one.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--runs", type=int, default=MINIMUM_RUNS,
        help=f"how many times to run agent1 on identical input (minimum {MINIMUM_RUNS})",
    )
    parser.add_argument(
        "--out", required=True,
        help="directory for per-run stores, logs, and the report",
    )
    parser.add_argument(
        "--baseline", default=None,
        help="a previous measurement.json to render this one against (AC-008 side by side)",
    )
    parser.add_argument(
        "--side", choices=("pre", "post"), default="post",
        help="which column this measurement fills when a baseline is given",
    )
    args = parser.parse_args(argv)

    base_store = Path(os.environ["TTE_STORE_PATH"])
    if not base_store.is_file():
        print(f"TTE_STORE_PATH does not name a file: {base_store}", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    study_ids = _watched_study_ids(SPEC_2_1_WATCHES)

    print(f"measuring {len(SPEC_2_1_WATCHES)} sentences over {args.runs} runs", flush=True)
    print(f"  base store (copied, not written): {base_store}", flush=True)

    report = measure_emission_stability(
        watches=list(SPEC_2_1_WATCHES),
        run_once=_make_run_once(
            base_store=base_store, out_dir=out_dir, study_ids=study_ids
        ),
        runs=args.runs,
    )

    measurement_path = out_dir / "measurement.json"
    measurement_path.write_text(
        json.dumps(report_to_dict(report), indent=2), encoding="utf-8"
    )

    baseline = None
    if args.baseline:
        baseline = report_from_dict(
            json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        )

    if baseline is None:
        # One side only. Which column it fills still matters: M3's baseline is the
        # pre-fix measurement, and rendering it as post-fix would invert the comparison
        # M4 later reads.
        rendered = render_comparison(
            pre=report if args.side == "pre" else None,
            post=None if args.side == "pre" else report,
        )
    else:
        rendered = render_comparison(
            pre=baseline if args.side == "post" else report,
            post=report if args.side == "post" else baseline,
        )

    report_path = out_dir / "report.md"
    report_path.write_text(rendered + "\n", encoding="utf-8")

    print()
    print(rendered)
    print()
    print(f"measurement: {measurement_path}")
    print(f"report:      {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
