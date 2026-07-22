#!/usr/bin/env python
"""
E2E Demo with Real OMOP CDM Data.
Phase 5: Real data integration for ARTEMIS 3.1.

Uses demo_cdm schema from Broadsea PostgreSQL.
"""
import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_real_data_demo(
    output_dir: str = "./output/real_data_demo",
    db_connection: str = "postgresql://postgres:mypass@localhost:5432/postgres"
):
    """Run E2E demo with real OMOP CDM data."""
    from src.analysis.omop_connector import OMOPConnector
    from src.agents.agent5 import Agent5Workflow
    from src.agents.agent6 import Agent6Workflow
    from src.reporting.models import HazardRatioSummary
    
    print("=" * 60)
    print("ARTEMIS 3.1 - Real Data E2E Demo")
    print("=" * 60)
    
    # Step 1: Connect to OMOP CDM
    print("\n[1/5] Connecting to OMOP CDM (demo_cdm)...")
    connector = OMOPConnector(
        connection_string=db_connection,
        schema="demo_cdm"
    )
    
    if not connector.test_connection():
        print("❌ Database connection failed!")
        return None
    
    person_count = connector.get_person_count()
    print(f"  ✓ Connected! {person_count:,} patients in database")
    
    # Step 2: Define study
    print("\n[2/5] Defining study cohorts...")
    
    # Top drugs from demo_cdm (concept IDs determined earlier)
    # Drug A (target): 1127433 (most prescribed)
    # Drug B (comparator): 40213160 (second most prescribed)
    target_drug_ids = [1127433]
    comparator_drug_ids = [40213160]
    
    # Outcome: Top condition (GI Bleed related - 260139)
    outcome_concept_ids = [260139]  # Upper respiratory infection (common in demo)
    
    print(f"  - Target Drug Concept ID: {target_drug_ids}")
    print(f"  - Comparator Drug Concept ID: {comparator_drug_ids}")
    print(f"  - Outcome Concept ID: {outcome_concept_ids}")
    
    # Step 3: Build analysis dataset
    print("\n[3/5] Extracting analysis dataset from OMOP CDM...")
    
    data = connector.build_analysis_dataset(
        target_drug_ids=target_drug_ids,
        comparator_drug_ids=comparator_drug_ids,
        outcome_concept_ids=outcome_concept_ids,
        followup_days=365
    )
    
    print(f"  - Total patients: {len(data)}")
    print(f"  - Target (treatment=1): {(data['treatment'] == 1).sum()}")
    print(f"  - Comparator (treatment=0): {(data['treatment'] == 0).sum()}")
    print(f"  - Events: {data['event'].sum()}")
    print(f"  - Event rate: {data['event'].mean():.1%}")
    
    if len(data) < 10:
        print("⚠️ Not enough patients for analysis. Try different drug concepts.")
        return None
    
    # Step 4: Run Agent 5 Analysis
    print("\n[4/5] Running Agent 5 (Analysis Agent)...")
    
    agent5 = Agent5Workflow()
    agent5.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="IPTW")
    
    try:
        results = agent5.run(data=data)
    except Exception as e:
        print(f"⚠️ Analysis failed: {e}")
        print("  This may be due to insufficient events or separation issues.")
        return None
    
    hr = results["hazard_ratio"]
    print(f"  ✓ Hazard Ratio: {hr['hr']:.3f}")
    print(f"  ✓ 95% CI: [{hr['ci_lower']:.3f}, {hr['ci_upper']:.3f}]")
    print(f"  ✓ p-value: {hr['p_value']:.4f}")
    
    # Check balance
    balance = results["balance"]
    print(f"  ✓ Covariate balance:")
    for cov, vals in balance.items():
        status = "✓" if vals["balanced"] else "✗"
        print(f"    {status} {cov}: SMD = {vals['smd_before']:.3f}")
    
    # Step 5: Generate Report
    print("\n[5/5] Running Agent 6 (Reporting Agent)...")
    
    hr_summary = HazardRatioSummary(
        hr=hr['hr'],
        ci_lower=hr['ci_lower'],
        ci_upper=hr['ci_upper'],
        p_value=hr['p_value']
    )
    
    agent6 = Agent6Workflow()
    agent6.set_results(
        study_title=f"ARTEMIS Real Data: Drug {target_drug_ids[0]} vs {comparator_drug_ids[0]}",
        hazard_ratio=hr_summary,
        target_n=results['n_target'],
        comparator_n=results['n_comparator'],
        balance=results['balance'],
        ps_scores=results['ps_scores'],
        treatment=results['treatment'],
        survival_data=results['survival_data']
    )
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    plot_paths = agent6.generate_plots(str(output_path / "plots"))
    print(f"  ✓ Generated plots:")
    for name, path in plot_paths.items():
        print(f"    - {name}: {path}")
    
    report_path = str(output_path / "report.html")
    agent6.generate_html_report(report_path)
    print(f"  ✓ Report saved: {report_path}")
    
    # Summary
    print("\n" + "=" * 60)
    print("✅ Real Data E2E Demo Complete!")
    print("=" * 60)
    print(f"\nOutputs saved to: {output_path.absolute()}")
    print("\nKey findings (from real OMOP CDM data):")
    print(f"  - Patients analyzed: {len(data)}")
    print(f"  - HR = {hr['hr']:.2f} (95% CI: {hr['ci_lower']:.2f}-{hr['ci_upper']:.2f})")
    significance = "statistically significant" if hr['p_value'] < 0.05 else "not statistically significant"
    print(f"  - Result is {significance} (p = {hr['p_value']:.4f})")
    
    return {
        "output_dir": str(output_path),
        "n_patients": len(data),
        "hazard_ratio": hr,
        "balance": balance,
        "plots": plot_paths
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARTEMIS 3.1 Real Data E2E Demo")
    parser.add_argument("--output-dir", default="./output/real_data_demo", help="Output directory")
    parser.add_argument(
        "--db-connection", 
        default="postgresql://postgres:mypass@localhost:5432/postgres",
        help="PostgreSQL connection string"
    )
    args = parser.parse_args()
    
    run_real_data_demo(args.output_dir, args.db_connection)
