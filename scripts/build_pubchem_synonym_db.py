#!/usr/bin/env python3
"""Build the offline PubChem synonym -> canonical-title SQLite database.

Why: protocols name drugs by development codes ("BI 10773") that the OMOP
vocabulary does not carry, which makes the concept mapper fall through to
embedding similarity and silently return a wrong-but-plausible concept.
PubChem knows these codes; this script bakes that knowledge into a local file
so the mapper can resolve them with no network at all.

Usage
-----
    .venv/bin/python scripts/build_pubchem_synonym_db.py
    .venv/bin/python scripts/build_pubchem_synonym_db.py --skip-download

Sources (NCBI FTP, no auth, HTTP Range supported so downloads resume):
    CID-Synonym-filtered.gz  CID <TAB> synonym   (one row per synonym)
    CID-Title.gz             CID <TAB> title     (PubChem's preferred name)

Everything is streamed; neither dump is ever held in memory.
"""

from __future__ import annotations

import argparse
import gzip
import os
import resource
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.agent2.drug_name_normalizer import normalize_key  # noqa: E402

BASE_URL = "https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/"
SYNONYM_FILE = "CID-Synonym-filtered.gz"
TITLE_FILE = "CID-Title.gz"

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "pubchem"
DEFAULT_DB_NAME = "pubchem_synonyms.sqlite"

# Synonyms longer than this are IUPAC names, InChI strings and SMILES.  No
# protocol ever writes a drug that way, and they are a large share of the dump,
# so dropping them keeps the index small.  The filter can only cause a miss on
# an absurdly long name, never a wrong answer.  The skipped count is recorded
# in the meta table.
MAX_SYNONYM_LEN = 100

BATCH_SIZE = 100_000
PROGRESS_EVERY = 10_000_000


def _log(message: str) -> None:
    """Progress output is unbuffered so a background build never looks hung."""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def download(url: str, dest: Path) -> None:
    """Fetch ``url`` to ``dest``, resuming a partial file via an HTTP Range request."""
    expected = int(urllib.request.urlopen(urllib.request.Request(url, method="HEAD")).headers["Content-Length"])
    have = dest.stat().st_size if dest.exists() else 0
    if have == expected:
        _log(f"{dest.name}: already complete ({expected:,} bytes)")
        return
    if have > expected:
        _log(f"{dest.name}: local file larger than remote, restarting")
        have = 0

    request = urllib.request.Request(url)
    if have:
        request.add_header("Range", f"bytes={have}-")
        _log(f"{dest.name}: resuming at {have:,} / {expected:,} bytes")
    else:
        _log(f"{dest.name}: downloading {expected:,} bytes")

    started = time.time()
    with urllib.request.urlopen(request) as response, open(dest, "ab" if have else "wb") as handle:
        next_report = have + 100 * 1024 * 1024
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
            have += len(chunk)
            if have >= next_report:
                rate = (have) / max(time.time() - started, 1e-9) / 1024 / 1024
                _log(f"{dest.name}: {have:,} / {expected:,} bytes ({100 * have / expected:.1f}%, {rate:.1f} MB/s)")
                next_report += 100 * 1024 * 1024
    _log(f"{dest.name}: done in {time.time() - started:.0f}s")


