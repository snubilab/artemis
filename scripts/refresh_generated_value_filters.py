"""Refresh the six committed ``data/generated/*.circe.json`` fixtures in place.

ADR-031 fixed value-constraint emission in ``src.services.value_constraint``, but
the checked-in fixtures under ``data/generated/`` were built by the old, buggy
builder and never regenerated. Regenerating them the "real" way means rerunning
Agent 1 extraction + Agent 2 concept mapping through the live LLM, which is
unnecessary here: ConceptSets/CodesetId do not change, only the value-filter
fields (``ValueAsNumber`` -> ``RangeHighRatio``/``RangeLowRatio``/sibling
``Unit``) do, and the op/value/unit for every affected criterion was already
extracted correctly by Agent 1 and is on record.

Provenance of ``_UNIT_TEXT_BY_STUDY`` below: each (value, op) pair was read
verbatim from the persisted studies store's
``eligibility.{inclusionCriteria,exclusionCriteria}[*].valueConstraint`` for the
matching study (main checkout ``tmp/tte/studies.json``, ids 8 EMPA-REG, 9
CARMELINA, 10 CAROLINA, read-only, 2026-07-30) — the same extraction that
produced these six files' CodesetIds and ValueAsNumber, just before the
now-fixed builder would have converted it. This script does not invent a unit;
it replays already-extracted IR through the fixed
``build_measurement_value_filter`` so the artifacts match what the fixed code
path would emit today.

Usage: .venv/bin/python scripts/refresh_generated_value_filters.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.services.value_constraint import build_measurement_value_filter

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = REPO_ROOT / "data" / "generated"

# study key (from the file's parent dir name) -> {(value, op): unit_text}
_UNIT_TEXT_BY_STUDY: dict[str, dict[tuple[float, str], str]] = {
    "carmelina": {
        (45.0, "lte"): "kg/m2",
        (6.5, "gte"): "%",
        (10.0, "gte"): "%",
        (15.0, "lt"): "ml/min/1.73 m2",
        (3.0, "gte"): "x ULN",
    },
    "carolina": {
        (45.0, "lte"): "kg/m2",
        (6.5, "gte"): "%",
        (8.5, "gt"): "%",
        (7.5, "gt"): "%",
    },
    "empa_reg": {
        (45.0, "lte"): "kg/m2",
        (7.0, "gte"): "%",
        (10.0, "gte"): "%",
        (30.0, "lt"): "ml/min/1.73 m2",
        (240.0, "gt"): "mg/dL",
        (3.0, "gt"): "x ULN",
    },
}


def _refresh_measurement(node: dict[str, Any], unit_text_by_pair: dict[tuple[float, str], str]) -> bool:
    """Rewrite one Measurement dict's value filter in place. Returns True if changed."""
    van = node.get("ValueAsNumber")
    if not isinstance(van, dict):
        return False
    key = (float(van["Value"]), van["Op"])
    unit_text = unit_text_by_pair.get(key)
    if unit_text is None:
        raise KeyError(
            f"no recorded unit_text for CodesetId={node.get('CodesetId')} value={key}; "
            "refusing to guess a unit (ADR-031 D5)"
        )
    fragment = build_measurement_value_filter({"op": van["Op"], "value": van["Value"], "unitText": unit_text})
    if not fragment:
        raise ValueError(f"build_measurement_value_filter produced nothing for {key} ({unit_text!r})")

    rebuilt: dict[str, Any] = {}
    for field_name, field_value in node.items():
        if field_name == "ValueAsNumber":
            rebuilt.update(fragment)
        else:
            rebuilt[field_name] = field_value
    node.clear()
    node.update(rebuilt)
    return True


def _walk(node: Any, unit_text_by_pair: dict[tuple[float, str], str]) -> int:
    changed = 0
    if isinstance(node, dict):
        if "CodesetId" in node and "ValueAsNumber" in node:
            changed += _refresh_measurement(node, unit_text_by_pair)
        for child in node.values():
            changed += _walk(child, unit_text_by_pair)
    elif isinstance(node, list):
        for child in node:
            changed += _walk(child, unit_text_by_pair)
    return changed


def refresh_file(path: Path) -> int:
    study_key = path.parent.name
    unit_text_by_pair = _UNIT_TEXT_BY_STUDY[study_key]
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = _walk(data, unit_text_by_pair)
    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> None:
    total = 0
    for path in sorted(GENERATED_DIR.rglob("*.circe.json")):
        changed = refresh_file(path)
        print(f"{path.relative_to(REPO_ROOT)}: {changed} criteria updated")
        total += changed
    print(f"total: {total} criteria updated")


if __name__ == "__main__":
    main()
