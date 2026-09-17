#!/usr/bin/env python3
"""Verify that the site-zero fixes are actually present in a freshly exported delivery.

Three defects the 2026-09-12 hospital reports exposed, each with a committed fix:

  C  concept-field  `isExcluded` members carried 2 of the fields Atlas reads, so Atlas
                    could not draw the concept set (b3f81ab, build path)
  B  entry-absence  an absence rule whose concept set contains the entry event made the
                    cohort empty on any CDM (686c9cb, export path)
  A  presence-unit  a Unit filter on an inclusion rule zeroed cohorts at a site whose
                    unit_concept_id differs (2f95aac, export path)

"The defect is gone" is not evidence on its own. A re-extraction re-rolls a large share
of criteria -- defect B itself was introduced by one -- so a defect can vanish simply
because the rule that carried it was not generated this time. Each check therefore
answers three questions and reports one of four verdicts:

  control     does the check FAIL on the unfixed baseline? If not, it cannot see the
              defect and its PASS means nothing                      -> CONTROL-BROKEN
  applicable  did the candidate actually exercise the fixed path? If not, a clean result
              proves nothing about the fix                            -> UNVERIFIABLE
  reflected   is the defect absent from the candidate AND does re-applying the repair
              change nothing?                                         -> PASS / FAIL

Read-only. Repairs are applied to in-memory copies; no file is written.

Exit codes: 0 every fix PASS; 1 any FAIL or CONTROL-BROKEN; 3 no FAIL but at least one
UNVERIFIABLE; 2 could not run (vocabulary unreachable, missing input).

Usage:
    .venv/bin/python scripts/verify_fix_reflection.py \\
        --baseline deliveries/2026-09-12 \\
        --candidate output/site_gap/<run>/DELIVERY \\
        --export-log output/site_gap/<run>/export.log
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Log lines the export-time repairs emit when they fire. They are the applicability
# signal for the two export-path fixes: without one, the fixed path never ran.
ENTRY_REPAIR_FIRED = "entry-exclusion repair:"
UNIT_REPAIR_FIRED = "presence-unit repair: rule"
UNIT_REPAIR_DECLINED = "presence-unit repair declines"


@dataclass
class Verdict:
    fix: str
    verdict: str
    notes: list[str] = field(default_factory=list)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.circe.json"))


def _count_excluded_items(doc: dict) -> int:
    return sum(
        1
        for cs in doc.get("ConceptSets") or []
        for item in (cs.get("expression") or {}).get("items") or []
        if item.get("isExcluded")
    )


def check_concept_fields(baseline: Path, candidate: Path) -> Verdict:
    atlas = _load_script("verify_atlas_renderable")
    v = Verdict("C concept-field", "")

    base_problems = sum(len(atlas.check_file(f)) for f in _files(baseline))
    v.notes.append(f"control: baseline has {base_problems} member(s) Atlas cannot render")
    if base_problems == 0:
        v.verdict = "CONTROL-BROKEN"
        return v

    excluded = sum(_count_excluded_items(json.loads(f.read_text())) for f in _files(candidate))
    v.notes.append(f"applicable: candidate carries {excluded} isExcluded member(s)")
    if excluded == 0:
        v.verdict = "UNVERIFIABLE"
        v.notes.append("no isExcluded member was generated, so the fixed append path did not run")
        return v

    problems = {f.name: atlas.check_file(f) for f in _files(candidate)}
    bad = {k: p for k, p in problems.items() if p}
    v.notes.append(f"reflected: {len(bad)} candidate file(s) with unrenderable members")
    for name, plist in bad.items():
        v.notes.append(f"  {name}: {plist[0]}")
    v.verdict = "FAIL" if bad else "PASS"
    return v


def _run_detector(directory: Path) -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_entry_exclusion_conflict.py"),
            str(directory),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode == 2:
        raise SystemExit(
            "CANNOT RUN: entry-exclusion detector could not run\n"
            f"{result.stdout}{result.stderr}"
        )
    return result.returncode


def _repair_changes(directory: Path, repair, vocab) -> dict[str, int]:
    from src.services.conceptset_closure import items_of_cohort

    changed: dict[str, int] = {}
    for f in _files(directory):
        doc = json.loads(f.read_text())
        work = copy.deepcopy(doc)
        records = repair(work, vocab.prefetch(items_of_cohort(work)))
        if json.dumps(work, sort_keys=True) != json.dumps(doc, sort_keys=True):
            changed[f.name] = len(records)
    return changed


def check_entry_absence(baseline: Path, candidate: Path, log_text: str | None, vocab) -> Verdict:
    from src.services.entry_exclusion_repair import repair_entry_exclusion_conflicts

    v = Verdict("B entry-absence", "")

    base_exit = _run_detector(baseline)
    base_changes = _repair_changes(baseline, repair_entry_exclusion_conflicts, vocab)
    v.notes.append(
        f"control: baseline detector exit {base_exit}, "
        f"repair would change {sorted(base_changes)}"
    )
    if base_exit != 1 or not base_changes:
        v.verdict = "CONTROL-BROKEN"
        return v

    fired = None if log_text is None else log_text.count(ENTRY_REPAIR_FIRED)
    v.notes.append(f"applicable: repair fired {fired} time(s) during export" if fired is not None
                   else "applicable: no export log given")
    cand_exit = _run_detector(candidate)
    residual = _repair_changes(candidate, repair_entry_exclusion_conflicts, vocab)
    v.notes.append(
        f"reflected: candidate detector exit {cand_exit}, "
        f"re-applying repair would change {sorted(residual)}"
    )

    if cand_exit == 1 or residual:
        v.verdict = "FAIL"
    elif not fired:
        v.verdict = "UNVERIFIABLE"
        v.notes.append(
            "candidate is clean but the repair never fired, "
            "so the conflicting rule was not generated"
        )
    else:
        v.verdict = "PASS"
    return v


def _unit_filters(doc) -> int:
    count = 0
    stack = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if isinstance(node.get("Unit"), list) and node["Unit"]:
                count += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return count


def check_presence_unit(baseline: Path, candidate: Path, log_text: str | None, vocab) -> Verdict:
    from src.services.presence_unit_repair import repair_presence_unit_filters

    v = Verdict("A presence-unit", "")

    base_changes = _repair_changes(baseline, repair_presence_unit_filters, vocab)
    v.notes.append(
        f"control: repair would remove unit filters in baseline files {sorted(base_changes)}"
    )
    if not base_changes:
        v.verdict = "CONTROL-BROKEN"
        return v

    if log_text is None:
        fired = declined = None
        v.notes.append("applicable: no export log given")
    else:
        fired = log_text.count(UNIT_REPAIR_FIRED)
        declined = log_text.count(UNIT_REPAIR_DECLINED)
        v.notes.append(
            f"applicable: {fired} unit filter(s) removed, {declined} declined during export"
        )

    residual = _repair_changes(candidate, repair_presence_unit_filters, vocab)
    remaining = sum(_unit_filters(json.loads(f.read_text())) for f in _files(candidate))
    v.notes.append(
        f"reflected: re-applying repair would change {sorted(residual)}; "
        f"{remaining} unit filter(s) remain "
        "(exclusions and declined inclusions keep theirs)"
    )

    if residual:
        v.verdict = "FAIL"
    elif not fired:
        v.verdict = "UNVERIFIABLE"
        v.notes.append(
            "no removable unit filter was generated, so the repair had nothing to act on"
        )
    else:
        v.verdict = "PASS"
    return v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--baseline", type=Path, required=True,
        help="unfixed delivery, e.g. deliveries/2026-09-12",
    )
    ap.add_argument(
        "--candidate", type=Path, required=True,
        help="freshly exported DELIVERY directory",
    )
    ap.add_argument("--export-log", type=Path, help="log of the export that produced --candidate")
    args = ap.parse_args(argv)

    for label, path in (("baseline", args.baseline), ("candidate", args.candidate)):
        if not _files(path):
            print(f"CANNOT RUN: no *.circe.json under {label} {path}")
            return 2
    log_text = args.export_log.read_text() if args.export_log else None

    from src.services.conceptset_closure import PostgresVocabulary
    from src.settings import settings

    try:
        vocab = PostgresVocabulary(settings.DATABASE_URL, settings.CDM_SCHEMA)
        vocab.__enter__()
    except Exception as exc:  # noqa: BLE001 -- fail loudly, never fall back
        print(f"CANNOT RUN: vocabulary unreachable ({settings.CDM_SCHEMA}): {exc}")
        return 2

    try:
        verdicts = [
            check_concept_fields(args.baseline, args.candidate),
            check_entry_absence(args.baseline, args.candidate, log_text, vocab),
            check_presence_unit(args.baseline, args.candidate, log_text, vocab),
        ]
    finally:
        vocab.__exit__(None, None, None)

    for v in verdicts:
        print(f"{v.verdict:15s} {v.fix}")
        for note in v.notes:
            print(f"                  {note}")

    kinds = {v.verdict for v in verdicts}
    if kinds & {"FAIL", "CONTROL-BROKEN"}:
        return 1
    if "UNVERIFIABLE" in kinds:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
