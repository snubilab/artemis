#!/usr/bin/env python
"""
E2E Demo Script for ARTEMIS 3.1.
Phase 4.4.3: End-to-end validation demo.

This script demonstrates the full pipeline from data to report generation.
"""
import argparse
import sys
from pathlib import Path
import pandas as pd
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def generate_synthetic_data(n_treated: int = 500, n_control: int = 500) -> pd.DataFrame:
    """Generate synthetic clinical trial data for demonstration."""
    np.random.seed(42)
    
    n_total = n_treated + n_control
    
    # Treatment assignment
    treatment = np.array([1] * n_treated + [0] * n_control)
    
    # Covariates with some imbalance
    age_treated = np.random.normal(62, 10, n_treated)
    age_control = np.random.normal(60, 10, n_control)
    age = np.concatenate([age_treated, age_control])
    
    bmi_treated = np.random.normal(28, 4, n_treated)
    bmi_control = np.random.normal(27, 4, n_control)
    bmi = np.concatenate([bmi_treated, bmi_control])
    
    # Simulate survival times with treatment effect
    baseline_hazard = 0.001
    treatment_hr = 0.75  # Protective effect
    
    times = []
    events = []
    
    for i in range(n_total):
        # Higher risk with age and BMI
        risk_factor = 1 + 0.02 * (age[i] - 60) + 0.01 * (bmi[i] - 27.5)
        if treatment[i] == 1:
            risk_factor *= treatment_hr
        
        # Exponential survival
        lambda_i = baseline_hazard * risk_factor
        t = np.random.exponential(1 / lambda_i)
        
        # Censor at max follow-up
        max_followup = 365 * 2  # 2 years
        if t > max_followup:
            times.append(max_followup)
            events.append(0)
        else:
            times.append(t)
            events.append(1)
    
    return pd.DataFrame({
        "person_id": range(n_total),
        "treatment": treatment,
        "age": age,
        "bmi": bmi,
        "time": times,
        "event": events
    })


def run_demo(output_dir: str = "./output/e2e_demo"):
    """Run the full E2E demonstration."""
    from src.agents.agent5 import Agent5Workflow
    from src.agents.agent6 import Agent6Workflow
    from src.reporting.models import HazardRatioSummary
    
    print("=" * 60)
    print("ARTEMIS 3.1 End-to-End Demo")
    print("=" * 60)
    
    # Step 1: Generate synthetic data
    print("\n[1/4] Generating synthetic clinical trial data...")
    data = generate_synthetic_data(n_treated=500, n_control=500)
    print(f"  - Total patients: {len(data)}")
    print(f"  - Treated: {(data['treatment'] == 1).sum()}")
    print(f"  - Control: {(data['treatment'] == 0).sum()}")
    print(f"  - Events: {data['event'].sum()}")
    
    # Step 2: Run Agent 5 (Analysis)
    print("\n[2/4] Running Agent 5 (Analysis Agent)...")
    agent5 = Agent5Workflow()
    agent5.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="IPTW")
    results = agent5.run(data=data)
    
    hr = results["hazard_ratio"]
    print(f"  - Hazard Ratio: {hr['hr']:.3f}")
    print(f"  - 95% CI: [{hr['ci_lower']:.3f}, {hr['ci_upper']:.3f}]")
    print(f"  - p-value: {hr['p_value']:.4f}")
    
    # Check balance
    balance = results["balance"]
    print(f"  - Covariates balanced (SMD < 0.1):")
    for cov, vals in balance.items():
        status = "✓" if vals["balanced"] else "✗"
        print(f"    {status} {cov}: SMD = {vals['smd_before']:.3f}")
    
    # Step 3: Run Agent 6 (Reporting)
    print("\n[3/4] Running Agent 6 (Reporting Agent)...")
    
    # Convert to HazardRatioSummary for Agent 6
    hr_summary = HazardRatioSummary(
        hr=hr['hr'],
        ci_lower=hr['ci_lower'],
        ci_upper=hr['ci_upper'],
        p_value=hr['p_value']
    )
    
    agent6 = Agent6Workflow()
    agent6.set_results(
        study_title="ARTEMIS E2E Demo: Synthetic Drug A vs Placebo",
        hazard_ratio=hr_summary,
        target_n=results['n_target'],
        comparator_n=results['n_comparator'],
        balance=results['balance'],
        ps_scores=results['ps_scores'],
        treatment=results['treatment'],
        survival_data=results['survival_data']
    )
    
    # Generate outputs
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    plot_paths = agent6.generate_plots(str(output_path / "plots"))
    print(f"  - Generated plots:")
    for name, path in plot_paths.items():
        print(f"    - {name}: {path}")
    
    # Step 4: Generate HTML report
    print("\n[4/4] Generating report...")
    report_path = str(output_path / "report.html")
    agent6.generate_html_report(report_path)
    print(f"  - Report saved: {report_path}")
    
    # Summary
    print("\n" + "=" * 60)
    print("✅ E2E Demo Complete!")
    print("=" * 60)
    print(f"\nOutputs saved to: {output_path.absolute()}")
    print("\nKey findings:")
    print(f"  - Treatment shows {'protective' if hr['hr'] < 1 else 'harmful'} effect")
    print(f"  - HR = {hr['hr']:.2f} (95% CI: {hr['ci_lower']:.2f}-{hr['ci_upper']:.2f})")
    significance = "statistically significant" if hr['p_value'] < 0.05 else "not statistically significant"
    print(f"  - Result is {significance} (p = {hr['p_value']:.4f})")
    
    return {
        "output_dir": str(output_path),
        "hazard_ratio": hr,
        "balance": balance,
        "plots": plot_paths
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARTEMIS 3.1 E2E Demo")
    parser.add_argument("--output-dir", default="./output/e2e_demo", help="Output directory")
    args = parser.parse_args()
    
    run_demo(args.output_dir)
