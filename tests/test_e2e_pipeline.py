"""
ARTEMIS E2E Pipeline Test: LEADER Trial Emulation.

Full pipeline test: Circe JSON → WebAPI cohorts → HDPS covariates → Analysis → Report.

Target:     Liraglutide (GLP-1 RA) users
Comparator: Sitagliptin (DPP-4 Inhibitor) users
Outcome:    3-point MACE (MI, Stroke, CV Death)
"""
import sys
import pytest
import json
import time
from pathlib import Path

# ============================================================
# LEADER Trial Circe JSON Definitions
# ============================================================

# Target cohort: Liraglutide (RxNorm Ingredient 1301025)
TARGET_CIRCE = {
    "PrimaryCriteria": {
        "CriteriaList": [{"DrugExposure": {"CodesetId": 0}}],
        "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
        "PrimaryCriteriaLimit": {"Type": "First"},
    },
    "ConceptSets": [
        {
            "id": 0,
            "name": "Liraglutide",
            "expression": {
                "items": [
                    {
                        "concept": {
                            "CONCEPT_ID": 1301025,
                            "CONCEPT_NAME": "liraglutide",
                            "DOMAIN_ID": "Drug",
                            "VOCABULARY_ID": "RxNorm",
                            "CONCEPT_CLASS_ID": "Ingredient",
                            "STANDARD_CONCEPT": "S",
                            "CONCEPT_CODE": "475968",
                            "INVALID_REASON": "V",
                        },
                        "includeDescendants": True,
                    }
                ]
            },
        }
    ],
}

# Comparator cohort: Sitagliptin (RxNorm Ingredient 1580747)
COMPARATOR_CIRCE = {
    "PrimaryCriteria": {
        "CriteriaList": [{"DrugExposure": {"CodesetId": 0}}],
        "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
        "PrimaryCriteriaLimit": {"Type": "First"},
    },
    "ConceptSets": [
        {
            "id": 0,
            "name": "Sitagliptin (DPP-4i)",
            "expression": {
                "items": [
                    {
                        "concept": {
                            "CONCEPT_ID": 1580747,
                            "CONCEPT_NAME": "sitagliptin",
                            "DOMAIN_ID": "Drug",
                            "VOCABULARY_ID": "RxNorm",
                            "CONCEPT_CLASS_ID": "Ingredient",
                            "STANDARD_CONCEPT": "S",
                            "CONCEPT_CODE": "593411",
                            "INVALID_REASON": "V",
                        },
                        "includeDescendants": True,
                    }
                ]
            },
        }
    ],
}

# 3-point MACE outcome concept IDs
MACE_CONCEPT_IDS = [
    4329847,   # Myocardial infarction
    372924,    # Cerebral infarction (stroke)
    434376,    # Acute myocardial infarction
    443454,    # Cerebrovascular accident
]


