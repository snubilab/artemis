#!/usr/bin/env python3
"""
Build a local SQLite database from UMLS MRCONSO.RRF.

Usage:
    python scripts/build_umls_sqlite.py \
        --input /path/to/MRCONSO.RRF \
        --output data/umls/mrconso.sqlite

MRCONSO.RRF columns (pipe-delimited):
    CUI|LAT|TS|LUI|STT|SUI|ISPREF|AUI|SAUI|SCUI|SDUI|SAB|TTY|CODE|STR|SRL|SUPPRESS|CVF|

We keep only English (LAT='ENG'), non-suppressed (SUPPRESS != 'O') rows.
Indexes on CUI, STR (case-insensitive), and SAB+CODE for fast lookups.
"""

import argparse
import csv
import os
import sqlite3
import sys

# MRCONSO has some very long STR fields (>131072 chars)
csv.field_size_limit(sys.maxsize)
import time

# MRCONSO column order (18 fields)
MRCONSO_COLS = [
    "CUI", "LAT", "TS", "LUI", "STT", "SUI", "ISPREF",
    "AUI", "SAUI", "SCUI", "SDUI", "SAB", "TTY", "CODE",
    "STR", "SRL", "SUPPRESS", "CVF",
]

# Vocabularies most relevant to OHDSI/OMOP mapping
RELEVANT_SABS = {
    "SNOMEDCT_US", "LNC",  # LOINC
    "RXNORM", "ATC", "NCI",
    "ICD10CM", "ICD10PCS", "ICD9CM",
    "CPT", "HCPCS",
    "NDFRT",  # Drug classifications
    "MSH",  # MeSH (useful for clinical terms)
    "CHV",  # Consumer Health Vocabulary (lay synonyms)
    "MEDLINEPLUS",
    "HPO",  # Human Phenotype Ontology
}


def parse_args():
    parser = argparse.ArgumentParser(description="Build SQLite from MRCONSO.RRF")
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to MRCONSO.RRF file",
    )
    parser.add_argument(
        "--output", "-o",
        default="data/umls/mrconso.sqlite",
        help="Path for output SQLite file (default: data/umls/mrconso.sqlite)",
    )
    parser.add_argument(
        "--all-vocabs",
        action="store_true",
        help="Include ALL vocabularies (not just OHDSI-relevant ones)",
    )
    return parser.parse_args()


