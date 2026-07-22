"""Run MedGemma LLM models through the TTE API pipeline and collect benchmark results.

Usage:
    python run_medgemma_benchmark.py --model all --study all
    python run_medgemma_benchmark.py --model "vllm/medgemma-27b-it" --study LEADER
    python run_medgemma_benchmark.py --base-url http://localhost:8080/tte --model all --study PLATO
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STUDIES = [
    {"name": "PLATO", "nctId": "NCT00391872", "sourceKey": "PLATO_BENCHMARK"},
    {"name": "LEADER", "nctId": "NCT01179048", "sourceKey": "LEADER_BENCHMARK"},
    {"name": "ARISTOTLE", "nctId": "NCT00412984", "sourceKey": "ARISTOTLE_BENCHMARK"},
]

MODELS = [
    "vllm/medgemma-27b-it",
    "vllm/medgemma-1.5-4b-it",
]

OUTPUT_PATH = Path("/app/docs/daily_notes/benchmark_run_ids.json")

ELIGIBILITY_POLL_INTERVAL_SEC = 10
ELIGIBILITY_POLL_TIMEOUT_SEC = 600
ELIGIBILITY_DONE_PHASES = frozenset({"done", "completed", "idle", "failed"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Outcome of a single (model, study) pipeline run."""

    model: str
    study_name: str
    study_id: int | None = None
    status: str = "not_started"
    error: str | None = None
    results: dict[str, Any] = field(default_factory=dict)
    elapsed_sec: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_response(resp: requests.Response, label: str) -> dict[str, Any]:
    """Raise on HTTP errors or a 'failed' status in the JSON body."""
    if not resp.ok:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(f"{label} returned HTTP {resp.status_code}: {detail}")
    data: dict[str, Any] = resp.json()
    if data.get("status") == "failed":
        detail = data.get("summary") or data.get("error") or json.dumps(data)
        raise RuntimeError(f"{label} returned status=failed: {detail}")
    return data


def _post(base_url: str, path: str, body: dict[str, Any] | None = None, label: str = "") -> dict[str, Any]:
    """POST helper with logging and response checking."""
    url = f"{base_url}{path}"
    logger.info("POST %s %s", url, json.dumps(body) if body else "")
    resp = requests.post(url, json=body, timeout=600)
    return _check_response(resp, label or path)


def _get(base_url: str, path: str, label: str = "") -> dict[str, Any]:
    """GET helper with logging and response checking."""
    url = f"{base_url}{path}"
    logger.debug("GET %s", url)
    resp = requests.get(url, timeout=120)
    return _check_response(resp, label or path)


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def create_study(base_url: str, study_name: str, model: str) -> int:
    """Create a new TTE study and return its ID."""
    body = {
        "name": f"{study_name} - {model}",
        "comparisonMode": "target_minus_treatment",
    }
    data = _post(base_url, "/studies", body, label="create_study")
    study_id = data["id"]
    logger.info("Created study id=%d name='%s'", study_id, data.get("name"))
    return study_id


def generate_from_nct(base_url: str, study_id: int, nct_id: str, model: str) -> dict[str, Any]:
    """Generate study design from a ClinicalTrials.gov NCT ID."""
    body = {"nctId": nct_id, "forceRefresh": True, "model": model}
    return _post(base_url, f"/studies/{study_id}/generate-from-nct", body, label="generate-from-nct")


def process_eligibility(base_url: str, study_id: int) -> dict[str, Any]:
    """Trigger eligibility concept mapping (async endpoint)."""
    return _post(base_url, f"/studies/{study_id}/process-eligibility", label="process-eligibility")


def poll_eligibility_progress(base_url: str, study_id: int) -> dict[str, Any]:
    """Poll eligibility mapping progress until completion or timeout."""
    deadline = time.monotonic() + ELIGIBILITY_POLL_TIMEOUT_SEC
    while time.monotonic() < deadline:
        data = _get(base_url, f"/studies/{study_id}/process-eligibility-progress", label="eligibility-progress")
        phase = data.get("phase", "unknown")
        logger.info("  eligibility phase=%s (study %d)", phase, study_id)

        if phase in ELIGIBILITY_DONE_PHASES:
            if phase == "failed":
                error_msg = data.get("error") or data.get("summary") or "unknown failure"
                raise RuntimeError(f"Eligibility mapping failed: {error_msg}")
            return data

        time.sleep(ELIGIBILITY_POLL_INTERVAL_SEC)

    raise TimeoutError(f"Eligibility mapping timed out after {ELIGIBILITY_POLL_TIMEOUT_SEC}s for study {study_id}")


