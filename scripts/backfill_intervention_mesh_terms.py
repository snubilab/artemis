"""Backfill ``trialMetadata.interventionMeshTerms`` into an existing TTE store.

Why this exists
---------------
The entry-drug mapper resolves a sponsor development code through the trial's
MeSH intervention terms (``TTEService._alias_ingredient_mapping``): the OMOP
vocabulary has no row for 'BI 10773', but NLM's MeSH index says 'empagliflozin'
where every sponsor-authored field says 'BI 10773'.

``TTEService`` writes those terms when a study is imported with the raw
ClinicalTrials.gov payload available. Stores created before that -- or through
the minimal-metadata branch -- carry no ``interventionMeshTerms`` at all, so the
alias path is silently inactive and a code-named target falls through to
embedding search. In ``output/circe_atc_fix`` that turned EMPA-REG's target arm
into a mix of HIV and cystic-fibrosis drugs.

The terms are read from the local NCT cache (``data/nct_cache/<NCT>.json``,
``derivedSection.interventionBrowseModule``), which is the same field the
importer reads. A trial with no cache entry is reported, never guessed at.

Dry run by default; ``--apply`` writes after taking a dated backup.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "nct_cache"


def mesh_terms_for(nct_id: str, cache_dir: Path) -> list[str] | None:
    """Read a trial's MeSH intervention terms from the local NCT cache.

    :param nct_id: The trial registry id, e.g. ``NCT01131676``.
    :param cache_dir: Directory holding ``<NCT>.json`` payloads.
    :returns: The MeSH terms, or None when the trial is not cached.
    """
    path = cache_dir / f"{nct_id}.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    browse = (raw.get("derivedSection") or {}).get("interventionBrowseModule") or {}
    return [
        term
        for term in ((m.get("term") or "").strip() for m in (browse.get("meshes") or []))
        if term
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store", help="path to studies.json")
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    ap.add_argument("--apply", action="store_true", help="write the result back")
    args = ap.parse_args(argv)

    store_path = Path(args.store)
    cache_dir = Path(args.cache_dir)
    if not store_path.exists():
        raise SystemExit(f"no store at {store_path}")
    if not cache_dir.is_dir():
        raise SystemExit(f"no NCT cache at {cache_dir}")

    doc = json.loads(store_path.read_text())
    studies = doc.get("studies")
    if studies is None:
        raise SystemExit("store has no 'studies' key")
    rows = studies if isinstance(studies, list) else list(studies.values())

    filled: list[str] = []
    already: list[str] = []
    uncached: list[str] = []
    empty: list[str] = []

    for study in rows:
        if not isinstance(study, dict):
            continue
        label = f"{study.get('id')} {str(study.get('name') or '')[:34]}"
        nct = (study.get("nctId") or (study.get("trialMetadata") or {}).get("nctId") or "").strip()
        if not nct:
            uncached.append(f"{label}  (no nctId)")
            continue

        metadata = study.setdefault("trialMetadata", {})
        if metadata.get("interventionMeshTerms"):
            already.append(f"{label}  {metadata['interventionMeshTerms']}")
            continue

        terms = mesh_terms_for(nct, cache_dir)
        if terms is None:
            uncached.append(f"{label}  {nct} not in cache")
            continue
        if not terms:
            empty.append(f"{label}  {nct} has no MeSH terms")
            continue

        metadata["interventionMeshTerms"] = terms
        filled.append(f"{label}  {nct} -> {terms}")

    for title, rowset in (("filled", filled), ("already set", already),
                          ("not cached", uncached), ("cached but empty", empty)):
        if rowset:
            print(f"\n## {title} ({len(rowset)})")
            for row in rowset:
                print(f"  {row}")

    if not args.apply:
        print(f"\ndry run: {len(filled)} studies would be filled; re-run with --apply")
        return 0

    if filled:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = store_path.with_name(f"{store_path.stem}.pre-mesh-{stamp}.json")
        shutil.copy2(store_path, backup)
        print(f"\nbackup: {backup}")
        store_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    print(f"written: {len(filled)} studies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
