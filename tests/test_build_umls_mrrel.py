"""Behaviour of scripts/build_umls_mrrel.py."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import build_umls_mrrel  # noqa: E402


def _rrf_line(cui1, rel, cui2, rela, sab, suppress="N"):
    # CUI1|AUI1|STYPE1|REL|CUI2|AUI2|STYPE2|RELA|RUI|SRUI|SAB|SL|RG|DIR|SUPPRESS|CVF|
    return f"{cui1}|A1|SCUI|{rel}|{cui2}|A2|SCUI|{rela}|R1||{sab}|{sab}||Y|{suppress}||\n"


def test_should_keep_only_isa_rows_from_listed_sources_when_building(tmp_path):
    rrf = tmp_path / "MRREL.RRF"
    rrf.write_text(
        _rrf_line("C_CLASS", "CHD", "C_DRUG", "isa", "MED-RT")
        + _rrf_line("C_DRUG", "PAR", "C_CLASS", "inverse_isa", "MED-RT")
        + _rrf_line("C_CLASS", "RO", "C_DRUG", "has_mechanism_of_action", "MED-RT")
        + _rrf_line("C_CLASS", "CHD", "C_OTHER", "isa", "MDR")
        + _rrf_line("C_CLASS", "CHD", "C_GONE", "isa", "MED-RT", suppress="O")
    )
    out = tmp_path / "mrrel.sqlite"

    count = build_umls_mrrel.build(str(rrf), str(out))

    rows = sqlite3.connect(out).execute(
        "SELECT cui1, cui2, rela, sab FROM mrrel ORDER BY rela"
    ).fetchall()
    assert count == 2
    assert rows == [
        ("C_DRUG", "C_CLASS", "inverse_isa", "MED-RT"),
        ("C_CLASS", "C_DRUG", "isa", "MED-RT"),
    ]
