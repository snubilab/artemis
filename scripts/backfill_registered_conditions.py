"""Backfill ``trialMetadata.conditions`` into an existing TTE store.

Why this exists
---------------
The disease entry anchor is chosen against the trial's own registered condition --
the strings ClinicalTrials.gov carries under
``protocolSection.conditionsModule.conditions`` (``["Diabetes", "Diabetes Mellitus,
Type 2"]`` for LEADER). ``TTEService._fetch_nct_trial_metadata`` now persists them at
ingest; every store written before that carries no ``conditions`` key at all, so
``src.utils.disease_anchor.select_disease_anchor`` has nothing to choose against and
refuses rather than guessing.

The values are read from the local NCT cache (``data/nct_cache/<NCT>.json``), which is
the same payload the importer reads and is a verbatim copy of the registry response --
verified against a live fetch for the six benchmark trials on 2026-09-06. A trial with
no cache entry is reported, never guessed at, and ``--fetch`` is available when the
cache is cold and the host has network.

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
API_URL = "https://clinicaltrials.gov/api/v2/studies/{nct}"


def _conditions_of(payload: dict) -> list[str]:
    module = (payload.get("protocolSection") or {}).get("conditionsModule") or {}
    return [c for c in ((x or "").strip() for x in module.get("conditions") or []) if c]


def conditions_for(nct_id: str, cache_dir: Path, *, fetch: bool) -> list[str] | None:
    """Registered conditions for one trial, from the local cache or the registry.

    :param nct_id: the trial registry id, e.g. ``NCT01179048``.
    :param cache_dir: directory holding ``<NCT>.json`` payloads.
    :param fetch: when the trial is not cached, ask ClinicalTrials.gov directly.
    :returns: the condition strings, or None when the trial could not be read.
    """
    path = cache_dir / f"{nct_id}.json"
    if path.exists():
        return _conditions_of(json.loads(path.read_text()))
    if not fetch:
        return None
    import requests

    response = requests.get(
        API_URL.format(nct=nct_id),
        params={"fields": "protocolSection.conditionsModule"},
        timeout=30,
    )
    response.raise_for_status()
    return _conditions_of(response.json())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("store", help="path to studies.json")
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    ap.add_argument(
        "--fetch",
        action="store_true",
        help="ask ClinicalTrials.gov for trials the local cache does not hold",
    )
    ap.add_argument("--apply", action="store_true", help="write the result back")
    args = ap.parse_args(argv)

    store_path = Path(args.store)
    cache_dir = Path(args.cache_dir)
    if not store_path.exists():
        raise SystemExit(f"no store at {store_path}")
    if not cache_dir.is_dir() and not args.fetch:
        raise SystemExit(f"no NCT cache at {cache_dir} (pass --fetch to ask the registry)")

    doc = json.loads(store_path.read_text())
    studies = doc.get("studies")
    if studies is None:
        raise SystemExit("store has no 'studies' key")
    rows = studies if isinstance(studies, list) else list(studies.values())

    filled: list[str] = []
    already: list[str] = []
    unreadable: list[str] = []
    empty: list[str] = []

    for study in rows:
        if not isinstance(study, dict):
            continue
        label = f"{study.get('id')} {str(study.get('name') or '')[:34]}"
        nct = (study.get("nctId") or (study.get("trialMetadata") or {}).get("nctId") or "").strip()
        if not nct:
            unreadable.append(f"{label}  (no nctId)")
            continue

        metadata = study.setdefault("trialMetadata", {})
        if metadata.get("conditions"):
            already.append(f"{label}  {metadata['conditions']}")
            continue

        conditions = conditions_for(nct, cache_dir, fetch=args.fetch)
        if conditions is None:
            unreadable.append(f"{label}  {nct} not in cache (pass --fetch)")
            continue
        if not conditions:
            empty.append(f"{label}  {nct} registers no condition")
            continue

        metadata["conditions"] = conditions
        filled.append(f"{label}  {nct} -> {conditions}")

    for title, rowset in (
        ("filled", filled),
        ("already set", already),
        ("not readable", unreadable),
        ("registers nothing", empty),
    ):
        if rowset:
            print(f"\n## {title} ({len(rowset)})")
            for row in rowset:
                print(f"  {row}")

    if not args.apply:
        print(f"\ndry run: {len(filled)} studies would be filled; re-run with --apply")
        return 0

    if filled:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = store_path.with_name(f"{store_path.stem}.pre-conditions-{stamp}.json")
        shutil.copy2(store_path, backup)
        print(f"\nbackup: {backup}")
        store_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    print(f"written: {len(filled)} studies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
