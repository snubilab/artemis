from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _concept_ids(
    circe: dict[str, Any], comparator: dict[str, Any] | None
) -> set[int]:
    result = {
        int(item["concept"]["CONCEPT_ID"])
        for concept_set in circe.get("ConceptSets", [])
        for item in concept_set.get("expression", {}).get("items", [])
    }
    result.update(
        int(concept_id)
        for candidate in (comparator or {}).get("candidates", [])
        for concept_id in candidate.get(
            "conceptIds", candidate.get("concept_ids", [])
        )
    )
    return result


def main() -> None:
    from src.services.site_cdm_adaptation import (
        compile_site_adaptation,
        load_achilles_snapshot,
        load_vocabulary_descendants,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--circe", type=Path, required=True)
    parser.add_argument("--vocabulary-map", type=Path)
    parser.add_argument("--vocab-schema")
    parser.add_argument("--comparator-artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    snapshot = load_achilles_snapshot(args.snapshot)
    circe = _json(args.circe)
    comparator = (
        _json(args.comparator_artifact) if args.comparator_artifact else None
    )
    if args.vocabulary_map:
        descendants = {
            int(key): {int(value) for value in values}
            for key, values in _json(args.vocabulary_map).items()
        }
    else:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url or not args.vocab_schema:
            parser.error(
                "provide --vocabulary-map or DATABASE_URL with --vocab-schema"
            )
        descendants = load_vocabulary_descendants(
            database_url,
            args.vocab_schema,
            _concept_ids(circe, comparator),
        )

    report = compile_site_adaptation(
        circe,
        snapshot,
        descendants,
        comparator_artifact=comparator,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            report.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
