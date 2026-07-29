#!/usr/bin/env python3
"""A/B the ADR-031 value-constraint fix across the six canonical Gold trials.

Two factors sit on two different stages, which is what makes this cheap:

    model  ->  process_eligibility()          (LLM: extract criteria + valueConstraint)
    arm    ->  _build_seeded_target_circe()   (code: valueConstraint -> Circe fragment)

So the extraction runs once per (model, study) and both arms are assembled on top
of that one criterion list. Running it twice would make the arms differ by
extraction noise, which is not the thing under test. Assembly itself still calls
Agent2 concept mapping, so results are model-dependent even without --extract.

The ``legacy`` arm is a faithful reproduction of ``_build_value_constraint`` as it
stood at 5379743 — the last commit before ``src/services/value_constraint.py``
existed. It is reproduced here rather than checked out as a worktree because that
snapshot also predates the model-routing and reasoning-preprocessing fixes, so a
snapshot arm cannot run a local model at all. Those are instrument defects, not the
intervention; mixing them in would attribute the instrument's failures to the arm.

Usage (inside the artemis-api container, which has torch/chromadb/Neo4j):

    python scripts/benchmark_value_constraint_arms.py --model vllm/Qwen/Qwen3.5-4B
    python scripts/benchmark_value_constraint_arms.py --report
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

ARTEMIS_DIR = Path(__file__).resolve().parents[1]
if str(ARTEMIS_DIR) not in sys.path:
    sys.path.insert(0, str(ARTEMIS_DIR))

DEFAULT_OUTPUT_ROOT = ARTEMIS_DIR / "output" / "value_constraint_arms"
GOLD_ROOT = ARTEMIS_DIR / "data" / "gold"

# study_id in tmp/tte/studies.json -> gold directory name
STUDIES: dict[int, str] = {
    1: "LEADER",
    2: "PLATO",
    3: "ARISTOTLE",
    8: "EMPA-REG OUTCOME",
    9: "CARMELINA",
    10: "CAROLINA",
}

ARMS = ("adr031", "legacy")

# Phrases that make a ratio bound correct. Kept deliberately literal: a criterion
# is only scored when its text says the threshold is relative to a reference range,
# because that is the only case where the two arms are allowed to disagree.
_ULN = re.compile(r"\b(?:x|times|×)\s*(?:the\s+)?(?:upper\s+limit|uln)\b|\buln\b", re.I)
_LLN = re.compile(r"\b(?:x|times|×)\s*(?:the\s+)?(?:lower\s+limit|lln)\b|\blln\b", re.I)

# ---------------------------------------------------------------------------
# legacy arm — verbatim behaviour of assembler._build_value_constraint @ 5379743
# ---------------------------------------------------------------------------

# UNIT_MAP as it stood at 5379743. "mg" is 8587 here, which is millilitre; the
# correction to 8576 rode along inside the intervention commit (25c53ac), so a
# faithful legacy arm keeps the wrong concept. It only matters for a mg-unit
# threshold, and reproducing it is cheaper than arguing about which half of a
# commit counts as the intervention.
_LEGACY_UNIT_MAP = {
    "%": 8554,
    "mg/dL": 8840,
    "mmol/L": 8753,
    "kg": 9529,
    "kg/m2": 9531,
    "mmHg": 8876,
    "year": 9448,
    "day": 8512,
    "mg": 8587,
}

_LEGACY_OPERATOR_MAP = {
    "lt": "lt", "gt": "gt", "eq": "eq", "lte": "lte",
    "gte": "gte", "neq": "neq", "bt": "bt", "nbt": "!bt",
}


def _get(vc: Any, *names: str) -> Any:
    for name in names:
        if isinstance(vc, dict):
            if name in vc:
                return vc[name]
        elif hasattr(vc, name):
            return getattr(vc, name)
    return None


def legacy_value_filter(vc: Any) -> dict[str, Any]:
    """Pre-ADR-031 shape: always ValueAsNumber, Unit nested inside it.

    "ALT > 3x ULN" arrives with value 3.0 and the bound parked in unit_text, so
    this emits ValueAsNumber {Value: 3.0, Op: gt} — an absolute 3 U/L, which
    every patient exceeds. That is defect #10, reproduced on purpose.
    """
    if vc is None:
        return {}
    value = _get(vc, "value", "Value")
    op = _get(vc, "op", "Op")
    if value is None or op is None:
        return {}
    result: dict[str, Any] = {
        "Value": value,
        "Op": _LEGACY_OPERATOR_MAP.get(str(op).lower(), "gt"),
    }
    unit_text = _get(vc, "unit_text", "unitText")
    if unit_text and unit_text in _LEGACY_UNIT_MAP:
        result["Unit"] = _LEGACY_UNIT_MAP[unit_text]
    return {"ValueAsNumber": result}


def install_arm(arm: str) -> None:
    """Swap the value-filter at its import sites.

    assembler and tte_service both did ``from ... import build_measurement_value_filter``,
    so the name is bound in their module namespaces; rebinding the source module
    alone would leave both callers on the original.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    import src.agents.agent3.assembler as assembler
    import src.services.tte_service as tte_service
    from src.services.value_constraint import build_measurement_value_filter

    impl = build_measurement_value_filter if arm == "adr031" else legacy_value_filter
    for module in (assembler, tte_service):
        if hasattr(module, "build_measurement_value_filter"):
            module.build_measurement_value_filter = impl


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