def create_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes."""
    conn.executescript("""
        DROP TABLE IF EXISTS mrconso;
        
        CREATE TABLE mrconso (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            cui     TEXT NOT NULL,
            lat     TEXT NOT NULL,
            ts      TEXT,
            lui     TEXT,
            stt     TEXT,
            sui     TEXT,
            ispref  TEXT,
            aui     TEXT,
            saui    TEXT,
            scui    TEXT,
            sdui    TEXT,
            sab     TEXT NOT NULL,
            tty     TEXT,
            code    TEXT,
            str     TEXT NOT NULL,
            srl     TEXT,
            suppress TEXT,
            cvf     TEXT
        );
        
        -- Lookup: CUI → all synonyms
        CREATE INDEX idx_cui ON mrconso(cui);
        
        -- Lookup: exact string match (case-insensitive via COLLATE NOCASE)
        CREATE INDEX idx_str ON mrconso(str COLLATE NOCASE);
        
        -- Lookup: vocabulary + code (e.g. LOINC + code)
        CREATE INDEX idx_sab_code ON mrconso(sab, code);
        
        -- Lookup: vocabulary filter
        CREATE INDEX idx_sab ON mrconso(sab);
        
        -- Lookup: preferred terms only
        CREATE INDEX idx_cui_ispref ON mrconso(cui, ispref);
    """)


def load_rrf(conn: sqlite3.Connection, rrf_path: str, all_vocabs: bool) -> int:
    """Parse MRCONSO.RRF and insert into SQLite. Returns row count."""
    insert_sql = f"""
        INSERT INTO mrconso (
            cui, lat, ts, lui, stt, sui, ispref,
            aui, saui, scui, sdui, sab, tty, code,
            str, srl, suppress, cvf
        ) VALUES ({','.join(['?'] * 18)})
    """

    total = 0
    inserted = 0
    skipped_lang = 0
    skipped_suppress = 0
    skipped_vocab = 0
    start = time.time()

    batch = []
    batch_size = 50_000

    with open(rrf_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="|")
        for row in reader:
            total += 1

            # RRF lines end with a trailing pipe → extra empty field
            if len(row) > 18:
                row = row[:18]
            elif len(row) < 18:
                # Pad short rows
                row.extend([""] * (18 - len(row)))

            lat = row[1]      # Language
            sab = row[11]     # Source abbreviation
            suppress = row[16]  # Suppress flag

            # Filter: English only
            if lat != "ENG":
                skipped_lang += 1
                continue

            # Filter: Non-suppressed
            if suppress == "O":
                skipped_suppress += 1
                continue

            # Filter: Relevant vocabularies only (unless --all-vocabs)
            if not all_vocabs and sab not in RELEVANT_SABS:
                skipped_vocab += 1
                continue

            batch.append(tuple(row))
            inserted += 1

            if len(batch) >= batch_size:
                conn.executemany(insert_sql, batch)
                batch.clear()
                elapsed = time.time() - start
                rate = inserted / elapsed if elapsed > 0 else 0
                print(
                    f"  ... {inserted:,} rows inserted "
                    f"({total:,} scanned, {rate:,.0f} rows/sec)",
                    end="\r",
                )

    # Final batch
    if batch:
        conn.executemany(insert_sql, batch)

    conn.commit()

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"✅ Done in {elapsed:.1f}s")
    print(f"   Total scanned:      {total:,}")
    print(f"   Inserted:           {inserted:,}")
    print(f"   Skipped (non-ENG):  {skipped_lang:,}")
    print(f"   Skipped (suppress): {skipped_suppress:,}")
    print(f"   Skipped (vocab):    {skipped_vocab:,}")

    return inserted


def print_stats(conn: sqlite3.Connection) -> None:
    """Print summary stats."""
    print(f"\n{'='*60}")
    print("📊 Database Statistics:")

    cur = conn.cursor()

    # Total rows
    cur.execute("SELECT COUNT(*) FROM mrconso")
    total = cur.fetchone()[0]
    print(f"   Total rows:    {total:,}")

    # Unique CUIs
    cur.execute("SELECT COUNT(DISTINCT cui) FROM mrconso")
    cuis = cur.fetchone()[0]
    print(f"   Unique CUIs:   {cuis:,}")

    # Unique strings
    cur.execute("SELECT COUNT(DISTINCT str) FROM mrconso")
    strs = cur.fetchone()[0]
    print(f"   Unique STRs:   {strs:,}")

    # By vocabulary
    print(f"\n   Rows by vocabulary (top 15):")
    cur.execute("""
        SELECT sab, COUNT(*) as cnt
        FROM mrconso
        GROUP BY sab
        ORDER BY cnt DESC
        LIMIT 15
    """)
    for sab, cnt in cur.fetchall():
        print(f"     {sab:20s} {cnt:>10,}")

    # Average synonyms per CUI
    cur.execute("""
        SELECT AVG(cnt) FROM (
            SELECT COUNT(*) as cnt FROM mrconso GROUP BY cui
        )
    """)
    avg = cur.fetchone()[0]
    print(f"\n   Avg synonyms/CUI: {avg:.1f}")


def main():
    args = parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Input file not found: {args.input}")
        sys.exit(1)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    # Remove existing DB
    if os.path.exists(args.output):
        print(f"⚠️  Removing existing DB: {args.output}")
        os.remove(args.output)

    file_size = os.path.getsize(args.input) / (1024 ** 3)
    print(f"📥 Input: {args.input} ({file_size:.2f} GB)")
    print(f"📤 Output: {args.output}")
    if args.all_vocabs:
        print(f"📚 Including ALL vocabularies")
    else:
        print(f"📚 Filtering to {len(RELEVANT_SABS)} OHDSI-relevant vocabularies")
    print(f"{'='*60}")

    conn = sqlite3.connect(args.output)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-200000")  # 200MB cache

    print("📋 Creating schema...")
    create_schema(conn)

    print("📖 Loading MRCONSO.RRF...")
    row_count = load_rrf(conn, args.input, args.all_vocabs)

    if row_count > 0:
        print_stats(conn)
    else:
        print("⚠️  No rows inserted. Check your filters.")

    conn.close()

    db_size = os.path.getsize(args.output) / (1024 ** 2)
    print(f"\n💾 SQLite size: {db_size:.1f} MB")
    print(f"✅ UMLS SQLite DB ready: {args.output}")


if __name__ == "__main__":
    main()
