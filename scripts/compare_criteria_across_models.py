#!/usr/bin/env python3
"""
Compare TTE eligibility criteria and concept IDs across different LLM models.

Fetches study details from the TTE API for GPT-4o (baseline) and medgemma models,
then produces a Markdown comparison report with criteria counts, concept ID Jaccard
similarity, and HR results per trial.

Usage:
    python3 compare_criteria_across_models.py --gpt4o 480,481,482
    python3 compare_criteria_across_models.py --gpt4o 480,481,482 --medgemma-27b 503,504,505 --medgemma-4b 506,507,508
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRIAL_ORDER = ["PLATO", "LEADER", "ARISTOTLE"]

NCT_TO_TRIAL: dict[str, str] = {
    "NCT00391872": "PLATO",
    "NCT01179048": "LEADER",
    "NCT00412984": "ARISTOTLE",
}

DEFAULT_OUTPUT = "/app/docs/daily_notes/2026-04-05_criteria_comparison_gpt4o_vs_medgemma.md"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Criterion:
    description: str
    domain: str
    concept_set_id: int | None
    concept_set_name: str
    mappable: bool
    concept_ids: list[int] = field(default_factory=list)


@dataclass
class StudyDetail:
    study_id: int
    trial_name: str
    nct_id: str
    inclusion: list[Criterion] = field(default_factory=list)
    exclusion: list[Criterion] = field(default_factory=list)
    hazard_ratio: float | None = None
    hr_lower: float | None = None
    hr_upper: float | None = None
    treatment_n: int | None = None
    comparator_n: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_concept_ids(structured_expr: dict | None, concept_set_id: int | None) -> list[int]:
    """Extract OMOP concept IDs for a conceptSetId from structuredExpression."""
    if not structured_expr or concept_set_id is None:
        return []
    for cs in structured_expr.get("ConceptSets", []):
        if cs.get("id") == concept_set_id:
            return sorted(
                {
                    int(item["concept"]["CONCEPT_ID"])
                    for item in cs.get("expression", {}).get("items", [])
                    if item.get("concept", {}).get("CONCEPT_ID") is not None
                }
            )
    return []


def jaccard(a: list[int], b: list[int]) -> float:
    """Jaccard similarity between two concept ID lists."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _parse_criteria(raw_list: list[dict], structured_expr: dict | None) -> list[Criterion]:
    """Parse raw criteria dicts into Criterion objects with concept IDs attached."""
    result: list[Criterion] = []
    for c in raw_list:
        cs_id = c.get("conceptSetId")
        crit = Criterion(
            description=c.get("description", ""),
            domain=c.get("domain", ""),
            concept_set_id=cs_id,
            concept_set_name=c.get("conceptSetName", ""),
            mappable=c.get("mappable", False),
            concept_ids=_extract_concept_ids(structured_expr, cs_id),
        )
        result.append(crit)
    return result


def _detect_trial(data: dict) -> str:
    """Detect trial name from study metadata NCT ID."""
    nct = data.get("trialMetadata", {}).get("nctId", "")
    return NCT_TO_TRIAL.get(nct, f"UNKNOWN({nct})")


# ---------------------------------------------------------------------------
# API access
# ---------------------------------------------------------------------------