def generate_seeded_cohorts(base_url: str, study_id: int) -> dict[str, Any]:
    """Generate CIRCE cohort definitions from mapped concepts."""
    return _post(base_url, f"/studies/{study_id}/generate-seeded-cohorts", label="generate-seeded-cohorts")


def preview_seeded_cohorts(base_url: str, study_id: int) -> str:
    """Preview seeded cohorts and return the previewHash."""
    data = _post(base_url, f"/studies/{study_id}/preview-seeded-cohorts", label="preview-seeded-cohorts")
    preview_hash = data["previewHash"]
    logger.info("  previewHash=%s", preview_hash)
    return preview_hash


def register_seeded_cohorts(base_url: str, study_id: int, preview_hash: str) -> dict[str, Any]:
    """Register previewed cohorts into WebAPI."""
    body = {"previewHash": preview_hash}
    return _post(base_url, f"/studies/{study_id}/register-seeded-cohorts", body, label="register-seeded-cohorts")


def apply_artifact(base_url: str, artifact_id: str, study_id: int, target_sections: list[str]) -> dict[str, Any]:
    """Apply an artifact's proposed changes to the study."""
    study = _get(base_url, f"/studies/{study_id}", label="get-study-version")
    base_version = int(study.get("version") or 1)
    body = {"targetSections": target_sections, "baseStudyVersion": base_version}
    return _post(base_url, f"/artifacts/{artifact_id}/apply", body, label="apply-artifact")


def run_full_pipeline(base_url: str, study_id: int, source_key: str) -> dict[str, Any]:
    """Execute the full analysis pipeline (execute + analysis + report)."""
    body = {"sourceKey": source_key}
    return _post(base_url, f"/studies/{study_id}/run-full-pipeline", body, label="run-full-pipeline")


def get_study(base_url: str, study_id: int) -> dict[str, Any]:
    """Fetch the final study state with results."""
    return _get(base_url, f"/studies/{study_id}", label="get-study")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_single_pipeline(base_url: str, model: str, study_cfg: dict[str, str]) -> RunResult:
    """Run the complete TTE pipeline for one (model, study) pair."""
    study_name = study_cfg["name"]
    nct_id = study_cfg["nctId"]
    source_key = study_cfg["sourceKey"]

    result = RunResult(model=model, study_name=study_name)
    t0 = time.monotonic()

    sid: int | None = None
    try:
        # Step 1: Create study
        sid = create_study(base_url, study_name, model)
        result.study_id = sid

        # Step 2: Generate from NCT → apply artifact to persist protocol
        logger.info("[%s/%s] Generating from NCT %s ...", model, study_name, nct_id)
        gen_resp = generate_from_nct(base_url, sid, nct_id, model)
        if gen_resp.get("artifactId"):
            logger.info("[%s/%s] Applying generate artifact ...", model, study_name)
            apply_artifact(base_url, gen_resp["artifactId"], sid, ["eligibility", "treatmentArms", "outcomes", "trialMetadata", "status"])

        # Step 3: Process eligibility → poll → apply to persist concept mappings
        logger.info("[%s/%s] Processing eligibility ...", model, study_name)
        elig_resp = process_eligibility(base_url, sid)
        poll_eligibility_progress(base_url, sid)
        if elig_resp.get("artifactId"):
            logger.info("[%s/%s] Applying eligibility artifact ...", model, study_name)
            apply_artifact(base_url, elig_resp["artifactId"], sid, ["eligibility"])

        # Step 4: Preview seeded cohorts (builds CIRCE from mapped criteria)
        logger.info("[%s/%s] Previewing seeded cohorts ...", model, study_name)
        preview_hash = preview_seeded_cohorts(base_url, sid)

        # Step 5: Register seeded cohorts (calls generate_seeded_cohorts internally) → apply
        logger.info("[%s/%s] Registering seeded cohorts ...", model, study_name)
        reg_resp = register_seeded_cohorts(base_url, sid, preview_hash)
        if reg_resp.get("artifactId"):
            logger.info("[%s/%s] Applying register artifact ...", model, study_name)
            apply_artifact(base_url, reg_resp["artifactId"], sid, ["eligibility", "treatmentArms", "outcomes"])

        # Step 6: Validate design (required before execution — artifact existence check only, no apply needed)
        logger.info("[%s/%s] Validating design ...", model, study_name)
        _post(base_url, f"/studies/{sid}/validate", label="validate-design")

        # Step 7: Run full pipeline (execute + analysis + report) — auto-applies internally
        logger.info("[%s/%s] Running full pipeline (sourceKey=%s) ...", model, study_name, source_key)
        run_full_pipeline(base_url, sid, source_key)

        # Step 8: Collect final results
        logger.info("[%s/%s] Collecting final results ...", model, study_name)
        final = get_study(base_url, sid)
        result.results = final.get("results") or {}
        result.status = final.get("status", "unknown")

        logger.info("[%s/%s] Completed with status=%s", model, study_name, result.status)

    except Exception as exc:
        result.status = "error"
        result.error = str(exc)
        logger.error("[%s/%s] Failed (study_id=%s): %s", model, study_name, sid, exc)

    result.elapsed_sec = round(time.monotonic() - t0, 1)
    return result


