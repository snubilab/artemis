#!/usr/bin/env python3
"""
Add MRSTY (Semantic Types) table to existing UMLS SQLite database.

Usage:
    python scripts/build_umls_mrsty.py \
        --input data/umls/2025AB/META/MRSTY.RRF \
        --db data/umls/mrconso.sqlite

MRSTY.RRF columns (pipe-delimited):
    CUI|TUI|STN|STY|ATUI|CVF|

This script adds/replaces the `mrsty` table in the existing mrconso.sqlite
database. The mrconso table is NOT modified.
"""

import argparse
import csv
import os
import sqlite3
import sys
import time

csv.field_size_limit(sys.maxsize)

# MRSTY column order (6 fields)
MRSTY_COLS = ["CUI", "TUI", "STN", "STY", "ATUI", "CVF"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Add MRSTY table to existing UMLS SQLite DB"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to MRSTY.RRF file",
    )
    parser.add_argument(
        "--db",
        default="data/umls/mrconso.sqlite",
        help="Path to existing SQLite DB (default: data/umls/mrconso.sqlite)",
    )
    return parser.parse_args()


def create_mrsty_schema(conn: sqlite3.Connection) -> None:
    """Create mrsty table and indexes (drops existing if any)."""
    conn.executescript("""
        DROP TABLE IF EXISTS mrsty;

        CREATE TABLE mrsty (
            cui  TEXT NOT NULL,
            tui  TEXT NOT NULL,
            sty  TEXT NOT NULL
        );

        CREATE INDEX idx_mrsty_cui ON mrsty(cui);
        CREATE INDEX idx_mrsty_tui ON mrsty(tui);
        CREATE INDEX idx_mrsty_sty ON mrsty(sty);
    """)


def load_mrsty(conn: sqlite3.Connection, rrf_path: str) -> int:
    """Parse MRSTY.RRF and insert into SQLite. Returns row count."""
    insert_sql = "INSERT INTO mrsty (cui, tui, sty) VALUES (?, ?, ?)"

    total = 0
    inserted = 0
    start = time.time()

    batch = []
    batch_size = 50_000

    with open(rrf_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="|")
        for row in reader:
            total += 1

            # RRF lines end with trailing pipe → extra empty field
            if len(row) < 4:
                continue

            cui = row[0]   # CUI
            tui = row[1]   # TUI (e.g., T047)
            sty = row[3]   # STY (e.g., "Disease or Syndrome")

            batch.append((cui, tui, sty))
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
    print(f"   Total scanned:  {total:,}")
    print(f"   Inserted:       {inserted:,}")

    return inserted


def print_stats(conn: sqlite3.Connection) -> None:
    """Print summary stats for mrsty table."""
    print(f"\n{'='*60}")
    print("📊 MRSTY Statistics:")

    cur = conn.cursor()

    # Total rows
    cur.execute("SELECT COUNT(*) FROM mrsty")
    total = cur.fetchone()[0]
    print(f"   Total rows:       {total:,}")

    # Unique CUIs
    cur.execute("SELECT COUNT(DISTINCT cui) FROM mrsty")
    cuis = cur.fetchone()[0]
    print(f"   Unique CUIs:      {cuis:,}")

    # Unique TUIs
    cur.execute("SELECT COUNT(DISTINCT tui) FROM mrsty")
    tuis = cur.fetchone()[0]
    print(f"   Unique TUIs:      {tuis:,}")

    # Top semantic types
    print(f"\n   Top 20 Semantic Types:")
    cur.execute("""
        SELECT sty, COUNT(*) as cnt
        FROM mrsty
        GROUP BY sty
        ORDER BY cnt DESC
        LIMIT 20
    """)
    for sty, cnt in cur.fetchall():
        print(f"     {sty:45s} {cnt:>10,}")

    # Verify join with mrconso works
    cur.execute("""
        SELECT COUNT(DISTINCT m.cui)
        FROM mrconso m
        INNER JOIN mrsty s ON m.cui = s.cui
    """)
    joined = cur.fetchone()[0]
    print(f"\n   CUIs in both mrconso+mrsty: {joined:,}")


def main():
    args = parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Input file not found: {args.input}")
        sys.exit(1)

    if not os.path.exists(args.db):
        print(f"❌ Database not found: {args.db}")
        print("   Run build_umls_sqlite.py first to create mrconso.sqlite")
        sys.exit(1)

    file_size = os.path.getsize(args.input) / (1024 ** 2)
    print(f"📥 Input: {args.input} ({file_size:.1f} MB)")
    print(f"📤 Database: {args.db}")
    print(f"{'='*60}")

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-200000")  # 200MB cache

    print("📋 Creating mrsty schema...")
    create_mrsty_schema(conn)

    print("📖 Loading MRSTY.RRF...")
    row_count = load_mrsty(conn, args.input)

    if row_count > 0:
        print_stats(conn)
    else:
        print("⚠️  No rows inserted. Check the input file.")

    conn.close()

    db_size = os.path.getsize(args.db) / (1024 ** 2)
    print(f"\n💾 SQLite size: {db_size:.1f} MB")
    print(f"✅ MRSTY table added to: {args.db}")


if __name__ == "__main__":
    main()
