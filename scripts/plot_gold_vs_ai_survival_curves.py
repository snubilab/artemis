#!/usr/bin/env python3
"""Export per-study Kaplan-Meier survival curves comparing Gold vs Ours."""
from __future__ import annotations

import argparse
import dataclasses
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import create_engine, text

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.analysis.km import KaplanMeierAnalysis, compare_survival_curves
from src.analysis.omop_connector import OMOPConnector
from src.pipeline.webapi_client import CohortTableReference


@dataclasses.dataclass
class StudyConfig:
    name: str
    cdm_schema: str
    results_schema: str
    ai_treatment_id: int
    gold_treatment_id: int
    outcome_id: int
    outcome_concept_id: int


STUDIES = [
    StudyConfig(
        name="LEADER",
        cdm_schema="synthea_cdm_leader",
        results_schema="synthea_cdm_leader_results",
        ai_treatment_id=840,
        gold_treatment_id=1136,
        outcome_id=841,
        outcome_concept_id=312327,
    ),
    StudyConfig(
        name="PLATO",
        cdm_schema="synthea_cdm_plato",
        results_schema="synthea_cdm_plato_results",
        ai_treatment_id=941,
        gold_treatment_id=1137,
        outcome_id=943,
        outcome_concept_id=4329847,
    ),
    StudyConfig(
        name="ARISTOTLE",
        cdm_schema="synthea_cdm_aristotle",
        results_schema="synthea_cdm_aristotle_results",
        ai_treatment_id=1127,
        gold_treatment_id=1138,
        outcome_id=1128,
        outcome_concept_id=381316,
    ),
]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Plot Kaplan-Meier curves for Gold vs Ours")
    p.add_argument("--db-url", default=os.environ.get("DATABASE_URL", "postgresql://postgres:mypass@127.0.0.1:5432/postgres"))
    p.add_argument("--studies", nargs="*", default=[s.name for s in STUDIES])
    p.add_argument("--followup-days", type=int, default=30)
    p.add_argument("--max-days", type=int, default=30)
    p.add_argument("--benchmark-json", default=None, help="Optional run_gold_vs_ai_comparison JSON for HR columns")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--prefix", default="2026-04-01_gold_vs_ai")
    return p.parse_args(argv)


def _study_map():
    return {s.name: s for s in STUDIES}


