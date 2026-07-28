#!/usr/bin/env python3
"""Normalize hospital-supplied ACHILLES exports into the standard snapshot ZIP.

Sites do not send `achilles_results` in one shape: we received an xlsx with
(domain, concept_id, count), per-domain CSVs with English headers, and numbered
CSVs with Korean headers. All three carry the same meaning — concept_id and the
distinct person count — so this script maps each into the snapshot contract that
`site_cdm_adaptation.load_achilles_snapshot` reads:

    <site>.zip
    ├── achilles_prevalence.csv   analysis_id,stratum_1,count_value
    └── manifest.json             siteKey, resultsSchema, versions, smallCellCount, analysisIds

Domain is recovered per file from probe concepts (a Condition file contains
common condition concepts, etc.), because the ATLAS "Data Sources" export drops
the analysis_id. Unknown domains and unparsable rows are reported, never guessed.

Usage:
    python3 scripts/normalize_site_achilles.py --input <dir> --output <dir>
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import unicodedata
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

# ACHILLES analysis ids for "persons with at least one X, by concept_id"
DOMAIN_ANALYSIS = {
    "visit": 200,
    "condition": 400,
    "procedure": 600,
    "drug": 700,
    "observation": 800,
    "measurement": 1800,
}

# Concepts that only appear in one domain — used to recover the domain of a file
# whose analysis_id was dropped by the ATLAS export.
DOMAIN_PROBES = {
    "condition": (201826, 320128, 4144111, 201340),
    "visit": (9202, 9201, 9203, 262, 8883, 32693),
    "measurement": (3026361, 3000963, 4146380, 3004410),
    "procedure": (4305317, 4163872, 42537845),
    "observation": (40479411, 37396387, 4051104, 44802448),
}

CONCEPT_HEADERS = ("concept id", "concept_id", "컨셉 아이디", "개념 아이디")
COUNT_HEADERS = ("person count", "count", "환자수", "환자 수")
INGREDIENT_HEADERS = ("ingredient", "재료", "성분")

XLNS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _to_int(value: object) -> int | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _match_header(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    for header in headers:
        low = (header or "").strip().lower()
        if any(candidate in low for candidate in candidates):
            return header
    return None


def _infer_domain(concept_ids: set[int], has_ingredient_column: bool) -> str | None:
    """Recover the domain from probe concepts; an Ingredient column implies drug."""
    hits = Counter()
    for domain, probes in DOMAIN_PROBES.items():
        hits[domain] = sum(1 for probe in probes if probe in concept_ids)
    domain, count = hits.most_common(1)[0]
    if count:
        return domain
    return "drug" if has_ingredient_column else None


def read_csv_file(path: Path) -> tuple[str | None, dict[int, int], list[str]]:
    rows = list(csv.DictReader(io.StringIO(_decode(path.read_bytes()))))
    warnings: list[str] = []
    if not rows:
        return None, {}, [f"{path.name}: empty"]
    headers = list(rows[0].keys())
    concept_key = _match_header(headers, CONCEPT_HEADERS)
    count_key = _match_header(headers, COUNT_HEADERS)
    if not concept_key or not count_key:
        return None, {}, [f"{path.name}: missing concept/count column in {headers}"]

    counts: dict[int, int] = {}
    skipped = 0
    for row in rows:
        concept_id, count = _to_int(row.get(concept_key)), _to_int(row.get(count_key))
        if concept_id is None or count is None or concept_id <= 0:
            skipped += 1
            continue
        counts[concept_id] = max(counts.get(concept_id, 0), count)
    if skipped:
        warnings.append(f"{path.name}: skipped {skipped} unparsable/zero-id rows")

    domain = _infer_domain(set(counts), bool(_match_header(headers, INGREDIENT_HEADERS)))
    if domain is None:
        warnings.append(f"{path.name}: domain could not be inferred — file ignored")
    return domain, counts, warnings


def read_xlsx_file(path: Path) -> tuple[dict[str, dict[int, int]], list[str]]:
    """Read a (domain, concept_id, count) sheet using only the stdlib."""
    domains: dict[str, dict[int, int]] = {}
    warnings: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [
                "".join(node.text or "" for node in item.iter(f"{XLNS}t"))
                for item in root.iter(f"{XLNS}si")
            ]
        sheet_name = next(n for n in names if n.startswith("xl/worksheets/sheet"))
        sheet = ET.fromstring(archive.read(sheet_name))
        rows: list[list[str | None]] = []
        for row in sheet.iter(f"{XLNS}row"):
            values: list[str | None] = []
            for cell in row.iter(f"{XLNS}c"):
                node = cell.find(f"{XLNS}v")
                text = node.text if node is not None else None
                if cell.get("t") == "s" and text is not None:
                    text = shared[int(text)]
                values.append(text)
            rows.append(values)

    if not rows:
        return {}, [f"{path.name}: empty sheet"]
    header = [str(value or "").strip().lower() for value in rows[0]]
    try:
        d_i, c_i, n_i = header.index("domain"), header.index("concept_id"), header.index("count")
    except ValueError:
        return {}, [f"{path.name}: expected domain/concept_id/count columns, got {header}"]

    skipped = 0
    unknown: Counter = Counter()
    for values in rows[1:]:
        if len(values) <= max(d_i, c_i, n_i):
            skipped += 1
            continue
        domain = str(values[d_i] or "").strip().lower()
        concept_id, count = _to_int(values[c_i]), _to_int(values[n_i])
        if concept_id is None or count is None or concept_id <= 0:
            skipped += 1
            continue
        if domain not in DOMAIN_ANALYSIS:
            unknown[domain] += 1
            continue
        bucket = domains.setdefault(domain, {})
        bucket[concept_id] = max(bucket.get(concept_id, 0), count)
    if skipped:
        warnings.append(f"{path.name}: skipped {skipped} unparsable/zero-id rows")
    for domain, n in unknown.items():
        warnings.append(f"{path.name}: dropped {n} rows in unsupported domain '{domain}'")
    return domains, warnings


def collect_site(source: Path) -> tuple[dict[str, dict[int, int]], list[str]]:
    """Read one site's export (a directory of CSVs, or a single xlsx)."""
    if source.is_file() and source.suffix.lower() == ".xlsx":
        return read_xlsx_file(source)

    domains: dict[str, dict[int, int]] = {}
    warnings: list[str] = []
    for path in sorted(p for p in source.iterdir() if p.suffix.lower() == ".csv"):
        domain, counts, file_warnings = read_csv_file(path)
        warnings.extend(file_warnings)
        if domain is None:
            continue
        bucket = domains.setdefault(domain, {})
        for concept_id, count in counts.items():
            bucket[concept_id] = max(bucket.get(concept_id, 0), count)
    return domains, warnings