def fetch_study(base_url: str, study_id: int) -> StudyDetail | None:
    """Fetch a single study from the TTE API and parse into StudyDetail."""
    url = f"{base_url}/studies/{study_id}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Failed to fetch study %d: %s", study_id, exc)
        return None

    data = resp.json()
    eligibility = data.get("eligibility", {})
    structured_expr = eligibility.get("structuredExpression")
    results = data.get("results") or {}

    trial_name = _detect_trial(data)

    return StudyDetail(
        study_id=study_id,
        trial_name=trial_name,
        nct_id=data.get("trialMetadata", {}).get("nctId", ""),
        inclusion=_parse_criteria(eligibility.get("inclusionCriteria", []), structured_expr),
        exclusion=_parse_criteria(eligibility.get("exclusionCriteria", []), structured_expr),
        hazard_ratio=results.get("hazardRatio"),
        hr_lower=results.get("hrLower95"),
        hr_upper=results.get("hrUpper95"),
        treatment_n=results.get("treatmentN"),
        comparator_n=results.get("comparatorN"),
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _fmt_hr(sd: StudyDetail) -> str:
    """Format HR with 95% CI, or 'N/A' if missing."""
    if sd.hazard_ratio is None:
        return "N/A"
    hr = f"{sd.hazard_ratio:.3f}"
    if sd.hr_lower is not None and sd.hr_upper is not None:
        hr += f" ({sd.hr_lower:.3f}-{sd.hr_upper:.3f})"
    return hr


def _fmt_n(val: int | None) -> str:
    return str(val) if val is not None else "N/A"


def _criteria_desc_short(c: Criterion, max_len: int = 60) -> str:
    """Truncate description for table display."""
    desc = c.description.replace("\n", " ").strip()
    if len(desc) > max_len:
        return desc[: max_len - 3] + "..."
    return desc


def _concept_ids_str(c: Criterion) -> str:
    if not c.concept_ids:
        return "-"
    if len(c.concept_ids) <= 5:
        return ", ".join(str(x) for x in c.concept_ids)
    return ", ".join(str(x) for x in c.concept_ids[:4]) + f" ...+{len(c.concept_ids) - 4}"


def generate_report(
    models: dict[str, dict[str, StudyDetail]],
    output_path: str,
) -> str:
    """Generate the full Markdown comparison report.

    Args:
        models: {model_name: {trial_name: StudyDetail}}
        output_path: Where the report will be written.

    Returns:
        The Markdown string.
    """
    buf = io.StringIO()
    w = buf.write

    w(f"# TTE Criteria Comparison Across LLM Models\n\n")
    w(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")

    model_names = list(models.keys())

    # ------------------------------------------------------------------
    # 1. Cross-study summary table
    # ------------------------------------------------------------------
    w("## 1. Cross-Study Summary\n\n")
    w("| Trial | Model | Study ID | Incl | Excl | HR (95% CI) | Tx N | Comp N |\n")
    w("|-------|-------|----------|------|------|-------------|------|--------|\n")
    for trial in TRIAL_ORDER:
        for mname in model_names:
            sd = models[mname].get(trial)
            if sd is None:
                w(f"| {trial} | {mname} | - | - | - | - | - | - |\n")
            else:
                w(
                    f"| {trial} | {mname} | {sd.study_id} "
                    f"| {len(sd.inclusion)} | {len(sd.exclusion)} "
                    f"| {_fmt_hr(sd)} | {_fmt_n(sd.treatment_n)} | {_fmt_n(sd.comparator_n)} |\n"
                )
    w("\n")

    # ------------------------------------------------------------------
    # 2. Per-trial sections
    # ------------------------------------------------------------------
    for trial in TRIAL_ORDER:
        w(f"## 2. {trial}\n\n")

        # Study metadata sub-table
        w(f"### {trial} — Study Metadata\n\n")
        w("| Model | Study ID | Incl | Excl | HR (95% CI) | Tx N | Comp N |\n")
        w("|-------|----------|------|------|-------------|------|--------|\n")
        for mname in model_names:
            sd = models[mname].get(trial)
            if sd is None:
                w(f"| {mname} | - | - | - | - | - | - |\n")
            else:
                w(
                    f"| {mname} | {sd.study_id} "
                    f"| {len(sd.inclusion)} | {len(sd.exclusion)} "
                    f"| {_fmt_hr(sd)} | {_fmt_n(sd.treatment_n)} | {_fmt_n(sd.comparator_n)} |\n"
                )
        w("\n")

        # Inclusion criteria table
        _write_criteria_table(w, "Inclusion", trial, models, model_names)

        # Exclusion criteria table
        _write_criteria_table(w, "Exclusion", trial, models, model_names)

        # Jaccard similarity (GPT-4o as reference)
        if "gpt-4o" in models and len(model_names) > 1:
            _write_jaccard_section(w, trial, models, model_names)

    # ------------------------------------------------------------------
    # 3. Study ID reference
    # ------------------------------------------------------------------
    w("## 3. Study ID Reference\n\n")
    w("| Model | PLATO | LEADER | ARISTOTLE |\n")
    w("|-------|-------|--------|----------|\n")
    for mname in model_names:
        ids = []
        for trial in TRIAL_ORDER:
            sd = models[mname].get(trial)
            ids.append(str(sd.study_id) if sd else "-")
        w(f"| {mname} | {' | '.join(ids)} |\n")
    w("\n")

    return buf.getvalue()


def _write_criteria_table(
    w,
    kind: str,
    trial: str,
    models: dict[str, dict[str, StudyDetail]],
    model_names: list[str],
) -> None:
    """Write an inclusion or exclusion criteria comparison table."""
    w(f"### {trial} — {kind} Criteria\n\n")

    # Header
    header_cols = ["#"]
    for mname in model_names:
        header_cols.extend([f"{mname} Description", f"{mname} Concepts"])
    w("| " + " | ".join(header_cols) + " |\n")
    w("|" + "|".join(["---"] * len(header_cols)) + "|\n")

    # Determine max row count across models
    attr = "inclusion" if kind == "Inclusion" else "exclusion"
    max_rows = 0
    for mname in model_names:
        sd = models[mname].get(trial)
        if sd:
            max_rows = max(max_rows, len(getattr(sd, attr)))

    if max_rows == 0:
        w("_(no criteria)_\n\n")
        return

    for i in range(max_rows):
        cols: list[str] = [str(i + 1)]
        for mname in model_names:
            sd = models[mname].get(trial)
            criteria_list = getattr(sd, attr) if sd else []
            if i < len(criteria_list):
                c = criteria_list[i]
                cols.append(_criteria_desc_short(c))
                cols.append(_concept_ids_str(c))
            else:
                cols.extend(["-", "-"])
        w("| " + " | ".join(cols) + " |\n")
    w("\n")


def _write_jaccard_section(
    w,
    trial: str,
    models: dict[str, dict[str, StudyDetail]],
    model_names: list[str],
) -> None:
    """Write Jaccard similarity between GPT-4o (ref) and other models."""
    ref_sd = models["gpt-4o"].get(trial)
    if not ref_sd:
        return

    other_models = [m for m in model_names if m != "gpt-4o"]
    if not other_models:
        return

    w(f"### {trial} — Concept ID Jaccard Similarity (ref: gpt-4o)\n\n")

    for other_name in other_models:
        other_sd = models[other_name].get(trial)
        if not other_sd:
            w(f"**{other_name}**: study not available\n\n")
            continue

        w(f"**gpt-4o vs {other_name}**\n\n")
        w("| Type | # | Ref Description | Jaccard | Shared | Ref-only | Other-only |\n")
        w("|------|---|-----------------|---------|--------|----------|------------|\n")

        for kind, attr in [("Incl", "inclusion"), ("Excl", "exclusion")]:
            ref_criteria: list[Criterion] = getattr(ref_sd, attr)
            other_criteria: list[Criterion] = getattr(other_sd, attr)

            for i, ref_c in enumerate(ref_criteria):
                ref_ids = set(ref_c.concept_ids)
                # Positional alignment (approximate)
                if i < len(other_criteria):
                    oth_c = other_criteria[i]
                    oth_ids = set(oth_c.concept_ids)
                else:
                    oth_ids = set()

                j = jaccard(ref_c.concept_ids, list(oth_ids))
                shared = len(ref_ids & oth_ids)
                ref_only = len(ref_ids - oth_ids)
                oth_only = len(oth_ids - ref_ids)

                w(
                    f"| {kind} | {i + 1} | {_criteria_desc_short(ref_c, 40)} "
                    f"| {j:.3f} | {shared} | {ref_only} | {oth_only} |\n"
                )

        w("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_id_list(raw: str) -> list[int]:
    """Parse comma-separated study IDs."""
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Compare TTE eligibility criteria across LLM models.",
    )
    parser.add_argument(
        "--gpt4o",
        required=True,
        help="GPT-4o study IDs (PLATO,LEADER,ARISTOTLE order), e.g. 480,481,482",
    )
    parser.add_argument(
        "--medgemma-27b",
        default=None,
        help="medgemma-27b study IDs (PLATO,LEADER,ARISTOTLE order)",
    )
    parser.add_argument(
        "--medgemma-4b",
        default=None,
        help="medgemma-4b study IDs (PLATO,LEADER,ARISTOTLE order)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output Markdown path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080/tte",
        help="TTE API base URL (default: http://localhost:8080/tte)",
    )
    return parser


def _load_model_studies(
    base_url: str,
    model_name: str,
    id_csv: str,
) -> dict[str, StudyDetail]:
    """Fetch studies for a model and return {trial_name: StudyDetail}."""
    ids = _parse_id_list(id_csv)
    if len(ids) != 3:
        log.error("Expected 3 study IDs for %s (PLATO,LEADER,ARISTOTLE), got %d", model_name, len(ids))
        sys.exit(1)

    result: dict[str, StudyDetail] = {}
    for study_id, expected_trial in zip(ids, TRIAL_ORDER):
        sd = fetch_study(base_url, study_id)
        if sd is None:
            log.warning("Skipping %s study %d (fetch failed)", model_name, study_id)
            continue
        if sd.trial_name != expected_trial:
            log.warning(
                "Study %d detected as %s but expected %s (position). Using detected name.",
                study_id,
                sd.trial_name,
                expected_trial,
            )
        result[sd.trial_name] = sd
    return result


def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    models: dict[str, dict[str, StudyDetail]] = {}

    # GPT-4o (always required)
    log.info("Fetching gpt-4o studies: %s", args.gpt4o)
    models["gpt-4o"] = _load_model_studies(args.base_url, "gpt-4o", args.gpt4o)

    # Optional medgemma models
    if args.medgemma_27b:
        log.info("Fetching medgemma-27b studies: %s", args.medgemma_27b)
        models["medgemma-27b"] = _load_model_studies(args.base_url, "medgemma-27b", args.medgemma_27b)

    if args.medgemma_4b:
        log.info("Fetching medgemma-4b studies: %s", args.medgemma_4b)
        models["medgemma-4b"] = _load_model_studies(args.base_url, "medgemma-4b", args.medgemma_4b)

    total_studies = sum(len(v) for v in models.values())
    if total_studies == 0:
        log.error("No studies fetched successfully. Aborting.")
        sys.exit(1)

    log.info("Fetched %d studies across %d models", total_studies, len(models))

    report = generate_report(models, args.output)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)

    log.info("Report written to %s (%d chars)", args.output, len(report))


if __name__ == "__main__":
    main()