def _load_index_dates(engine, results_schema: str, cohort_id: int) -> pd.DataFrame:
    query = text(
        f"""
        SELECT subject_id AS person_id, MIN(cohort_start_date) AS index_date
        FROM {results_schema}.cohort
        WHERE cohort_definition_id = :cid
        GROUP BY subject_id
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"cid": cohort_id})
    if df.empty:
        return df
    df["index_date"] = pd.to_datetime(df["index_date"]).dt.date
    return df


def _extract_survival(connector: OMOPConnector, cohort_df: pd.DataFrame, outcome_ref: CohortTableReference, followup_days: int) -> pd.DataFrame:
    person_ids = cohort_df["person_id"].astype(int).tolist()
    index_dates = dict(zip(cohort_df["person_id"].astype(int), cohort_df["index_date"]))
    return connector.extract_outcome_from_cohort(person_ids, outcome_ref, index_dates, followup_days)


def _fmt_hr_ci(block: dict) -> str:
    hr = block.get("hr")
    lo = block.get("ci_lower")
    hi = block.get("ci_upper")
    if hr is None or lo is None or hi is None:
        return ""
    return f"{float(hr):.3f} [{float(lo):.3f}, {float(hi):.3f}]"


def _build_hr_lookup(path: str | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for study, data in payload.items():
        gold = data.get("gold", {})
        ours = data.get("ai", {})
        ci_ratio = ""
        g_w = gold.get("ci_width")
        o_w = ours.get("ci_width")
        if g_w not in (None, 0) and o_w is not None:
            ci_ratio = f"{float(o_w) / float(g_w):.4f}"
        out[study] = {
            "gold_hr_ci": _fmt_hr_ci(gold),
            "ours_hr_ci": _fmt_hr_ci(ours),
            "ci_ratio": ci_ratio,
        }
    return out


def _plot_single(
    study_name: str,
    gold_surv: pd.DataFrame,
    ours_surv: pd.DataFrame,
    out_path: Path,
    max_days: int,
):
    km_gold = KaplanMeierAnalysis().fit(
        times=gold_surv["time"].tolist(),
        events=gold_surv["event"].tolist(),
        label="Gold",
    )
    km_ours = KaplanMeierAnalysis().fit(
        times=ours_surv["time"].tolist(),
        events=ours_surv["event"].tolist(),
        label="Ours",
    )

    fig, ax = plt.subplots(figsize=(8, 5), dpi=140)
    km_gold.km_fitter.plot_survival_function(ax=ax, ci_show=True, color="#1f77b4")
    km_ours.km_fitter.plot_survival_function(ax=ax, ci_show=True, color="#d62728")
    ax.set_title(f"{study_name}: Kaplan-Meier Survival (Gold vs Ours)")
    ax.set_xlabel("Days")
    ax.set_ylabel("Survival probability")
    ax.grid(alpha=0.25, linestyle="--", linewidth=0.8)
    ax.set_ylim(0.0, 1.02)
    ax.set_xlim(0, max_days)
    tick_step = 5 if max_days >= 20 else max(1, max_days // 5)
    ax.set_xticks(list(range(0, max_days + 1, tick_step)))
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _write_summary(paths: tuple[Path, Path], rows: list[list[str]], horizon_days: int, include_hr: bool):
    csv_path, md_path = paths
    header = [
        "Study",
        "Gold N",
        "Gold Events",
        "Ours N",
        "Ours Events",
        "Log-rank p-value",
        f"Gold S({horizon_days}d)",
        f"Ours S({horizon_days}d)",
    ]
    if include_hr:
        header.extend([
            "Gold HR [95% CI]",
            "Ours HR [95% CI]",
            "CI Ratio (Ours/Gold)",
        ])
    header.extend([
        "Outcome Source",
        "Plot",
    ])

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    lines = [
        "# Gold vs Ours Kaplan-Meier Summary",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    hr_lookup = _build_hr_lookup(args.benchmark_json)

    selected = []
    study_lookup = _study_map()
    for name in args.studies:
        key = name.upper()
        if key not in study_lookup:
            raise ValueError(f"Unknown study: {name}")
        selected.append(study_lookup[key])

    rows = []
    for study in selected:
        connector = OMOPConnector(connection_string=args.db_url, schema=study.cdm_schema)
        engine = create_engine(args.db_url)

        gold_df = _load_index_dates(engine, study.results_schema, study.gold_treatment_id)
        ours_df = _load_index_dates(engine, study.results_schema, study.ai_treatment_id)
        if gold_df.empty or ours_df.empty:
            continue

        outcome_ref = CohortTableReference(
            cohort_definition_id=study.outcome_id,
            results_schema=study.results_schema,
            person_count=0,
            source_key="",
            name=f"{study.name} outcome",
        )

        gold_surv = _extract_survival(connector, gold_df, outcome_ref, args.followup_days)
        ours_surv = _extract_survival(connector, ours_df, outcome_ref, args.followup_days)
        outcome_source = "cohort"

        cmp_result = compare_survival_curves(
            gold_surv["time"].tolist(),
            gold_surv["event"].tolist(),
            ours_surv["time"].tolist(),
            ours_surv["event"].tolist(),
        )

        km_gold = KaplanMeierAnalysis().fit(gold_surv["time"].tolist(), gold_surv["event"].tolist(), label="Gold")
        km_ours = KaplanMeierAnalysis().fit(ours_surv["time"].tolist(), ours_surv["event"].tolist(), label="Ours")

        plot_name = f"{args.prefix}_{study.name.lower()}_km_gold_vs_ours_{args.max_days}d.png"
        plot_path = output_dir / plot_name
        _plot_single(study.name, gold_surv, ours_surv, plot_path, args.max_days)

        row = [
            study.name,
            str(len(gold_surv)),
            str(int(gold_surv["event"].sum())),
            str(len(ours_surv)),
            str(int(ours_surv["event"].sum())),
            f"{cmp_result.p_value:.4g}",
            f"{km_gold.survival_function_at(args.max_days):.4f}",
            f"{km_ours.survival_function_at(args.max_days):.4f}",
        ]
        hr = hr_lookup.get(study.name, {})
        if args.benchmark_json:
            row.extend([
                hr.get("gold_hr_ci", ""),
                hr.get("ours_hr_ci", ""),
                hr.get("ci_ratio", ""),
            ])
        row.extend([outcome_source, plot_name])
        rows.append(row)

        print(f"Wrote: {plot_path}")

    csv_path = output_dir / f"{args.prefix}_km_gold_vs_ours_summary_{args.max_days}d.csv"
    md_path = output_dir / f"{args.prefix}_km_gold_vs_ours_summary_{args.max_days}d.md"
    _write_summary((csv_path, md_path), rows, args.max_days, include_hr=bool(args.benchmark_json))
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {md_path}")


if __name__ == "__main__":
    main()