def write_snapshot(
    out_zip: Path,
    site_key: str,
    domains: dict[str, dict[int, int]],
    *,
    run_date: str,
    small_cell_count: int,
    cdm_version: str,
    vocabulary_version: str,
    achilles_version: str,
) -> int:
    """Write the snapshot ZIP. analysisIds always lists all six required ids,
    even when a site supplied no rows for a domain — the loader validates the
    contract, and an absent domain is legitimately an empty set of rows."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["analysis_id", "stratum_1", "count_value"])
    total = 0
    for domain in sorted(domains, key=lambda d: DOMAIN_ANALYSIS[d]):
        analysis_id = DOMAIN_ANALYSIS[domain]
        for concept_id in sorted(domains[domain]):
            writer.writerow([analysis_id, concept_id, domains[domain][concept_id]])
            total += 1

    manifest = {
        "siteKey": site_key,
        "resultsSchema": f"{site_key}_results",
        "cdmVersion": cdm_version,
        "vocabularyVersion": vocabulary_version,
        "achillesVersion": achilles_version,
        "achillesRunDate": run_date,
        "smallCellCount": small_cell_count,
        "analysisIds": sorted(DOMAIN_ANALYSIS.values()),
    }
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("achilles_prevalence.csv", buffer.getvalue())
        archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
    return total


SITE_KEYS = {"아주대": "ajou", "계명대": "keimyung", "동아대": "donga"}


def site_key_for(name: str) -> str:
    # Korean filenames often arrive NFD-decomposed (macOS), where "계명대" does not
    # substring-match its NFC form — normalize before comparing.
    normalized = unicodedata.normalize("NFC", name)
    for korean, latin in SITE_KEYS.items():
        if korean in normalized:
            return latin
    return "".join(ch for ch in normalized.lower() if ch.isalnum()) or "site"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-date", default=date.today().isoformat(),
                        help="ACHILLES run date reported by the site")
    parser.add_argument("--small-cell-count", type=int, default=0,
                        help="site suppression threshold; 0 = not applied/unknown")
    parser.add_argument("--cdm-version", default="unknown")
    parser.add_argument("--vocabulary-version", default="unknown")
    parser.add_argument("--achilles-version", default="unknown")
    args = parser.parse_args()

    sources = [p for p in sorted(args.input.iterdir())
               if p.is_dir() or p.suffix.lower() == ".xlsx"]
    if not sources:
        raise SystemExit(f"no site exports found under {args.input}")

    for source in sources:
        site_key = site_key_for(source.stem if source.is_file() else source.name)
        domains, warnings = collect_site(source)
        if not domains:
            print(f"[{site_key}] no usable rows — skipped")
            for warning in warnings:
                print(f"    ! {warning}")
            continue
        out_zip = args.output / f"{site_key}.zip"
        rows = write_snapshot(
            out_zip, site_key, domains,
            run_date=args.run_date,
            small_cell_count=args.small_cell_count,
            cdm_version=args.cdm_version,
            vocabulary_version=args.vocabulary_version,
            achilles_version=args.achilles_version,
        )
        summary = " ".join(f"{d}={len(c):,}" for d, c in sorted(domains.items()))
        print(f"[{site_key}] {rows:,} rows -> {out_zip}")
        print(f"    {summary}")
        for warning in warnings:
            print(f"    ! {warning}")


if __name__ == "__main__":
    main()