# ---------------------------------------------------------------------------
# Output & reporting
# ---------------------------------------------------------------------------


def save_results(results: list[RunResult], output_path: Path) -> None:
    """Persist run results to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "model": r.model,
            "study": r.study_name,
            "studyId": r.study_id,
            "status": r.status,
            "error": r.error,
            "elapsedSec": r.elapsed_sec,
            "results": r.results,
        }
        for r in results
    ]
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info("Results saved to %s", output_path)


def print_summary(results: list[RunResult]) -> None:
    """Print a summary table of all runs."""
    header = f"{'Model':<30} {'Study':<12} {'ID':>5} {'Status':<12} {'Time(s)':>8} {'Error'}"
    separator = "-" * len(header)
    print(f"\n{separator}")
    print(header)
    print(separator)
    for r in results:
        error_col = (r.error[:60] + "...") if r.error and len(r.error) > 60 else (r.error or "")
        sid_str = str(r.study_id) if r.study_id is not None else "-"
        print(f"{r.model:<30} {r.study_name:<12} {sid_str:>5} {r.status:<12} {r.elapsed_sec:>8.1f} {error_col}")
    print(separator)

    ok_count = sum(1 for r in results if r.status not in ("error", "failed", "not_started"))
    fail_count = len(results) - ok_count
    print(f"\nTotal: {len(results)} runs | OK: {ok_count} | Failed: {fail_count}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Run MedGemma benchmark through TTE API pipeline")
    parser.add_argument(
        "--model",
        default="all",
        help='Model name or "all" for both MedGemma variants (default: all)',
    )
    parser.add_argument(
        "--study",
        default="all",
        help='Study name (PLATO/LEADER/ARISTOTLE) or "all" (default: all)',
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080/tte",
        help="TTE API base URL (default: http://localhost:8080/tte)",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_PATH),
        help=f"Output JSON path (default: {OUTPUT_PATH})",
    )
    return parser.parse_args(argv)


def resolve_models(model_arg: str) -> list[str]:
    """Resolve --model arg into a list of model names."""
    if model_arg.lower() == "all":
        return list(MODELS)
    if model_arg not in MODELS:
        logger.warning("Model '%s' is not in the default list; using it anyway.", model_arg)
    return [model_arg]


def resolve_studies(study_arg: str) -> list[dict[str, str]]:
    """Resolve --study arg into a list of study configs."""
    if study_arg.lower() == "all":
        return list(STUDIES)
    matched = [s for s in STUDIES if s["name"].upper() == study_arg.upper()]
    if not matched:
        available = ", ".join(s["name"] for s in STUDIES)
        raise ValueError(f"Unknown study '{study_arg}'. Available: {available}")
    return matched


def main(argv: list[str] | None = None) -> None:
    """Entry point: parse args, run pipelines, report results."""
    args = parse_args(argv)

    models = resolve_models(args.model)
    studies = resolve_studies(args.study)
    output_path = Path(args.output)

    logger.info("Models: %s", models)
    logger.info("Studies: %s", [s["name"] for s in studies])
    logger.info("Base URL: %s", args.base_url)
    logger.info("Output: %s", output_path)

    results: list[RunResult] = []
    for model in models:
        for study_cfg in studies:
            logger.info("=" * 70)
            logger.info("Starting: model=%s study=%s", model, study_cfg["name"])
            logger.info("=" * 70)
            result = run_single_pipeline(args.base_url, model, study_cfg)
            results.append(result)

    save_results(results, output_path)
    print_summary(results)

    has_failures = any(r.status in ("error", "failed") for r in results)
    if has_failures:
        logger.warning("Some runs failed. Check the summary above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