VALUE_KEYS = ("RangeHighRatio", "RangeLowRatio", "ValueAsNumber")


def walk_dicts(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_dicts(value)


def count_value_keys(circe: Any) -> dict[str, int]:
    counts = {key: 0 for key in VALUE_KEYS}
    counts["Unit"] = 0
    for node in walk_dicts(circe):
        for key in counts:
            if key in node:
                counts[key] += 1
    return counts


def iter_criteria(eligibility: dict[str, Any]):
    """Both criteria lists. There is no combined "criteria" key on a stored study."""
    for key in ("inclusionCriteria", "exclusionCriteria"):
        for criterion in eligibility.get(key) or []:
            if isinstance(criterion, dict):
                yield criterion


def expected_bound(text: str) -> str | None:
    """What the criterion text says the threshold is relative to."""
    if not text:
        return None
    if _ULN.search(text):
        return "uln"
    if _LLN.search(text):
        return "lln"
    return None


def score_criteria(eligibility: dict[str, Any], circe: Any) -> dict[str, Any]:
    """Per-criterion verdict for the criteria where the arms may legitimately differ.

    Only criteria whose own text names a reference-range bound are scored. An
    absolute threshold ("HbA1c > 7%") is correct as ValueAsNumber in both arms and
    would dilute the contrast without carrying information.
    """
    ratio_texts = []
    for criterion in iter_criteria(eligibility):
        text = " ".join(
            str(criterion.get(field) or "")
            for field in ("sourceText", "description")
        ).strip()
        # The bound lives in the constraint, not the prose. Stored criteria predate
        # ADR-031's reference_bound field and park it in unitText as "x ULN"; all 34
        # constraints across the six studies have reference_bound=None, so reading
        # only sourceText reports zero reference bounds for EMPA-REG and CARMELINA,
        # which are the two studies that actually carry them.
        constraint = criterion.get("valueConstraint") or {}
        unit_text = constraint.get("unitText") or constraint.get("unit_text") or ""
        declared = constraint.get("referenceBound") or constraint.get("reference_bound")
        bound = (
            (declared if declared in ("uln", "lln") else None)
            or expected_bound(unit_text)
            or expected_bound(text)
        )
        if bound:
            ratio_texts.append(
                {"text": text[:120], "unit_text": unit_text, "expected": bound}
            )

    counts = count_value_keys(circe)
    emitted_ratio = counts["RangeHighRatio"] + counts["RangeLowRatio"]
    return {
        "criteria_naming_a_reference_bound": len(ratio_texts),
        "ratio_fragments_emitted": emitted_ratio,
        "value_as_number_emitted": counts["ValueAsNumber"],
        "unit_emitted": counts["Unit"],
        "examples": ratio_texts[:5],
    }


def gold_counts(study_name: str) -> dict[str, int]:
    directory = GOLD_ROOT / study_name
    counts = {key: 0 for key in VALUE_KEYS}
    counts["Unit"] = 0
    if not directory.is_dir():
        return counts
    for path in sorted(directory.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for key, value in count_value_keys(doc).items():
            counts[key] += value
    return counts


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

PROVENANCE_KEYS = ("LLM_MODEL", "VLLM_BASE_URL", "EMBEDDING_MODEL", "AGENT2_CRITIC_MODEL_TIER")


def provenance() -> dict[str, str | None]:
    return {key.lower(): os.environ.get(key) for key in PROVENANCE_KEYS}


def isolate_store(model: str) -> Path:
    """Point TTE_STORE_PATH at a per-model copy, before TTEService is imported.

    process_eligibility() rewrites the study it runs on. The default store is the
    one the live service serves from and holds real run history, so a benchmark
    that used it would overwrite six real studies with per-model output and leave
    nothing to compare against. Copying is not optional and not a flag: a flag
    that must be remembered is a store that eventually gets overwritten.
    """
    default = Path(os.environ.get("TTE_STORE_PATH") or ARTEMIS_DIR / "tmp" / "tte" / "studies.json")
    bench = default.with_name(f"bench_{model.replace('/', '__')}.json")
    if not bench.exists():
        if not default.exists():
            raise SystemExit(f"No study store to copy from: {default}")
        bench.write_bytes(default.read_bytes())
        print(f"Store copied: {default} -> {bench}")
    os.environ["TTE_STORE_PATH"] = str(bench)
    return bench


def run_study(service: Any, study_id: int, study_name: str, extract: bool) -> dict[str, Any]:
    """Optionally re-extract with the current model, then assemble both arms.

    Extraction is opt-in because the arm is a pure function of the stored
    valueConstraints, so re-extracting would add extraction noise to a contrast
    that has none. Assembly still calls Agent2 concept mapping, so both arms cost
    LLM time either way — what --extract adds is a fresh criterion list.
    """
    if extract:
        service.process_eligibility(study_id)
    study = service.store.get_study(study_id)
    eligibility = study.get("eligibility") or {}

    result: dict[str, Any] = {
        "study_id": study_id,
        "study": study_name,
        "gold": gold_counts(study_name),
        "arms": {},
    }
    for arm in ARMS:
        install_arm(arm)
        # A fresh copy per arm: _build_seeded_target_circe pops keys off its input.
        circe = service._build_seeded_target_circe(json.loads(json.dumps(eligibility)))
        result["arms"][arm] = {
            "counts": count_value_keys(circe),
            "score": score_criteria(eligibility, circe),
        }
    install_arm("adr031")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="LLM_MODEL for this run; recorded as provenance")
    parser.add_argument("--studies", default="", help="Comma-separated study ids (default: all six)")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", action="store_true", help="Aggregate existing results and exit")
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Re-run process_eligibility with the current model before assembling (LLM cost)",
    )
    args = parser.parse_args()

    if args.report:
        return report(args.output_root)

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    selected = STUDIES
    if args.studies:
        wanted = {int(part) for part in args.studies.split(",") if part.strip()}
        selected = {sid: name for sid, name in STUDIES.items() if sid in wanted}

    model = os.environ.get("LLM_MODEL", "unset")
    isolate_store(model)

    from src.services.tte_service import TTEService
    from src.services.tte_store import TTEStore

    service = TTEService(TTEStore(os.environ["TTE_STORE_PATH"]))
    # Always model-labelled. Assembly re-maps every criterion through Agent2, so
    # even without --extract the Circe depends on the model; a shared directory
    # would let two models' runs merge into one apparent result.
    suffix = "extracted" if args.extract else "stored-criteria"
    out_dir = args.output_root / f'{model.replace("/", "__")}__{suffix}'
    out_dir.mkdir(parents=True, exist_ok=True)

    for study_id, study_name in selected.items():
        print(f"[{model}] {study_name} (id={study_id}) ...", flush=True)
        try:
            payload = run_study(service, study_id, study_name, args.extract)
        except Exception:
            # One study failing must not silently shrink the denominator.
            payload = {
                "study_id": study_id,
                "study": study_name,
                "error": traceback.format_exc(limit=6),
            }
            print(f"  FAILED: {payload['error'].splitlines()[-1]}", flush=True)
        payload["runtime_config"] = provenance()
        (out_dir / f"{study_id:02d}_{study_name.replace(' ', '_')}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        if "error" not in payload:
            for arm in ARMS:
                counts = payload["arms"][arm]["counts"]
                print(
                    f"  {arm:<8} RangeHighRatio={counts['RangeHighRatio']:<3} "
                    f"ValueAsNumber={counts['ValueAsNumber']:<3} Unit={counts['Unit']}",
                    flush=True,
                )
    return 0


def report(output_root: Path) -> int:
    if not output_root.is_dir():
        print(f"No results under {output_root}")
        return 1
    for model_dir in sorted(output_root.iterdir()):
        if not model_dir.is_dir():
            continue
        print(f"\n=== {model_dir.name} ===")
        print(f"  {'study':<20} {'gold RHR':>8} {'adr031 RHR':>11} {'legacy RHR':>11} {'adr031 VAN':>11} {'legacy VAN':>11}")
        failed = []
        for path in sorted(model_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "error" in payload:
                failed.append(payload["study"])
                continue
            gold = payload["gold"]["RangeHighRatio"]
            a = payload["arms"]["adr031"]["counts"]
            b = payload["arms"]["legacy"]["counts"]
            print(
                f"  {payload['study']:<20} {gold:>8} {a['RangeHighRatio']:>11} "
                f"{b['RangeHighRatio']:>11} {a['ValueAsNumber']:>11} {b['ValueAsNumber']:>11}"
            )
        if failed:
            print(f"  not measured ({len(failed)}): {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