def _rows(path: Path):
    """Yield ``(cid, value)`` pairs from a gzipped two-column TSV, streaming.

    Malformed lines are skipped rather than aborting a 40-minute build; the
    dumps are machine-generated but not guaranteed clean UTF-8.
    """
    with gzip.open(path, mode="rt", encoding="utf-8", errors="replace", newline="") as handle:
        for line in handle:
            cid, sep, value = line.partition("\t")
            if not sep:
                continue
            value = value.rstrip("\r\n")
            if not value:
                continue
            try:
                yield int(cid), value
            except ValueError:
                continue


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # Durability is worthless here: the file is a derived artifact and a failed
    # build is simply rerun.  Turning the journal off roughly halves load time.
    conn.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = FILE;
        PRAGMA cache_size = -524288;
        """
    )
    return conn


def load_titles(conn: sqlite3.Connection, path: Path) -> int:
    """Load CID -> title.  ``cid INTEGER PRIMARY KEY`` aliases rowid, so the
    lookup index the reader joins on costs nothing extra."""
    conn.execute("DROP TABLE IF EXISTS title")
    conn.execute("CREATE TABLE title (cid INTEGER PRIMARY KEY, title TEXT NOT NULL)")
    started = time.time()
    total = 0
    batch: list[tuple[int, str]] = []
    for cid, title in _rows(path):
        batch.append((cid, title))
        if len(batch) >= BATCH_SIZE:
            conn.executemany("INSERT OR REPLACE INTO title VALUES (?, ?)", batch)
            total += len(batch)
            batch.clear()
            if total % PROGRESS_EVERY == 0:
                _log(f"titles: {total:,} rows ({total / (time.time() - started):,.0f}/s)")
    if batch:
        conn.executemany("INSERT OR REPLACE INTO title VALUES (?, ?)", batch)
        total += len(batch)
    conn.commit()
    _log(f"titles: {total:,} rows in {time.time() - started:.0f}s")
    return total


def load_synonyms(conn: sqlite3.Connection, path: Path) -> tuple[int, int]:
    """Load synonym -> CID, keyed by the normalized lookup key.

    The raw spelling is kept alongside the key so the reader can report whether
    a hit was exact, case-folded or only punctuation-normalized.
    """
    conn.execute("DROP TABLE IF EXISTS synonym")
    conn.execute("CREATE TABLE synonym (key TEXT NOT NULL, raw TEXT NOT NULL, cid INTEGER NOT NULL)")
    started = time.time()
    total = skipped = 0
    batch: list[tuple[str, str, int]] = []
    for cid, synonym in _rows(path):
        if len(synonym) > MAX_SYNONYM_LEN:
            skipped += 1
            continue
        key = normalize_key(synonym)
        if not key:
            skipped += 1
            continue
        batch.append((key, synonym, cid))
        if len(batch) >= BATCH_SIZE:
            conn.executemany("INSERT INTO synonym VALUES (?, ?, ?)", batch)
            total += len(batch)
            batch.clear()
            if total % PROGRESS_EVERY == 0:
                _log(f"synonyms: {total:,} kept / {skipped:,} skipped ({total / (time.time() - started):,.0f}/s)")
    if batch:
        conn.executemany("INSERT INTO synonym VALUES (?, ?, ?)", batch)
        total += len(batch)
    conn.commit()
    _log(f"synonyms: {total:,} kept / {skipped:,} skipped in {time.time() - started:.0f}s")
    return total, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Where dumps and the DB live")
    parser.add_argument("--skip-download", action="store_true", help="Rebuild from already-downloaded dumps")
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)
    synonym_path = args.data_dir / SYNONYM_FILE
    title_path = args.data_dir / TITLE_FILE
    db_path = args.data_dir / DEFAULT_DB_NAME

    if args.skip_download:
        missing = [p for p in (synonym_path, title_path) if not p.exists()]
        if missing:
            parser.error(f"--skip-download but missing: {', '.join(str(p) for p in missing)}")
    else:
        download(BASE_URL + TITLE_FILE, title_path)
        download(BASE_URL + SYNONYM_FILE, synonym_path)

    started = time.time()
    # Build into a temp name so an interrupted run never leaves a half-built DB
    # that the reader would happily open and answer wrongly from.
    staging = db_path.with_suffix(".sqlite.building")
    staging.unlink(missing_ok=True)
    conn = _connect(staging)
    try:
        title_rows = load_titles(conn, title_path)
        synonym_rows, skipped = load_synonyms(conn, synonym_path)

        _log("building index on synonym(key) ...")
        index_started = time.time()
        conn.execute("CREATE INDEX idx_synonym_key ON synonym(key)")
        conn.commit()
        _log(f"index built in {time.time() - index_started:.0f}s")

        conn.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
        conn.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
                ("source", BASE_URL),
                ("title_rows", str(title_rows)),
                ("synonym_rows", str(synonym_rows)),
                ("synonym_rows_skipped", str(skipped)),
                ("max_synonym_len", str(MAX_SYNONYM_LEN)),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    os.replace(staging, db_path)
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    _log(f"wrote {db_path} ({db_path.stat().st_size / 1024**3:.2f} GiB)")
    _log(f"total build time {time.time() - started:.0f}s, peak RSS {peak_mb:.0f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
