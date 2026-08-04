#!/usr/bin/env python3
"""Export circe definitions from a TTE store, or check the exported ones still match.

`eligibility.structuredExpression` holds the core expression -- ConceptSets,
InclusionRules, PrimaryCriteria. A cohort definition WebAPI will accept also
needs four wrapper keys, which the registration path normally adds. This writes
the complete form, so the files can be handed over or registered as they are.

``--check`` rebuilds in memory and fails if the files on disk differ. Pointed at
a snapshot, that is the recovery guarantee stated out loud: `tmp/` is gitignored
and holds stores that cost GPU hours, so the claim that losing it is survivable
should be a command someone can run, not a sentence in a document.

Usage:
    # export
    python3 scripts/export_circe_from_store.py \\
        --store tmp/tte_six_deliver/studies.json --out output/circe_be/2026-08-03

    # verify the deliverable is still reproducible from its snapshot
    python3 scripts/export_circe_from_store.py \\
        --store snapshots/2026-08-04_six-studies_deliverable.json \\
        --out output/circe_be/2026-08-03 --check

See omx_wiki/tte-artifact-locations.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ARTEMIS_DIR = Path(__file__).resolve().parent.parent

# Added by the registration path; the stored expression carries only the core.
# Values taken from WebAPI definition 3394, which generated successfully.
WRAPPER = {
    "cdmVersionRange": ">=5.0.0",
    "QualifiedLimit": {"Type": "First"},
    "ExpressionLimit": {"Type": "First"},
    "CollapseSettings": {"CollapseType": "ERA", "EraPad": 0},
}

STUDIES = {
    3: ("ARISTOTLE", "NCT00412984"),
    2: ("PLATO", "NCT00391872"),
    10: ("CAROLINA", "NCT01243424"),
    8: ("EMPA-REG", "NCT01131676"),
    9: ("CARMELINA", "NCT01897532"),
    1: ("LEADER", "NCT01179048"),
}


def build(store_path: Path) -> dict[str, str]:
    """Render every study's circe from a store.

    :param store_path: a studies.json, live store or snapshot.
    :returns: filename -> serialised circe JSON.
    """
    studies = json.loads(store_path.read_text())["studies"]
    rendered: dict[str, str] = {}
    for study_id, (name, nct) in STUDIES.items():
        study = next((s for s in studies if s["id"] == study_id), None)
        if study is None:
            print(f"  {name}: absent from {store_path}", file=sys.stderr)
            continue
        expression = (study.get("eligibility") or {}).get("structuredExpression")
        if not expression:
            print(f"  {name}: no structuredExpression", file=sys.stderr)
            continue
        if isinstance(expression, str):
            expression = json.loads(expression)
        # Store values win, so a study that already carries a wrapper key keeps it.
        circe = {**WRAPPER, **expression}
        rendered[f"{name}_{nct}_study{study_id}_circe.json"] = (
            json.dumps(circe, indent=2, ensure_ascii=False)
        )
    return rendered


def describe(filename: str, body: str) -> dict:
    """Manifest row for one exported file."""
    circe = json.loads(body)
    return {
        "study": filename.split("_")[0],
        "nct": filename.split("_")[1],
        "file": filename,
        "conceptSets": len(circe.get("ConceptSets") or []),
        "inclusionRules": len(circe.get("InclusionRules") or []),
        "rangeHighRatio": body.count("RangeHighRatio"),
        "isExcludedItems": sum(
            1 for cs in circe.get("ConceptSets") or []
            for item in (cs.get("expression") or {}).get("items") or []
            if item.get("isExcluded")
        ),
        "bytes": len(body.encode()),
        "md5": hashlib.md5(body.encode()).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="studies.json to read")
    ap.add_argument("--out", required=True, help="directory for the circe files")
    ap.add_argument("--check", action="store_true",
                    help="compare against what is already there and fail on any difference")
    args = ap.parse_args()

    store_path = Path(args.store)
    out_dir = Path(args.out)
    if not store_path.is_file():
        raise SystemExit(f"no store at {store_path}")

    rendered = build(store_path)
    if not rendered:
        raise SystemExit(f"{store_path} yielded no circe")

    if args.check:
        differences = []
        for filename, body in sorted(rendered.items()):
            target = out_dir / filename
            if not target.is_file():
                differences.append(f"{filename}: missing from {out_dir}")
            elif target.read_text() != body:
                differences.append(f"{filename}: differs from {store_path.name}")
        for line in differences:
            print(f"  {line}", file=sys.stderr)
        if differences:
            print(f"\n{len(differences)} of {len(rendered)} do not match — the exported "
                  f"deliverable cannot be reproduced from this store", file=sys.stderr)
            return 1
        print(f"all {len(rendered)} circe files reproduce exactly from {store_path.name}")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for filename, body in sorted(rendered.items()):
        (out_dir / filename).write_text(body)
        rows.append(describe(filename, body))
    (out_dir / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n")

    print(f"{'study':<11}{'CS':>4}{'IR':>4}{'RHR':>5}{'excl':>6}{'KB':>7}")
    for row in rows:
        print(f"{row['study']:<11}{row['conceptSets']:>4}{row['inclusionRules']:>4}"
              f"{row['rangeHighRatio']:>5}{row['isExcludedItems']:>6}{row['bytes'] // 1024:>7}")
    print(f"\nwrote {len(rows)} circe files and manifest.json to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
