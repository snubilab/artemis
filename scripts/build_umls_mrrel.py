#!/usr/bin/env python3
"""
Build data/umls/mrrel.sqlite from UMLS MRREL.RRF.

Usage:
    python scripts/build_umls_mrrel.py \
        --input /path/to/META/MRREL.RRF \
        --output data/umls/mrrel.sqlite

MRREL.RRF columns (pipe-delimited):
    CUI1|AUI1|STYPE1|REL|CUI2|AUI2|STYPE2|RELA|RUI|SRUI|SAB|SL|RG|DIR|SUPPRESS|CVF|

The only reader is `drug_class_expander.expand_drug_class_via_umls`, which asks for
`isa` / `inverse_isa` rows by CUI. We keep exactly those rows, non-suppressed, from the
sources the 2026-03-13 build used (docs/daily_notes/2026-03-13_umls_mrrel_drug_class.md).
"""

import argparse
import csv
import os
import sqlite3
import sys

csv.field_size_limit(sys.maxsize)

SOURCES = {"MED-RT", "MSH", "NCI", "SNOMEDCT_US", "RXNORM"}
RELAS = {"isa", "inverse_isa"}


def build(rrf_path: str, out_path: str) -> int:
    """Write the mrrel table to out_path (replacing it). Returns rows inserted."""
    if os.path.exists(out_path):
        os.remove(out_path)
    conn = sqlite3.connect(out_path)
    conn.execute(
        "CREATE TABLE mrrel (cui1 TEXT NOT NULL, rel TEXT, cui2 TEXT NOT NULL,"
        " rela TEXT NOT NULL, sab TEXT NOT NULL)"
    )
    inserted = 0
    batch = []
    with open(rrf_path, encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="|", quoting=csv.QUOTE_NONE):
            cui1, rel, cui2, rela, sab, suppress = row[0], row[3], row[4], row[7], row[10], row[14]
            if rela not in RELAS or sab not in SOURCES or suppress == "O":
                continue
            batch.append((cui1, rel, cui2, rela, sab))
            if len(batch) >= 50_000:
                conn.executemany("INSERT INTO mrrel VALUES (?,?,?,?,?)", batch)
                inserted += len(batch)
                batch.clear()
    conn.executemany("INSERT INTO mrrel VALUES (?,?,?,?,?)", batch)
    inserted += len(batch)
    conn.execute("CREATE INDEX idx_mrrel_cui1_rela ON mrrel(cui1, rela)")
    conn.execute("CREATE INDEX idx_mrrel_cui2_rela ON mrrel(cui2, rela)")
    conn.commit()
    conn.close()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Build mrrel.sqlite from MRREL.RRF")
    parser.add_argument("--input", "-i", required=True, help="Path to MRREL.RRF")
    parser.add_argument("--output", "-o", default="data/umls/mrrel.sqlite")
    args = parser.parse_args()
    if not os.path.exists(args.input):
        sys.exit(f"Input file not found: {args.input}")
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    n = build(args.input, args.output)
    if n == 0:
        sys.exit("No isa/inverse_isa rows inserted — check the input file and SOURCES.")
    print(f"{n:,} rows -> {args.output}")


if __name__ == "__main__":
    main()