@pytest.mark.integration
def test_e2e():
    """Run the full ARTEMIS E2E pipeline."""
    from src.pipeline.webapi_client import WebAPIClient
    from src.pipeline.cohort_executor import CohortExecutor
    from src.analysis.omop_connector import OMOPConnector
    from src.agents.agent5 import Agent5Workflow
    from src.agents.agent6 import Agent6Workflow
    from src.reporting.models import HazardRatioSummary

    output_dir = Path("./output/e2e_leader_test")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print("  ARTEMIS E2E Pipeline Test: LEADER Trial Emulation")
    print("  Liraglutide vs Sitagliptin (DPP-4i)")
    print("=" * 70 + "\n")

    # ================================================================
    # PHASE 1: Cohort Generation via WebAPI
    # ================================================================
    print("[PHASE 1] Cohort Generation via WebAPI")
    print("-" * 50)

    webapi = WebAPIClient()
    try:
        info = webapi.check_health()
    except Exception:
        pytest.skip("WebAPI not reachable")
    print(f"  ✅ WebAPI {info['version']} online")

    connector = OMOPConnector(
        connection_string="postgresql://postgres:mypass@localhost:5432/ohdsi",
        schema="synthea23m",
    )
    assert connector.test_connection(), "DB connection failed"
    print("  ✅ DB connection OK")

    executor = CohortExecutor(
        connector=connector,
        webapi_client=webapi,
    )

    t0 = time.time()
    result = executor.execute(
        circe_json=TARGET_CIRCE,
        comparator_circe_json=COMPARATOR_CIRCE,
        outcome_concept_ids=MACE_CONCEPT_IDS,
        followup_days=1460,  # 4 years per LEADER
        cohort_name="ARTEMIS LEADER Target",
    )
    t_cohort = time.time() - t0

    print(f"\n  Cohort generation time: {t_cohort:.1f}s")
    print(f"  Total patients: {result.patient_count}")
    print(f"  Target: {result.target_count}")
    print(f"  Comparator: {result.comparator_count}")
    print(f"  Fallback used: {result.used_fallback}")

    data = result.data
    assert len(data) > 0, "No patients extracted"
    assert "treatment" in data.columns, "Missing treatment column"

    n_target = int((data["treatment"] == 1).sum())
    n_comp = int((data["treatment"] == 0).sum())
    assert n_target > 0, f"No target patients (got {n_target})"
    assert n_comp > 0, f"No comparator patients (got {n_comp})"
    print(f"  ✅ Dual-cohort dataset: {n_target} target, {n_comp} comparator")

    # Count HDPS covariates
    hdps_cols = [c for c in data.columns if c.startswith(("cond_", "drug_", "proc_"))]
    print(f"  ✅ HDPS covariates: {len(hdps_cols)}")

    # Save patient data
    data.to_csv(output_dir / "patient_data.csv", index=False)
    print(f"  ✅ Patient data saved: {len(data)} rows, {len(data.columns)} cols")

    # ================================================================
    # PHASE 2: Causal Inference Analysis (Agent 5)
    # ================================================================
    print(f"\n[PHASE 2] Causal Inference Analysis (IPTW)")
    print("-" * 50)

    t0 = time.time()
    agent5 = Agent5Workflow()
    agent5.configure(
        target_cohort_id=1,
        comparator_cohort_id=2,
        analysis_method="IPTW",
    )
    analysis = agent5.run(data=data)
    t_analysis = time.time() - t0

    hr = analysis["hazard_ratio"]
    print(f"\n  Analysis time: {t_analysis:.1f}s")
    print(f"  Method: {analysis['analysis_method']}")
    print(f"  Hazard Ratio: {hr['hr']:.3f}")
    print(f"  95% CI: ({hr['ci_lower']:.3f}, {hr['ci_upper']:.3f})")
    print(f"  p-value: {hr['p_value']:.4f}")
    print(f"  Target N: {analysis['n_target']}")
    print(f"  Comparator N: {analysis['n_comparator']}")

    significance = "SIGNIFICANT" if hr["p_value"] < 0.05 else "not significant"
    print(f"  → Result is {significance}")

    # Check balance
    balanced_count = sum(
        1 for v in analysis["balance"].values()
        if isinstance(v, dict) and v.get("balanced", False)
    )
    total_covariates = len(analysis["balance"])
    print(f"  Balanced covariates: {balanced_count}/{total_covariates}")

    # ================================================================
    # PHASE 3: Report Generation (Agent 6)
    # ================================================================
    print(f"\n[PHASE 3] Report Generation")
    print("-" * 50)

    t0 = time.time()
    hr_summary = HazardRatioSummary(
        hr=hr["hr"],
        ci_lower=hr["ci_lower"],
        ci_upper=hr["ci_upper"],
        p_value=hr["p_value"],
    )

    agent6 = Agent6Workflow()
    agent6.set_results(
        study_title="ARTEMIS LEADER Trial Emulation: Liraglutide vs DPP-4i",
        hazard_ratio=hr_summary,
        target_n=analysis["n_target"],
        comparator_n=analysis["n_comparator"],
        balance=analysis["balance"],
        ps_scores=analysis["ps_scores"],
        treatment=analysis["treatment"],
        survival_data=analysis["survival_data"],
    )

    # Generate plots
    plots_dir = output_dir / "plots"
    plot_paths = agent6.generate_plots(str(plots_dir))
    print(f"  ✅ Generated {len(plot_paths)} plots:")
    for name, path in plot_paths.items():
        print(f"     {name}: {path}")

    # Generate HTML report
    report_path = str(output_dir / "report.html")
    agent6.generate_html_report(report_path)
    t_report = time.time() - t0
    print(f"  ✅ HTML report: {report_path} ({t_report:.1f}s)")

    # ================================================================
    # Summary
    # ================================================================
    total_time = t_cohort + t_analysis + t_report
    print("\n" + "=" * 70)
    print("  ✅ ARTEMIS E2E Pipeline COMPLETE")
    print("=" * 70)
    print(f"  Total time:        {total_time:.1f}s")
    print(f"  Patients:          {len(data)} ({n_target} T / {n_comp} C)")
    print(f"  HDPS covariates:   {len(hdps_cols)}")
    print(f"  HR:                {hr['hr']:.3f} (CI: {hr['ci_lower']:.3f}-{hr['ci_upper']:.3f})")
    print(f"  p-value:           {hr['p_value']:.4f} ({significance})")
    print(f"  Plots:             {len(plot_paths)}")
    print(f"  Report:            {report_path}")
    print(f"  Output dir:        {output_dir.absolute()}")
    print("=" * 70 + "\n")

    return {
        "data_shape": data.shape,
        "n_target": n_target,
        "n_comparator": n_comp,
        "hdps_covariates": len(hdps_cols),
        "hr": hr,
        "plots": len(plot_paths),
        "report": report_path,
    }


if __name__ == "__main__":
    try:
        result = test_e2e()
        print(json.dumps({k: str(v) for k, v in result.items()}, indent=2))
    except Exception as e:
        print(f"\n❌ E2E Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
