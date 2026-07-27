from __future__ import annotations

import argparse
import csv
import json
import zipfile
from pathlib import Path

ANALYSIS_IDS = [200, 400, 600, 700, 800, 1800]
DPP4_INGREDIENT = 1580747
DPP4_PRODUCT = 747300
SULFONYLUREA_INGREDIENT = 1597756
SULFONYLUREA_PRODUCT = 1597758
T2DM = 201826
T2DM_SUBTYPES = [
    37016354,
    4226121,
    43530656,
    43530685,
    45757499,
    45763582,
    45769905,
    45770830,
]
UACR = 3001802
LIFESTYLE_CONCEPTS = {
    3044370,
    4027003,
    4036784,
    4058149,
    604229,
    4026921,
    4038720,
    4058141,
}


def _read_rows(path: Path) -> dict[tuple[int, int], int]:
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["analysis_id", "stratum_1", "count_value"]:
            raise ValueError("source CSV has an invalid header")
        rows = {
            (int(row["analysis_id"]), int(row["stratum_1"])): int(
                row["count_value"]
            )
            for row in reader
        }
    if len(rows) != 1212 or any(value <= 0 for value in rows.values()):
        raise ValueError("expected 1,212 positive Synthea ACHILLES rows")
    return rows


def _csv_bytes(rows: dict[tuple[int, int], int]) -> bytes:
    lines = ["analysis_id,stratum_1,count_value"]
    lines.extend(
        f"{analysis_id},{concept_id},{count}"
        for (analysis_id, concept_id), count in sorted(rows.items())
    )
    return ("\n".join(lines) + "\n").encode()


def _write_zip(
    path: Path,
    site_key: str,
    rows: dict[tuple[int, int], int],
) -> None:
    manifest = {
        "siteKey": site_key,
        "resultsSchema": f"{site_key}_results",
        "cdmVersion": "5.4",
        "vocabularyVersion": "2026-06-30",
        "achillesVersion": "1.7.2",
        "achillesRunDate": "2026-07-24",
        "smallCellCount": 0,
        "analysisIds": ANALYSIS_IDS,
    }
    members = {
        "achilles_prevalence.csv": _csv_bytes(rows),
        "manifest.json": (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode(),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 7, 24, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)


def build_fixtures(source_csv: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = _read_rows(source_csv)

    hospital_a = {
        key: value
        for key, value in base.items()
        if key[1] not in LIFESTYLE_CONCEPTS
    }
    hospital_a[(700, DPP4_PRODUCT)] = 120

    hospital_b = {
        key: value
        for key, value in base.items()
        if key not in {(400, T2DM), (1800, UACR)}
    }

    hospital_c = {
        key: value
        for key, value in base.items()
        if key[1] not in {DPP4_INGREDIENT, DPP4_PRODUCT}
    }
    hospital_c[(700, SULFONYLUREA_PRODUCT)] = 90

    _write_zip(output_dir / "hospital_a.zip", "hospital_a", hospital_a)
    _write_zip(output_dir / "hospital_b.zip", "hospital_b", hospital_b)
    _write_zip(output_dir / "hospital_c.zip", "hospital_c", hospital_c)

    vocabulary_map = {
        1127433: [1127433],
        T2DM: [T2DM, *T2DM_SUBTYPES],
        UACR: [UACR],
        3044370: [3044370],
        DPP4_INGREDIENT: [DPP4_INGREDIENT, DPP4_PRODUCT],
        SULFONYLUREA_INGREDIENT: [
            SULFONYLUREA_INGREDIENT,
            SULFONYLUREA_PRODUCT,
        ],
    }
    comparator = {
        "candidates": [
            {
                "name": "DPP-4 inhibitor",
                "conceptIds": [DPP4_INGREDIENT],
            },
            {
                "name": "Sulfonylurea",
                "conceptIds": [SULFONYLUREA_INGREDIENT],
            },
        ]
    }
    circe = {
        "ConceptSets": [
            _concept_set(1, "entry drug", 1127433),
            _concept_set(2, "Type 2 diabetes", T2DM, True),
            _concept_set(3, "UACR", UACR),
            _concept_set(4, "dietary intervention", 3044370),
        ],
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugExposure": {"CodesetId": 1}}]
        },
        "InclusionRules": [
            _rule("Type 2 diabetes", "ConditionOccurrence", 2),
            _rule("UACR", "Measurement", 3, value=True),
            _rule("dietary intervention", "Observation", 4),
        ],
    }
    (output_dir / "vocabulary_map.json").write_text(
        json.dumps(vocabulary_map, sort_keys=True, indent=2) + "\n"
    )
    (output_dir / "comparator_candidates.json").write_text(
        json.dumps(comparator, sort_keys=True, indent=2) + "\n"
    )
    (output_dir / "circe.json").write_text(
        json.dumps(circe, sort_keys=True, indent=2) + "\n"
    )


def _concept_set(
    codeset_id: int,
    name: str,
    concept_id: int,
    include_descendants: bool = False,
) -> dict[str, object]:
    return {
        "id": codeset_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {"CONCEPT_ID": concept_id},
                    "includeDescendants": include_descendants,
                    "isExcluded": False,
                }
            ]
        },
    }


def _rule(
    name: str,
    domain: str,
    codeset_id: int,
    *,
    value: bool = False,
) -> dict[str, object]:
    body: dict[str, object] = {"CodesetId": codeset_id}
    if value:
        body["ValueAsNumber"] = {"Op": "gte", "Value": 30}
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {
                    "Criteria": {domain: body},
                    "Occurrence": {"Type": 2, "Count": 1},
                    "StartWindow": {
                        "Start": {"Days": 365, "Coeff": -1},
                        "End": {"Days": 0, "Coeff": 1},
                    },
                }
            ],
            "Groups": [],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-csv",
        type=Path,
        default=Path("tests/fixtures/site_adaptation/synthea_achilles_prevalence.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/fixtures/site_adaptation"),
    )
    args = parser.parse_args()
    build_fixtures(args.source_csv, args.output_dir)


if __name__ == "__main__":
    main()
